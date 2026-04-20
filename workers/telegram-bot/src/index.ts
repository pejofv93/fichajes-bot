// fichajes-bot Telegram Worker v3.1
// Cloudflare Workers + grammy + D1 native binding

import { Bot, webhookCallback, Context } from "grammy";

export interface Env {
  DB: D1Database;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID_ALLOWED: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const bot = new Bot<Context>(env.TELEGRAM_BOT_TOKEN);

    // ── Security: solo Pejo ──────────────────────────────────────────
    bot.use(async (ctx, next) => {
      const allowedId = env.TELEGRAM_CHAT_ID_ALLOWED;
      if (String(ctx.chat?.id) !== allowedId) return;
      await next();
    });

    // ── /start ───────────────────────────────────────────────────────
    bot.command("start", async (ctx) => {
      await ctx.reply(
        "🏆 *Fichajes Bot v3.1 — Real Madrid Transfer Intelligence*\n\n" +
        "Comandos disponibles:\n" +
        "/top — Top 20 fichajes probables\n" +
        "/salidas — Top 10 salidas probables\n" +
        "/explain _nombre_ — Razonamiento completo\n" +
        "/detalle _nombre_ — Info completa\n" +
        "/historico _nombre_ — Score 30 días\n" +
        "/sources _nombre_ — Fuentes del jugador\n" +
        "/castilla — Castilla movimientos\n" +
        "/juvenil — Juvenil A movimientos\n" +
        "/cedidos — Canteranos cedidos\n" +
        "/debut\\_watch — Próximos debuts cantera\n" +
        "/economia — Estado modelo económico\n" +
        "/silencio — Pausar/reanudar alertas\n" +
        "/status — Estado del sistema\n" +
        "/feedback _texto_ — Enviar feedback",
        { parse_mode: "Markdown" }
      );
    });

    // ── /top ─────────────────────────────────────────────────────────
    bot.command("top", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_smoothed, tipo_operacion_principal,
               club_actual, posicion, flags
        FROM jugadores
        WHERE tipo_operacion_principal = 'FICHAJE'
          AND entidad = 'primer_equipo'
          AND score_smoothed >= 0.10
          AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 20
      `).all();

      if (!rows.results.length) {
        await ctx.reply("No hay fichajes en el radar todavía. El sistema está calentando motores. 🔄");
        return;
      }

      const lines = rows.results.map((r: any, i: number) => {
        const pct = Math.round(r.score_smoothed * 100);
        const em = pct >= 70 ? "🟢" : pct >= 40 ? "🟡" : "🔴";
        const flags = JSON.parse(r.flags || "[]") as string[];
        const flagStr = flags.includes("POSIBLE_GLOBO_SONDA") ? " 🎭" : "";
        const posStr = r.posicion ? ` · ${r.posicion}` : "";
        return `${i + 1}. ${em} *${r.nombre_canonico}*${posStr} · ${pct}%${flagStr}`;
      });

      const now = new Date().toLocaleDateString("es-ES", {
        day: "2-digit", month: "2-digit", year: "numeric"
      });

      const msg = `🏆 *TOP 20 FICHAJES · ${now}*\n━━━━━━━━━━━━━━━━━\n\n${lines.join("\n")}\n\n_/explain <nombre> para análisis completo_`;
      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /salidas ──────────────────────────────────────────────────────
    bot.command("salidas", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_smoothed, club_actual, posicion
        FROM jugadores
        WHERE tipo_operacion_principal = 'SALIDA'
          AND entidad = 'primer_equipo'
          AND score_smoothed >= 0.10
          AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 10
      `).all();

      if (!rows.results.length) {
        await ctx.reply("No hay salidas significativas en el radar.");
        return;
      }

      const lines = rows.results.map((r: any, i: number) => {
        const pct = Math.round(r.score_smoothed * 100);
        const em = pct >= 70 ? "🔴" : pct >= 40 ? "🟡" : "🟢";
        return `${i + 1}. ${em} *${r.nombre_canonico}* · ${pct}%`;
      });

