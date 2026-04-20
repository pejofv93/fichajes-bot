# fichajes-bot v3.1 🏆

> **Real Madrid Transfer Intelligence System**
> 0€/mes · GitHub Actions + Cloudflare D1 + Telegram Bot
> Construido por Claude Code. Pejo solo consigue API keys.

## Resumen

Sistema de inteligencia de fichajes del Real Madrid. Scrape automatizado de RSS + Bluesky + web estático, scoring Bayesiano con Kalman smoothing, alertas a Telegram con hasta 2h de latencia (el price of free).

**Coste mensual: 0€.** Para siempre.

---

## Checklist de configuración para Pejo

### FASE 0 — API Keys (30 min)

Necesitas 8 valores. Todos gratis, sin tarjeta de crédito.

```
CLOUDFLARE_ACCOUNT_ID       → cloudflare.com dashboard
CLOUDFLARE_D1_DATABASE_ID   → cloudflare.com → Workers & Pages → D1
CLOUDFLARE_API_TOKEN        → cloudflare.com → My Profile → API Tokens
GEMINI_API_KEY              → aistudio.google.com → Get API key
TELEGRAM_BOT_TOKEN          → @BotFather → /newbot
TELEGRAM_CHAT_ID            → api.telegram.org/bot{TOKEN}/getUpdates
BLUESKY_HANDLE              → tu-bot.bsky.social
BLUESKY_APP_PASSWORD        → bsky.app → Settings → App Passwords
```

Ver `PRIMEROS_PASOS.md` para instrucciones paso a paso.

### FASE 1 — GitHub Secrets (10 min)

Repo → Settings → Secrets and variables → Actions → New repository secret

Añade los 8 valores de arriba como secrets.

### FASE 2 — Iniciar Claude Code (5 min)

```bash
cd fichajes-bot
claude
```

El PROJECT_KNOWLEDGE_v3.1.md ya está en el repo. Claude Code hace el resto.

### FASE 3 — Verificación (5 min)

```bash
python scripts/verify_setup.py
```

---

## Arquitectura

```
GitHub Actions (crons)
  hot-loop:   cada 2h  → RSS + Bluesky tier-S → process → score → alert
  cold-loop:  cada 4h  → RSS tier A/B/C + web scraping → process → score
  daily-report: 08:00  → Informe diario a Telegram
  calibrator: 02:00    → Auto-calibración Bayesiana
  archiver:   lun 03:00→ Limpieza + GitHub Pages
  health-check: cada 6h→ Monitoreo de salud del sistema

Cloudflare D1 (SQLite 5GB free)
  18 tablas: jugadores, rumores, periodistas, lexicon, ...

Cloudflare Workers (TypeScript)
  Bot Telegram: /top /explain /status /economia ...
```

### Presupuesto de minutos GitHub Actions

| Workflow | Cron | Min/mes |
|---|---|---|
| hot-loop | cada 2h | 720 |
| cold-loop | cada 4h | 360 |
| daily-report | 06:00 UTC | 30 |
| evening-update | 18:00 UTC | 30 |
| calibrator | 00:00 UTC | 90 |
| archiver | lunes 01:00 UTC | 32 |
| health-check | cada 6h | 120 |
| ci | push/PR | ~24 |
| **TOTAL** | | **~1406/2000** ✅ |

---

## Lo que Pejo NO toca nunca

- ❌ Código Python, TypeScript, SQL
- ❌ `git commit`, `git push` (Claude Code lo hace)
- ❌ Deploys manuales (workflows y wrangler lo hacen)
- ❌ Reiniciar servidores (no hay servidores)
- ❌ Actualizar dependencias (Dependabot + Claude Code)

---

## Comandos del bot Telegram

```
/top          Top 20 fichajes probables
/salidas      Top 10 salidas probables
/explain X    Análisis completo de un jugador
/detalle X    Ficha del jugador
/historico X  Score últimos 30 días
/sources X    Fuentes que reportan sobre X
/castilla     Castilla movimientos
/juvenil      Juvenil A movimientos
/cedidos      Canteranos cedidos
/economia     Modelo económico RM
/silencio     Pausar/reanudar alertas
/status       Estado del sistema
/feedback X   Enviar feedback
```

---

## Stack

- **LLM**: Gemini Flash (1500 req/día gratis)
- **Noticias**: feedparser (RSS) + atproto (Bluesky)
- **Scraping**: selectolax (HTML estático, SIN Playwright)
- **BD**: Cloudflare D1 (5GB free, ~33 años de margen)
- **Bot**: grammy + Cloudflare Workers
- **CI/CD**: GitHub Actions (1406/2000 min/mes)
- **Python**: 3.11, uv, pydantic v2, loguru, tenacity

---

*🏆 Hala Madrid. Con datos, sin excusas, sin facturas.*