      const msg = `📤 *TOP SALIDAS · Real Madrid*\n━━━━━━━━━━━━━━━━━\n\n${lines.join("\n")}`;
      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /explain ─────────────────────────────────────────────────────
    bot.command("explain", async (ctx) => {
      const nombre = ctx.match?.trim();
      if (!nombre) {
        await ctx.reply("Uso: /explain <nombre_jugador>\nEjemplo: /explain Bellingham");
        return;
      }

      const jugador = await env.DB.prepare(`
        SELECT * FROM jugadores
        WHERE LOWER(nombre_canonico) LIKE LOWER(?) OR LOWER(slug) = LOWER(?)
        LIMIT 1
      `).bind(`%${nombre}%`, nombre).first<any>();

      if (!jugador) {
        await ctx.reply(`No encontrado: "${nombre}"\nUsa /top para ver los nombres exactos.`);
        return;
      }

      const history = await env.DB.prepare(`
        SELECT score_nuevo, razon_cambio, timestamp
        FROM score_history
        WHERE jugador_id = ?
        ORDER BY timestamp DESC LIMIT 5
      `).bind(jugador.jugador_id).all();

      const topRumores = await env.DB.prepare(`
        SELECT r.lexico_detectado, r.peso_lexico, r.fecha_publicacion,
               p.nombre_completo as periodista_nombre
        FROM rumores r
        LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
        WHERE r.jugador_id = ? AND r.retractado = 0
        ORDER BY ABS(r.peso_lexico) DESC LIMIT 3
      `).bind(jugador.jugador_id).all();

      const pct = Math.round((jugador.score_smoothed || 0) * 100);
      const factores = parseJSON(jugador.factores_actuales);
      const flags = parseJSON(jugador.flags) as string[];

      const sparkHistory = await env.DB.prepare(`
        SELECT score_nuevo FROM score_history
        WHERE jugador_id = ?
        ORDER BY timestamp DESC LIMIT 14
      `).bind(jugador.jugador_id).all();
      const scores = (sparkHistory.results as any[]).map(r => r.score_nuevo).reverse();
      const sparkline = buildSparkline(scores);

      const msg = [
        `🔬 *Análisis: ${jugador.nombre_canonico}*`,
        `━━━━━━━━━━━━━━━━━━━━`,
        ``,
        `📊 *Score actual: ${pct}%*`,
        `   raw: ${fmt(jugador.score_raw)} | smooth: ${pct}%`,
        ``,
        `🧮 *Factores de scoring:*`,
        `├─ Consenso:     ${fmt(factores.consenso)}`,
        `├─ Credibilidad: ${fmt(factores.credibilidad)}`,
        `├─ Fase rumor:   ${factores.fase_dominante ?? "?"}\/6`,
        `├─ Económico:    ${fmt(factores.factor_econ)}`,
        `├─ Sustitución:  ${fmt(factores.factor_subst)}`,
        `└─ Temporal:     ${fmt(factores.factor_temporal)}`,
        ``,
      ];

      if (topRumores.results.length) {
        msg.push(`📰 *Rumores con más peso:*`);
        (topRumores.results as any[]).forEach((r, i) => {
          const per = r.periodista_nombre || "Fuente desconocida";
          const lex = r.lexico_detectado || "?";
          msg.push(`${i + 1}. ${per} — "${lex}" (${fmt(r.peso_lexico)})`);
        });
        msg.push(``);
      }

      if (sparkline) {
        msg.push(`📈 *Evolución reciente:*\n\`${sparkline}\``);
        msg.push(``);
      }

      if (flags.length) {
        msg.push(`🚩 *Flags:* ${flags.join(", ")}`);
      }

      const fullMsg = msg.join("\n");
      const chunks = splitMessage(fullMsg);
      for (const chunk of chunks) {
        await ctx.reply(chunk, { parse_mode: "Markdown" });
      }
    });

    // ── /status ──────────────────────────────────────────────────────
    bot.command("status", async (ctx) => {
      const metrics = await env.DB.prepare(`
        SELECT metric_name, value, timestamp
        FROM metricas_sistema
        WHERE metric_name IN (
          'last_hot_loop_at', 'last_cold_loop_at',
          'rumores_procesados_hoy', 'gemini_calls_hoy',
          'sources_activas', 'sources_degradadas'
        )
        ORDER BY timestamp DESC
      `).all();

      const m: Record<string, any> = {};
      for (const row of metrics.results as any[]) {
        if (!m[row.metric_name]) m[row.metric_name] = row;
      }

      const jugadoresCount = await env.DB.prepare(
        "SELECT COUNT(*) as n FROM jugadores WHERE is_active=1"
      ).first<any>();

      // Última retractación detectada
      const lastRetraction = await env.DB.prepare(`
        SELECT j.nombre_canonico, r.retractado_at, p.nombre_completo as periodista
        FROM rumores r
        LEFT JOIN jugadores j ON r.jugador_id = j.jugador_id
        LEFT JOIN periodistas p ON r.periodista_id = p.periodista_id
        WHERE r.retractado = 1
        ORDER BY r.retractado_at DESC LIMIT 1
      `).first<any>();

      // Flags activos en el sistema
      const activeFlags = await env.DB.prepare(`
        SELECT flag_name, estado
        FROM flags_sistema
        WHERE estado != 'OFF'
        ORDER BY flag_name
      `).all();

      const retractionLine = lastRetraction
        ? `🚫 Última retractación: ${lastRetraction.nombre_canonico || "?"} (${lastRetraction.retractado_at?.split("T")[0] || "?"})`
        : `✅ Sin retractaciones recientes`;

      const flagLines = (activeFlags.results as any[]).length > 0
        ? `🚩 Flags activos: ${(activeFlags.results as any[]).map((f: any) => `${f.flag_name}=${f.estado}`).join(", ")}`
        : `✅ Sin flags activos`;

      const msg = [
        `⚙️ *Estado del sistema — Fichajes Bot v3.1*`,
        ``,
        `🔄 Último hot-loop: ${m.last_hot_loop_at?.value || "nunca"}`,
        `🌡️ Último cold-loop: ${m.last_cold_loop_at?.value || "nunca"}`,
        `📰 Rumores procesados hoy: ${m.rumores_procesados_hoy?.value || 0}`,
        `🤖 Calls Gemini hoy: ${m.gemini_calls_hoy?.value || 0}/1400`,
        `👥 Jugadores en radar: ${jugadoresCount?.n || 0}`,
        m.sources_degradadas?.value > 0
          ? `⚠️ Fuentes degradadas: ${m.sources_degradadas.value}`
          : `✅ Todas las fuentes operativas`,
        ``,
        retractionLine,
        flagLines,
      ].join("\n");

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /castilla ────────────────────────────────────────────────────
    bot.command("castilla", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_debut, score_fichaje_ext, score_salida, estado
        FROM cantera_jugadores
        WHERE nivel = 'castilla' AND estado = 'activo'
        ORDER BY score_debut DESC LIMIT 10
      `).all();

      if (!rows.results.length) {
        await ctx.reply("Sin datos de Castilla todavía. El scraper de cantera está en configuración.");
        return;
      }

      const lines = (rows.results as any[]).map((r, i) => {
        const debut = Math.round((r.score_debut || 0) * 100);
        return `${i + 1}. *${r.nombre_canonico}* — Debut primer equipo: ${debut}%`;
      });

      await ctx.reply(
        `🏟️ *Real Madrid Castilla*\n━━━━━━━━━━━━━━━\n\n${lines.join("\n")}`,
        { parse_mode: "Markdown" }
      );
    });

    // ── /juvenil ────────────────────────────────────────────────────
    bot.command("juvenil", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_debut, edad, posicion
        FROM cantera_jugadores
        WHERE nivel = 'juvenil_a' AND estado = 'activo'
        ORDER BY score_debut DESC LIMIT 10
      `).all();

      if (!rows.results.length) {
        await ctx.reply("Sin datos de Juvenil A todavía.");
        return;
      }

      const lines = (rows.results as any[]).map((r, i) => {
        const debut = Math.round((r.score_debut || 0) * 100);
        const edad = r.edad ? ` (${r.edad}a)` : "";
        return `${i + 1}. *${r.nombre_canonico}*${edad} · ${r.posicion || "?"} — ${debut}%`;
      });

      await ctx.reply(
        `⭐ *Juvenil A — Talentos*\n━━━━━━━━━━━━━━━\n\n${lines.join("\n")}`,
        { parse_mode: "Markdown" }
      );
    });

    // ── /debut_watch ─────────────────────────────────────────────────
    bot.command("debut_watch", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_smoothed, entidad, posicion, edad
        FROM jugadores
        WHERE entidad IN ('castilla', 'juvenil_a')
          AND score_smoothed >= 0.3
          AND is_active = 1
        ORDER BY score_smoothed DESC LIMIT 5
      `).all();

      if (!rows.results.length) {
        await ctx.reply("Sin candidatos a debut identificados actualmente.");
        return;
      }

      const lines = (rows.results as any[]).map((r, i) => {
        const pct = Math.round((r.score_smoothed || 0) * 100);
        const em = pct >= 70 ? "🟢" : pct >= 40 ? "🟡" : "🔴";
        const nivel = r.entidad === "castilla" ? "Castilla" : "Juvenil A";
        const pos = r.posicion ? ` · ${r.posicion}` : "";
        const edad = r.edad ? ` (${r.edad}a)` : "";
        return `${i + 1}. ${em} *${r.nombre_canonico}*${edad}${pos} [${nivel}] — ${pct}%`;
      });

      await ctx.reply(
        `🌟 *DEBUT WATCH — Próximos 5 candidatos*\n━━━━━━━━━━━━━━━\n\n${lines.join("\n")}\n\n_Probabilidad estimada de debut en primer equipo_`,
        { parse_mode: "Markdown" }
      );
    });

    // ── /cedidos ────────────────────────────────────────────────────
    bot.command("cedidos", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT cj.nombre_canonico, c.club_cesion, c.liga_cesion,
               c.probabilidad_retorno, c.probabilidad_venta, c.opcion_compra_m
        FROM cedidos c
        JOIN cantera_jugadores cj ON c.jugador_id = cj.jugador_id
        WHERE c.activa = 1
        ORDER BY c.probabilidad_retorno DESC LIMIT 10
      `).all();

      if (!rows.results.length) {
        await ctx.reply("Sin cedidos registrados actualmente.");
        return;
      }

      const lines = (rows.results as any[]).map((r, i) => {
        const ret = Math.round((r.probabilidad_retorno || 0) * 100);
        const venta = Math.round((r.probabilidad_venta || 0) * 100);
        const compra = r.opcion_compra_m ? ` · OC: ${(r.opcion_compra_m / 1e6).toFixed(0)}M€` : "";
        return `${i + 1}. *${r.nombre_canonico}* @ ${r.club_cesion}${compra}\n   Retorno: ${ret}% · Venta: ${venta}%`;
      });

      await ctx.reply(
        `🔄 *Cedidos RM*\n━━━━━━━━━━━━━━━\n\n${lines.join("\n\n")}`,
        { parse_mode: "Markdown" }
      );
    });

    // ── /economia ────────────────────────────────────────────────────
    bot.command("economia", async (ctx) => {
      const econ = await env.DB.prepare(
        "SELECT * FROM modelo_economico WHERE activo = 1 ORDER BY fecha_actualizacion DESC LIMIT 1"
      ).first<any>();

      if (!econ) {
        await ctx.reply("Modelo económico no disponible. El cold-loop lo cargará en el próximo ciclo.");
        return;
      }

      const msg = [
        `💰 *Modelo Económico RM · ${econ.temporada || "?"}*`,
        `_Actualizado: ${new Date(econ.fecha_actualizacion).toLocaleDateString("es-ES")}_`,
        `_Fuente: ${econ.fuente || "?"} (confianza ${Math.round((econ.confianza || 0) * 100)}%)_`,
        ``,
        `Tope salarial LaLiga: ${fmtM(econ.tope_laliga_rm)}`,
        `Masa salarial actual: ${fmtM(econ.masa_salarial_actual)}`,
        `Margen disponible: *${fmtM(econ.margen_salarial)}*`,
        `Presupuesto fichajes: *${fmtM(econ.presupuesto_fichajes_restante)}*`,
        ``,
        `Regla FFP: ${econ.regla_actual || "?"}`,
        `Política edad máx: ${econ.politica_edad_max || "?"}`,
      ].join("\n");

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /silencio ────────────────────────────────────────────────────
    bot.command("silencio", async (ctx) => {
      const current = await env.DB.prepare(
        "SELECT estado FROM flags_sistema WHERE flag_name = 'alertas_realtime'"
      ).first<any>();

      const newState = current?.estado === "ENFORCE_HARD" ? "OFF" : "ENFORCE_HARD";
      await env.DB.prepare(
        "UPDATE flags_sistema SET estado = ?, actualizado_at = CURRENT_TIMESTAMP WHERE flag_name = 'alertas_realtime'"
      ).bind(newState).run();

      const msg = newState === "OFF"
        ? "🔕 Alertas pausadas. Usa /silencio para reactivar."
        : "🔔 Alertas reactivadas.";
      await ctx.reply(msg);
    });

    // ── /feedback ────────────────────────────────────────────────────
    bot.command("feedback", async (ctx) => {
      const text = ctx.match?.trim();
      if (!text) {
        await ctx.reply("Uso: /feedback <tu mensaje>\nEjemplo: /feedback El bot no registró el fichaje de X");
        return;
      }
      await env.DB.prepare(
        "INSERT INTO alertas_log (log_id, feedback_usuario, enviada_at) VALUES (?, ?, CURRENT_TIMESTAMP)"
      ).bind(crypto.randomUUID(), text).run();
      await ctx.reply("✅ Feedback registrado. Gracias Pejo 🏆");
    });

    // ── /detalle ─────────────────────────────────────────────────────
    bot.command("detalle", async (ctx) => {
      const nombre = ctx.match?.trim();
      if (!nombre) {
        await ctx.reply("Uso: /detalle <nombre_jugador>");
        return;
      }

      const jugador = await env.DB.prepare(`
        SELECT j.*, me.margen_salarial
        FROM jugadores j
        LEFT JOIN modelo_economico me ON me.activo=1
        WHERE LOWER(j.nombre_canonico) LIKE LOWER(?) OR LOWER(j.slug) = LOWER(?)
        LIMIT 1
      `).bind(`%${nombre}%`, nombre).first<any>();

      if (!jugador) {
        await ctx.reply(`No encontrado: "${nombre}"`);
        return;
      }

      const n_rumores = await env.DB.prepare(
        "SELECT COUNT(*) as n FROM rumores WHERE jugador_id=? AND retractado=0"
      ).bind(jugador.jugador_id).first<any>();

      const msg = [
        `📋 *Ficha: ${jugador.nombre_canonico}*`,
        `━━━━━━━━━━━━━━━━━━━━`,
        `Posición: ${jugador.posicion || "?"}`,
        `Club actual: ${jugador.club_actual || "?"}`,
        `Edad: ${jugador.edad || "?"}`,
        `Valor de mercado: ${fmtM(jugador.valor_mercado_m)}`,
        ``,
        `📊 Score: ${Math.round((jugador.score_smoothed || 0) * 100)}%`,
        `🎯 Tipo operación: ${jugador.tipo_operacion_principal}`,
        `📰 Rumores registrados: ${n_rumores?.n || 0}`,
        `🏷️ Primera mención: ${jugador.primera_mencion_at?.split("T")[0] || "?"}`,
        ``,
        `_/explain ${jugador.nombre_canonico} para análisis completo_`,
      ].join("\n");

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /historico ───────────────────────────────────────────────────
    bot.command("historico", async (ctx) => {
      const nombre = ctx.match?.trim();
      if (!nombre) {
        await ctx.reply("Uso: /historico <nombre_jugador>");
        return;
      }

      const jugador = await env.DB.prepare(
        "SELECT jugador_id, nombre_canonico FROM jugadores WHERE LOWER(nombre_canonico) LIKE LOWER(?) LIMIT 1"
      ).bind(`%${nombre}%`).first<any>();

      if (!jugador) {
        await ctx.reply(`No encontrado: "${nombre}"`);
        return;
      }

      const hist = await env.DB.prepare(`
        SELECT score_nuevo, delta, razon_cambio, timestamp
        FROM score_history
        WHERE jugador_id = ?
        ORDER BY timestamp DESC LIMIT 30
      `).bind(jugador.jugador_id).all();

      if (!hist.results.length) {
        await ctx.reply("Sin historial disponible para este jugador.");
        return;
      }

      const scores = (hist.results as any[]).map(r => r.score_nuevo).reverse();
      const sparkline = buildSparkline(scores);

      const lines = (hist.results as any[]).slice(0, 10).map(r => {
        const pct = Math.round((r.score_nuevo || 0) * 100);
        const delta = r.delta ? (r.delta > 0 ? `+${Math.round(r.delta * 100)}` : `${Math.round(r.delta * 100)}`) : "0";
        const fecha = r.timestamp?.split("T")[0] || "?";
        return `${fecha}: ${pct}% (${delta}) — ${r.razon_cambio || "?"}`;
      });

      const msg = [
        `📈 *Histórico score: ${jugador.nombre_canonico}*`,
        `\`${sparkline}\``,
        ``,
        ...lines,
      ].join("\n");

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /sources ─────────────────────────────────────────────────────
    bot.command("sources", async (ctx) => {
      const nombre = ctx.match?.trim();
      if (!nombre) {
        await ctx.reply("Uso: /sources <nombre_jugador>");
        return;
      }

      const jugador = await env.DB.prepare(
        "SELECT jugador_id, nombre_canonico FROM jugadores WHERE LOWER(nombre_canonico) LIKE LOWER(?) LIMIT 1"
      ).bind(`%${nombre}%`).first<any>();

      if (!jugador) {
        await ctx.reply(`No encontrado: "${nombre}"`);
        return;
      }

      const fuentes = await env.DB.prepare(`
        SELECT p.nombre_completo, p.tier, p.reliability_global,
               COUNT(r.rumor_id) as n_rumores,
               MAX(r.fecha_publicacion) as ultimo_rumor
        FROM rumores r
        JOIN periodistas p ON r.periodista_id = p.periodista_id
        WHERE r.jugador_id = ? AND r.retractado = 0
        GROUP BY r.periodista_id
        ORDER BY n_rumores DESC LIMIT 8
      `).bind(jugador.jugador_id).all();

      if (!fuentes.results.length) {
        await ctx.reply("Sin fuentes registradas para este jugador.");
        return;
      }

      const lines = (fuentes.results as any[]).map((f, i) => {
        const rel = Math.round((f.reliability_global || 0) * 100);
        const last = f.ultimo_rumor?.split("T")[0] || "?";
        return `${i + 1}. [${f.tier}] *${f.nombre_completo}* · ${rel}% fiabilidad · ${f.n_rumores} rumores · último: ${last}`;
      });

      await ctx.reply(
        `📡 *Fuentes: ${jugador.nombre_canonico}*\n━━━━━━━━━━━━━━━\n\n${lines.join("\n")}`,
        { parse_mode: "Markdown" }
      );
    });

    return webhookCallback(bot, "cloudflare-mod")(request);
  },
};

// ── Utilities ──────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined): string {
  if (v == null) return "?";
  return `${Math.round(v * 100)}%`;
}

function fmtM(v: number | null | undefined): string {
  if (v == null) return "?";
  return `${(v / 1_000_000).toFixed(0)}M€`;
}

function parseJSON(s: string | null | undefined): any {
  if (!s) return {};
  try { return JSON.parse(s); } catch { return {}; }
}

function buildSparkline(scores: number[]): string {
  if (!scores.length) return "";
  const chars = "▁▂▃▄▅▆▇█";
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 0.01;
  return scores
    .map(s => chars[Math.min(7, Math.floor(((s - min) / range) * 8))])
    .join("");
}

function splitMessage(text: string, maxLen = 4000): string[] {
  if (text.length <= maxLen) return [text];
  const chunks: string[] = [];
  let current = "";
  for (const line of text.split("\n")) {
    if (current.length + line.length + 1 > maxLen) {
      chunks.push(current.trim());
      current = "";
    }
    current += line + "\n";
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}
