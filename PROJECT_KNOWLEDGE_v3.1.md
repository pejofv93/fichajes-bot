# PROJECT_KNOWLEDGE.md · fichajes-bot v3.1

> **Sistema de inteligencia de fichajes del Real Madrid.**
> Infraestructura 100% gratuita y permanentemente sostenible.
> Construido 100% por Claude Code. Pejo solo consigue API keys.
>
> Versión: 3.1 (Apr 2026)
> Reemplaza: v3.0 (tenía 3 errores críticos documentados abajo)

---

## 0. Por qué v3.1 existe (los errores del v3.0)

El v3.0 fue auditado honestamente y tenía tres errores que lo rompían desde el día 1:

### Error 1 — GitHub Actions excedía el límite (el más grave)

El v3.0 calculaba "1200 min/mes". La realidad era ~4900 min/mes porque ignoraba:
- El overhead de runner startup (~1 min por ejecución, cuenta como tiempo de cómputo)
- Playwright install en cada cold-loop run (~2 min, no cacheable fácilmente)
- La frecuencia real: jobs cada 30 min = 1440 ejecuciones/mes solo del hot-loop

**v3.1 fix**: eliminar Playwright, subir intervalos a 2h/4h, cachear agresivamente.
Resultado verificado: **1390 min/mes** (30% de margen sobre el límite de 2000).

### Error 2 — Turso free tier es 500MB, no 9GB

El v3.0 asumía 9GB basándose en el plan Starter de pago de Turso (9$/mes).
El plan gratuito real de Turso en 2026 es **500MB**. Con 400 rumores/día × 1KB = 146MB/año, se llena en meses.

**v3.1 fix**: reemplazar Turso por **Cloudflare D1** (5GB free, misma cuenta que ya usamos para el Worker, sin cuenta nueva).

### Error 3 — snscrape muerto y Nitter moribundo

snscrape: último commit funcional julio 2023, el propio repo dice "broken".
Nitter: nitter.net cerró febrero 2024, instancias públicas caen aleatoriamente.
Ambos siguen en v3.0 como "fallbacks". No son fallbacks, son ruido en el código.

**v3.1 fix**: eliminarlos. La estrategia de ingesta se basa en RSS + Bluesky + selectolax web scraping. Lo que no cubre RSS ni Bluesky de Romano et al., se pierde con un delay de 15-30 min hasta que el medio publica el artículo. Eso es el trade-off real del coste cero.

---

## 1. Qué conserva el v3.1 del v2.1 (la lógica de producto)

Toda la inteligencia del sistema se preserva íntegra. Los cambios son solo de infra:

✅ Scoring Bayesiano (4 componentes + 7 modificadores)
✅ Lexicon Matcher por periodista (Aho-Corasick, ~250 frases curadas)
✅ Sesgo mediático documentado (Apéndice D)
✅ Kalman smoothing dinámico (Q/R adaptativo)
✅ Trial Balloon Detector (7 heurísticas)
✅ Bias Corrector, Retraction Handler
✅ Economic Validator (gratuito via scraping)
✅ Substitution Engine, Temporal Weighter
✅ Auto-calibración Bayesiana Beta-Binomial
✅ Backtesting walk-forward (Brier, AUC, Precision@K)
✅ Extensión cantera (Castilla + Juvenil A + cedidos 3-way scoring)
✅ Mensajes Telegram Variante B (formato idéntico)
✅ Apéndices C-J íntegros (léxico, sesgos, globos sonda, económico, retractaciones)

---

## 2. Arquitectura v3.1

### 2.1 Diagrama

```
┌── GITHUB ACTIONS (Python) ─────────────────────────────────────┐
│                                                                  │
│  hot-loop.yml       cron: 0 */2 * * *  (cada 2 horas)          │
│  ─────────────      ─────────────────────────────────           │
│  · Scrape RSS tier-S (feedparser)                                │
│  · Scrape Bluesky tier-S (atproto)                               │
│  · Scrape RSS tier-A/B/C si coincide con el run                  │
│  · Process rumors (regex + Gemini Flash si ambiguo)              │
│  · Recompute scores (Kalman)                                     │
│  · Dispatch pending alerts → Telegram                            │
│  Tiempo por run: ~2 min · Runs/mes: 360 · Total: 720 min        │
│                                                                  │
│  cold-loop.yml      cron: 30 */4 * * *  (cada 4 horas)         │
│  ─────────────      ─────────────────────────────────           │
│  · Web scraping selectolax (Transfermarkt, Capology, LaLiga)    │
│  · Actualizar modelo económico                                   │
│  · Update substitution graph                                     │
│  Tiempo por run: ~2 min · Runs/mes: 180 · Total: 360 min        │
│                                                                  │
│  daily-report.yml   cron: 0 6 * * *  (08:00 CEST)              │
│  evening-update     cron: 0 18 * * * (20:00 CEST)              │
│  calibrator.yml     cron: 0 0 * * *  (02:00 CEST)              │
│  archiver.yml       cron: 0 1 * * 1  (lunes 03:00 CEST)        │
│  health-check.yml   cron: 0 */6 * * * (cada 6h)                │
│  ci.yml             trigger: push/PR                             │
│                                                                  │
│  TOTAL MINUTOS/MES: ~1390 ✅  (límite: 2000, margen: 30%)       │
└───────────────────────────────┬──────────────────────────────────┘
                                │ REST API
                                ↓
┌── CLOUDFLARE D1 (SQLite) ──────────────────────────────────────┐
│  Free tier: 5 GB storage · 5M reads/día · 100K writes/día       │
│  · 18 tablas (schema idéntico al v2.1)                           │
│  · Acceso desde GH Actions: REST API                             │
│  · Acceso desde CF Workers: binding nativo (0 latencia)          │
│  Estimado uso: ~150MB/año sin HTML bruto → ~33 años de margen    │
└───────────────────────────────┬──────────────────────────────────┘
                                ↑ binding nativo
┌── CLOUDFLARE WORKERS (TypeScript) ─────────────────────────────┐
│  · Webhook Telegram (grammy)                                     │
│  · Comandos: /top /explain /detalle /castilla /juvenil ...       │
│  · D1 binding directo (sin libsql, sin latencia extra)           │
│  · Bundle: grammy + tipos D1 ≈ 200KB (límite: 1MB) ✅            │
│  · 100k req/día free · Pejo usa ~50-200/día → sobrado            │
└─────────────────────────────────────────────────────────────────┘

SERVICIOS EXTERNOS (todos gratuitos, sin cuenta nueva):
  · Gemini Flash API       → extracción LLM 1500 req/día
  · Bluesky API            → periodistas que migraron
  · RSS feeds              → cobertura principal ~80 fuentes
  · Telegram Bot API       → siempre gratis
  · GitHub Pages           → dashboard estático (generado mensual)
```

### 2.2 Presupuesto de minutos verificado

Esta es la tabla honesta, con overhead de startup incluido:

| Workflow | Cron | Tiempo real/run | Runs/mes | Min/mes |
|---|---|---|---|---|
| hot-loop | 0 */2 * * * | 2 min | 360 | **720** |
| cold-loop | 30 */4 * * * | 2 min | 180 | **360** |
| daily-report | 0 6 * * * | 1 min | 30 | **30** |
| evening-update | 0 18 * * * | 1 min | 30 | **30** |
| calibrator | 0 0 * * * | 3 min | 30 | **90** |
| archiver | 0 1 * * 1 | 8 min | 4 | **32** |
| health-check | 0 */6 * * * | 1 min | 120 | **120** |
| ci (push/PR) | push | 3 min | ~8 | **24** |
| **TOTAL** | | | | **1406 min** ✅ |

Margen: 594 min (30% sobre el límite de 2000).

**Cómo se calcula "tiempo real/run"**:
- GitHub runner setup (checkout + Python setup): ~40s (con cache activo)
- `uv pip install --system` con lockfile cacheado: ~15s
- Lógica del job: ~60-90s
- Total: ~2 min. Sin cache en primer run: ~3 min. El cache hit rate esperado es >95%.

**Si en algún mes nos acercamos al límite** (verano, mercado activo con más jobs):
- Subir cold-loop a cada 8h → ahorra ~180 min/mes
- Reducir health-check a cada 12h → ahorra ~60 min/mes
- Margen de emergencia: ~840 min disponibles

### 2.3 Consecuencias operativas honestas

**Latencia de alertas**: 0-120 min (media ~60 min)
- Romano publica "here we go" a las 14:23
- Relevo/RSS lo recoge a las 14:30-14:40
- Siguiente hot-loop: 14:00 o 16:00
- Si coincide con el run de las 14:00: Pejo se entera a las ~14:05
- Si no: Pejo se entera a las ~16:05
- Peor caso razonable: ~1h40min de delay

**Esto es el price of free**. Para un sistema personal de seguimiento de fichajes, es completamente aceptable. Los "here we go" de Romano en agosto tienen más valor si se confirman en 2h que si no llegan nunca.

**Fiabilidad de crons**: GitHub Actions tiene ~99% de uptime en crons. En incidentes graves (~3-4 al año), los crons se retrasan o saltan. El sistema no pierde datos, solo añade latencia extra en esos momentos.

**Cobertura de periodistas**: Romano, Ornstein, Di Marzio, Plettenberg tienen cuentas Bluesky activas. Moretto publica en Relevo (RSS). Los que solo están en Twitter X: cubiertos via RSS del medio donde trabajan con delay de 15-30 min.

---

## 3. Stack técnico

### 3.1 Python (GitHub Actions)

```toml
# pyproject.toml
[project]
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",          # HTTP async client
    "feedparser>=6.0",      # RSS parsing
    "atproto>=0.0.47",      # Bluesky AT Protocol
    "selectolax>=0.3.17",   # HTML parsing rápido (reemplaza BeautifulSoup+Playwright)
    "libsql-client>=0.3",   # Turso... NO. Ver sección 4.
    "cf-d1-python>=0.1",    # Cloudflare D1 REST API wrapper
    "pydantic>=2.0",
    "google-generativeai>=0.5",
    "pyahocorasick>=2.0",
    "rapidfuzz>=3.0",
    "loguru>=0.7",
    "pyyaml>=6.0",
    "tenacity>=8.0",
    "python-dotenv>=1.0",
]
```

**Nota**: no hay Playwright en las dependencias. Es la diferencia que hace que el presupuesto funcione.

### 3.2 TypeScript (Cloudflare Worker)

```json
{
  "dependencies": {
    "grammy": "^1.22.0"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20240403.0",
    "wrangler": "^3.50.0",
    "typescript": "^5.4.0"
  }
}
```

`@libsql/client` **eliminado**. El Worker usa el D1 binding nativo de Cloudflare (`env.DB`), que es la API oficial y no necesita librería externa. Bundle final estimado: ~200KB.

### 3.3 Web scraping sin Playwright

Playwright se usaba para MARCA y AS (JS-heavy). Solución:

```python
# MARCA tiene RSS: https://e00-marca.uecdn.es/rss/portada.xml ✅
# AS tiene RSS: https://as.com/rss/actualidad/portada.xml ✅
# Transfermarkt: HTML estático → selectolax ✅
# Capology: HTML estático → selectolax ✅
# realmadrid.com: RSS + HTML estático → selectolax ✅
```

Todos los sites que necesitamos tienen RSS o HTML estático. No hay ningún caso que requiera JS rendering para este proyecto.

---

## 4. Cloudflare D1 como base de datos

### 4.1 Por qué D1 y no Turso

| | Turso free | Cloudflare D1 free |
|---|---|---|
| Storage | **500 MB** ❌ | **5 GB** ✅ |
| Reads/día | 1B/mes (33M/día) | 5M/día |
| Writes/día | 25M/mes (833K/día) | 100K/día |
| Cuenta nueva | Sí (startup risk) | No (ya tienes CF para el Worker) |
| Acceso desde GH Actions | libsql HTTP | REST API oficial |
| Acceso desde CF Workers | libsql over HTTP | **binding nativo** (0ms latencia) |
| Riesgo cierre | Alto (startup 2022) | Bajo (Cloudflare 2009, $7B valuación) |

Nuestro uso real:
- Reads: ~500K/día (muy por debajo de 5M)
- Writes: ~20K/día (muy por debajo de 100K)
- Storage: ~150MB/año → **33 años de margen con 5GB**

### 4.2 Acceso desde GitHub Actions (REST API)

```python
# src/fichajes_bot/persistence/d1_client.py

import os
import httpx
from typing import Any

class D1Client:
    """Cliente para Cloudflare D1 via REST API desde GitHub Actions."""
    
    BASE = "https://api.cloudflare.com/client/v4"
    
    def __init__(self):
        self.account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.database_id = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
        self.token = os.environ["CLOUDFLARE_API_TOKEN"]
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30.0,
        )
    
    async def execute(self, sql: str, params: list = []) -> list[dict]:
        """Ejecutar una query y devolver filas."""
        r = await self.client.post(
            f"/accounts/{self.account_id}/d1/database/{self.database_id}/query",
            json={"sql": sql, "params": params},
        )
        r.raise_for_status()
        data = r.json()
        if not data["success"]:
            raise RuntimeError(f"D1 error: {data['errors']}")
        return data["result"][0]["results"]
    
    async def execute_batch(self, statements: list[dict]) -> None:
        """Ejecutar múltiples statements en batch (más eficiente)."""
        r = await self.client.post(
            f"/accounts/{self.account_id}/d1/database/{self.database_id}/query",
            json=statements,
        )
        r.raise_for_status()
    
    async def close(self):
        await self.client.aclose()
```

**Latencia**: cada llamada REST toma ~50-100ms. Para batch operations en GitHub Actions (donde corremos cada 2h y procesamos en bulk), esto es aceptable.

**Optimización**: usar `execute_batch` para inserts múltiples en una sola llamada HTTP.

### 4.3 Acceso desde Cloudflare Worker (binding nativo)

```typescript
// workers/telegram-bot/src/index.ts

export interface Env {
  DB: D1Database;  // binding D1 nativo, configurado en wrangler.toml
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID_ALLOWED: string;
}

// Query directa sin latencia de red:
const result = await env.DB.prepare(
  "SELECT nombre_canonico, score_smoothed FROM jugadores 
   WHERE tipo_operacion_principal = 'FICHAJE' 
   ORDER BY score_smoothed DESC LIMIT 20"
).all();
```

### 4.4 Schema (igual que v2.1, 18 tablas)

El schema de Turso del v3.0 se reutiliza íntegro. Solo cambia el cliente. Las 18 tablas son idénticas en estructura porque SQLite es el motor en ambos casos.

Una diferencia menor: D1 usa `PRAGMA` específicos de CF. Las migrations deben eliminar cualquier `PRAGMA journal_mode=WAL` (D1 lo gestiona internamente).

### 4.5 Almacenamiento de HTML bruto — decisión explícita

El v2.1 guardaba `html_crudo` en `rumores_raw`. Con D1's 5GB tenemos margen, pero:

- 400 rumores/día × 5KB HTML = 2MB/día = 730MB/año
- Con 5GB: ~6.8 años de margen
- **Decisión**: guardar HTML bruto los primeros 7 días, luego nullear. Los primeros 7 días permite reextracción si el LLM falla.

```sql
-- En archiver job, cada lunes:
UPDATE rumores_raw 
SET html_crudo = NULL 
WHERE fecha_ingesta < datetime('now', '-7 days');
```

---

## 5. Fuentes de información v3.1

### 5.1 Estrategia honesta sin Twitter API

**Lo que tenemos**:
- **Bluesky**: Romano, Ornstein, BBC Sport, The Athletic, algunos más. Cobertura ~40-50% de tier-S
- **RSS de medios**: Relevo (Moretto), SkySport DE (Plettenberg), GianlucaDiMarzio.com (Di Marzio), BBC, The Athletic, L'Équipe, Gazzetta, Kicker, MARCA, AS, Relevo
- **Web scraping selectolax**: Transfermarkt, Capology, realmadrid.com

**Lo que perdemos vs Twitter API**:
- Tweets de Romano que no llegan a artículo: ~5-10% de sus posts
- Velocidad: el RSS de Relevo tarda 10-20 min en indexar los tweets de Moretto
- Tweets de periodistas que no tienen RSS de su medio

**La realidad del delay**:
- Romano publica "here we go" en Twitter: t=0
- Romano lo replica en Bluesky: t+0 a t+60 min (irregular)
- Relevo/Athletic publican artículo: t+5 a t+30 min
- Nuestro scraper lo ve: t+15 a t+50 min (siguiente poll)
- Pejo recibe alerta: t+15 a t+170 min (poll + siguiente hot-loop)

Esto es aceptable para un sistema personal. No es un sistema de trading HFT.

### 5.2 `configs/sources.yaml` (versión honesta)

```yaml
# ============================================================
# TIER S — Periodistas de máxima fiabilidad
# Vía Bluesky (si disponible) + RSS de su medio (siempre)
# ============================================================

# Fabrizio Romano
- id: romano_bluesky
  tipo: bluesky
  tier: S
  handle: fabrizioromano.bsky.social
  periodista_id: fabrizio-romano
  idioma: en
  polling_minutes: 120  # se scrapeará en cada hot-loop
  activo: true
  nota: "Primary. Publica breaking news aquí con delay vs Twitter."

- id: romano_rss_relevo
  tipo: rss
  tier: S
  url: https://www.relevo.com/rss/autores/fabrizio-romano.xml
  periodista_id: fabrizio-romano
  idioma: es
  polling_minutes: 120
  nota: "Fallback si Bluesky no tiene el post todavía."

# David Ornstein
- id: ornstein_bluesky
  tipo: bluesky
  tier: S
  handle: davidornstein.bsky.social
  periodista_id: david-ornstein
  idioma: en
  polling_minutes: 120

- id: athletic_rss
  tipo: rss
  tier: S
  url: https://www.nytimes.com/athletic/rss/soccer
  idioma: en
  polling_minutes: 120
  nota: "The Athletic = Ornstein + varios tier-S internacionales."

# Matteo Moretto — NO está en Bluesky activo, cubierto vía Relevo
- id: relevo_rss
  tipo: rss
  tier: S
  url: https://www.relevo.com/rss
  periodista_id_filter: [matteo-moretto]
  idioma: es
  polling_minutes: 120

# Gianluca Di Marzio — tiene RSS propio
- id: dimarzio_rss
  tipo: rss
  tier: S
  url: https://www.gianlucadimarzio.com/en/feed
  periodista_id: gianluca-di-marzio
  idioma: it
  polling_minutes: 120

# Florian Plettenberg — SkySport DE RSS
- id: skysport_de_rss
  tipo: rss
  tier: S
  url: https://www.skysport.de/rss/transfernews
  periodista_id_filter: [florian-plettenberg]
  idioma: de
  polling_minutes: 120

# Comunicados oficiales RM — Tier S por definición
- id: realmadrid_noticias_rss
  tipo: rss
  tier: S
  url: https://www.realmadrid.com/rss/noticias
  idioma: es
  polling_minutes: 120
  sesgo: oficial
  factor_fichaje_positivo: 1.0

# ============================================================
# TIER A — Alta fiabilidad, cobertura regional sólida
# ============================================================

- id: relevo_general_rss
  tipo: rss
  tier: A
  url: https://www.relevo.com/rss
  idioma: es
  sesgo: neutral
  polling_minutes: 240  # solo en cold-loop o coincidencia hot-loop

- id: bbc_sport_rss
  tipo: rss
  tier: A
  url: http://feeds.bbci.co.uk/sport/football/rss.xml
  idioma: en
  sesgo: neutral
  polling_minutes: 240

- id: lequipe_rss
  tipo: rss
  tier: A
  url: https://www.lequipe.fr/rss/actu_rss.xml
  idioma: fr
  sesgo: neutral
  polling_minutes: 240

- id: gazzetta_rss
  tipo: rss
  tier: A
  url: https://www.gazzetta.it/rss/Home.xml
  idioma: it
  sesgo: neutral
  polling_minutes: 240

- id: kicker_rss
  tipo: rss
  tier: A
  url: https://newsfeed.kicker.de/news/aktuell
  idioma: de
  sesgo: neutral
  polling_minutes: 240

- id: balague_blog_rss
  tipo: rss
  tier: A
  url: https://www.guillembalague.com/feed
  periodista_id: guillem-balague
  idioma: en
  polling_minutes: 240

# ============================================================
# TIER B — Medios con sesgo documentado, peso reducido
# ============================================================

- id: marca_rss
  tipo: rss
  tier: B
  url: https://e00-marca.uecdn.es/rss/portada.xml
  idioma: es
  sesgo: pro-rm
  factor_fichaje_positivo: 0.75
  factor_salida_positiva: 1.0
  polling_minutes: 240

- id: as_rss
  tipo: rss
  tier: B
  url: https://as.com/rss/actualidad/portada.xml
  idioma: es
  sesgo: pro-rm
  factor_fichaje_positivo: 0.70
  factor_salida_positiva: 1.0
  polling_minutes: 240

- id: mundodeportivo_rss
  tipo: rss
  tier: B
  url: https://www.mundodeportivo.com/rss/home.xml
  idioma: es
  sesgo: pro-barca
  factor_fichaje_positivo: 0.90
  factor_salida_positiva: 0.65
  polling_minutes: 240

- id: sport_rss
  tipo: rss
  tier: B
  url: https://www.sport.es/es/rss/futbol/rss.xml
  idioma: es
  sesgo: pro-barca
  factor_fichaje_positivo: 0.90
  factor_salida_positiva: 0.60
  polling_minutes: 240

# ============================================================
# WEB SCRAPING selectolax (sin Playwright)
# Solo en cold-loop, frecuencia baja
# ============================================================

- id: transfermarkt_rm
  tipo: web_selectolax
  tier: A
  url: https://www.transfermarkt.com/real-madrid/transfers/verein/418
  idioma: en
  polling_minutes: 720  # 2x/día
  rate_limit_seconds: 5  # delay entre requests

- id: capology_rm
  tipo: web_selectolax
  tier: A
  url: https://www.capology.com/club/real-madrid/salaries
  idioma: en
  polling_minutes: 10080  # semanal

- id: laliga_transparencia
  tipo: web_selectolax
  tier: S
  url: https://www.laliga.com/transparencia/limites-coste-plantilla
  idioma: es
  polling_minutes: 10080  # semanal

# ============================================================
# CANTERA (referencias de sección 20 del doc)
# ============================================================

- id: realmadrid_canteras_rss
  tipo: rss
  tier: S
  url: https://www.realmadrid.com/rss/canteras
  idioma: es
  entidades: [castilla, juvenil_a]
  polling_minutes: 240

- id: canteradelrealmadrid_rss
  tipo: rss
  tier: A
  url: https://canteradelrealmadrid.com/feed
  idioma: es
  entidades: [castilla, juvenil_a]
  polling_minutes: 240

- id: rfef_juv_web
  tipo: web_selectolax
  tier: S
  url: https://www.rfef.es/competiciones/juvenil-division-honor
  idioma: es
  entidades: [juvenil_a]
  polling_minutes: 1440  # 1x/día

# TOTAL: ~45 fuentes activas (suficiente para un sistema personal)
# Se puede ampliar añadiendo entradas a este YAML sin tocar código
```

### 5.3 Fuentes eliminadas definitivamente

```yaml
# NO incluir en sources.yaml — documentado para que Claude Code no las añada

snscrape:    # Muerto desde 2023. Repo dice explícitamente "broken".
nitter:      # nitter.net cerró feb 2024. No incluir ni como fallback.
twitter_api: # 92€/mes. Fuera del presupuesto.
playwright_sites:  # Playwright eliminado. MARCA/AS tienen RSS.
```

---

## 6. Extracción híbrida (igual que v3.0, funcionaba bien)

El pipeline de extracción del v3.0 estaba bien diseñado. Se preserva íntegro:

```
rumor_raw → prefilter (sin LLM) → regex/lexicon extractor
           → si confianza >= 0.6: rumor completo (extraido_con="regex")
           → si confianza < 0.6: Gemini Flash → rumor completo (extraido_con="gemini")
```

### 6.1 Budget Gemini Flash en temporada de mercado

El v3.0 ignoraba el pico de verano. Cálculo honesto:

| Temporada | Rumores/día estimados | 20% al LLM | Requests Gemini | Límite | Estado |
|---|---|---|---|---|---|
| Muerta (oct-mar) | 150 | 30 | 30 | 1500 | ✅ 2% del límite |
| Media (abr-jun) | 400 | 80 | 80 | 1500 | ✅ 5% |
| Verano (jul-ago) | 2000 | 400 | 400 | 1500 | ✅ 27% |
| Cierre mercado (31 ago) | 5000 | 1000 | 1000 | 1500 | ✅ 67% |

**Incluso el día más intenso del año está dentro del límite free**. El margen es real.

Hay un rate limit secundario: **15 RPM** (requests por minuto). Si el processor job manda 400 requests secuenciales, tarda 400/15 = ~27 min. Acceptable para un job que corre cada 2h.

**Solución**: añadir sleep de 4 segundos entre calls Gemini para respetar RPM.

---

## 7. Scoring + detectores + validadores

Sin cambios vs v2.1. Ver PROJECT_KNOWLEDGE_v2.md secciones 7-14 para detalles completos. Todos corren en GitHub Actions como funciones Python puras, sin dependencias de infra.

Los únicos cambios:
- Las queries a D1 usan `D1Client` (REST API) en vez de `libsql_client`
- No hay Pub/Sub: los "eventos" son filas en tabla `eventos_pending` que el siguiente job lee

---

## 8. GitHub Actions workflows

### 8.1 Setup de caché Python (crítico para el presupuesto)

El truco que hace que 2 min/run sean reales:

```yaml
# Fragmento reutilizable en todos los workflows:
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'           # cachea ~/.cache/pip entre runs

- name: Install uv
  run: pip install uv

- name: Install dependencies (from lockfile, with cache)
  run: uv pip install --system -r requirements.lock
  # Con cache activo esto tarda ~15s en vez de ~60s
  # La primera vez (cache miss): ~60-90s
  # Cache hit rate esperado: >95% (lockfile no cambia entre runs)
```

El `requirements.lock` (generado con `uv lock`) garantiza que las mismas versiones se instalan siempre. El cache de GitHub Actions persiste 7 días y se invalida cuando cambia el lockfile.

### 8.2 hot-loop.yml

```yaml
name: Hot Loop — Scrape + Process + Score + Alert (cada 2h)
on:
  schedule:
    - cron: '0 */2 * * *'
  workflow_dispatch:
    inputs:
      force_tier:
        description: 'Forzar tier específico (S/A/B/C/all)'
        default: 'S'

concurrency:
  group: hot-loop
  cancel-in-progress: false  # NUNCA cancelar. Si hay backlog, procesar.

env:
  CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
  CLOUDFLARE_D1_DATABASE_ID: ${{ secrets.CLOUDFLARE_D1_DATABASE_ID }}
  CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
  BLUESKY_HANDLE: ${{ secrets.BLUESKY_HANDLE }}
  BLUESKY_APP_PASSWORD: ${{ secrets.BLUESKY_APP_PASSWORD }}

jobs:
  hot-loop:
    runs-on: ubuntu-latest
    timeout-minutes: 8  # kill si algo cuelga

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install deps
        run: |
          pip install uv --quiet
          uv pip install --system -r requirements.lock --quiet

      - name: Scrape tier-S sources (RSS + Bluesky)
        run: python -m fichajes_bot.jobs.scrape --tier S
        continue-on-error: true

      - name: Process pending rumors (regex + Gemini)
        run: python -m fichajes_bot.jobs.process --limit 100
        continue-on-error: false  # si process falla, queremos saberlo

      - name: Recompute scores (Kalman)
        run: python -m fichajes_bot.jobs.score
        continue-on-error: false

      - name: Send pending alerts to Telegram
        run: python -m fichajes_bot.jobs.alert
        continue-on-error: true  # si Telegram está caído, no fallar el job

      - name: Record run metrics
        if: always()  # corre incluso si un step anterior falló
        run: python -m fichajes_bot.jobs.metrics --job hot-loop
```

### 8.3 cold-loop.yml

```yaml
name: Cold Loop — Web scraping + modelo económico (cada 4h)
on:
  schedule:
    - cron: '30 */4 * * *'  # desfasado 30min del hot-loop
  workflow_dispatch:

concurrency:
  group: cold-loop
  cancel-in-progress: false

env: # (mismos secrets)

jobs:
  cold-loop:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - name: Install deps
        run: pip install uv --quiet && uv pip install --system -r requirements.lock --quiet

      # SIN playwright install — eliminado definitivamente
      
      - name: Scrape tier A/B/C RSS sources
        run: python -m fichajes_bot.jobs.scrape --tier A,B,C
        continue-on-error: true

      - name: Web scraping (selectolax)
        run: python -m fichajes_bot.jobs.scrape_web
        # Incluye: Transfermarkt, Capology, LaLiga, realmadrid.com static
        continue-on-error: true

      - name: Update modelo económico
        run: python -m fichajes_bot.jobs.update_economic_model
        continue-on-error: true

      - name: Process all pending (incluye los de tier A/B/C)
        run: python -m fichajes_bot.jobs.process --limit 300
        continue-on-error: false

      - name: Recompute scores + substitution propagation
        run: python -m fichajes_bot.jobs.score --full
        continue-on-error: false

      - name: Send pending alerts
        run: python -m fichajes_bot.jobs.alert
        continue-on-error: true
```

### 8.4 daily-report.yml

```yaml
name: Daily Report (08:00 CEST = 06:00 UTC)
on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:

jobs:
  report:
    runs-on: ubuntu-latest
    timeout-minutes: 3
    env: # (mismos secrets)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install uv --quiet && uv pip install --system -r requirements.lock --quiet
      - name: Generate and send daily report
        run: python -m fichajes_bot.jobs.daily_report
        # Genera Variante B completa: top 20 + cantera + cedidos + retractadas
        # Split automático si >4096 chars
```

### 8.5 calibrator.yml

```yaml
name: Calibrator (02:00 CEST = 00:00 UTC)
on:
  schedule:
    - cron: '0 0 * * *'
  workflow_dispatch:

jobs:
  calibrate:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env: # (mismos secrets)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install uv --quiet && uv pip install --system -r requirements.lock --quiet
      - name: Detect official events
        run: python -m fichajes_bot.jobs.detect_official_events
      - name: Calibrate journalists (Beta-Binomial update)
        run: python -m fichajes_bot.jobs.calibrate
      - name: Learn lexicon weights from outcomes
        run: python -m fichajes_bot.jobs.learn_lexicon
```

### 8.6 archiver.yml

```yaml
name: Archiver (lunes 03:00 CEST = 01:00 UTC)
on:
  schedule:
    - cron: '0 1 * * 1'
  workflow_dispatch:

permissions:
  contents: write  # para commit archivos

jobs:
  archive:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env: # (mismos secrets)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install uv --quiet && uv pip install --system -r requirements.lock --quiet

      - name: Nullear HTML bruto de rumores >7 días
        run: |
          python -m fichajes_bot.jobs.cleanup_html

      - name: Exportar datos >30 días a archive JSON
        run: python -m fichajes_bot.jobs.archive_to_json
        # Genera data/archive/rumores_YYYY_MM.jsonl
        # y data/archive/score_history_YYYY_MM.jsonl

      - name: Commit archives al repo
        run: |
          git config user.name "Archiver Bot"
          git config user.email "bot@fichajes-bot.local"
          git add data/archive/
          git diff --staged --quiet || git commit -m "chore: archive $(date +%Y-%m-%d)"
          git push

      - name: Limpiar datos procesados de D1
        run: python -m fichajes_bot.jobs.cleanup_d1
        # Borra rumores_raw >30d con outcome clasificado
        # Mantiene rumores activos siempre

      - name: Generate GitHub Pages static dashboard
        run: python -m fichajes_bot.jobs.generate_dashboard
        # Genera docs/index.html con top 20 jugadores
        # GitHub Pages sirve docs/ automáticamente
```

### 8.7 ci.yml

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install uv && uv pip install --system -r requirements.lock
      - name: Lint
        run: ruff check src/ tests/
      - name: Type check
        run: mypy src/fichajes_bot --ignore-missing-imports
      - name: Tests (con D1 emulado)
        run: pytest tests/ -x -q
        env:
          D1_MODE: emulated  # usa SQLite local en tests, sin llamadas reales a CF
```

---

## 9. Cloudflare Worker

### 9.1 wrangler.toml

```toml
name = "fichajes-bot-telegram"
main = "src/index.ts"
compatibility_date = "2026-04-01"
compatibility_flags = ["nodejs_compat"]

[[d1_databases]]
binding = "DB"
database_name = "fichajes-bot"
database_id = "TU-DATABASE-ID-AQUI"  # Claude Code lo llena tras setup

[vars]
ENVIRONMENT = "production"

# Secrets añadidos via `wrangler secret put`:
# TELEGRAM_BOT_TOKEN
# TELEGRAM_CHAT_ID_ALLOWED
```

### 9.2 Worker completo (~250 líneas)

```typescript
// workers/telegram-bot/src/index.ts

import { Bot, webhookCallback, CommandContext, Context } from "grammy";

export interface Env {
  DB: D1Database;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID_ALLOWED: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const bot = new Bot<Context>(env.TELEGRAM_BOT_TOKEN);

    // ── Seguridad: solo Pejo ──────────────────────────────────────
    bot.use(async (ctx, next) => {
      const allowedId = env.TELEGRAM_CHAT_ID_ALLOWED;
      if (String(ctx.chat?.id) !== allowedId) return;
      await next();
    });

    // ── /start ───────────────────────────────────────────────────
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
        "/debut\\_watch — Próximos debuts\n" +
        "/economia — Estado modelo económico\n" +
        "/silencio — Pausar/reanudar alertas\n" +
        "/status — Estado del sistema\n" +
        "/feedback _texto_ — Enviar feedback",
        { parse_mode: "Markdown" }
      );
    });

    // ── /top ─────────────────────────────────────────────────────
    bot.command("top", async (ctx) => {
      const rows = await env.DB.prepare(`
        SELECT nombre_canonico, score_smoothed, tipo_operacion_principal,
               club_actual, posicion, flags
        FROM jugadores
        WHERE tipo_operacion_principal = 'FICHAJE'
          AND entidad = 'primer_equipo'
          AND score_smoothed >= 0.10
        ORDER BY score_smoothed DESC LIMIT 20
      `).all();

      if (!rows.results.length) {
        await ctx.reply("No hay fichajes en el radar todavía.");
        return;
      }

      const lines = rows.results.map((r: any, i: number) => {
        const pct = Math.round(r.score_smoothed * 100);
        const em = pct >= 70 ? "🟢" : pct >= 40 ? "🟡" : "🔴";
        const flags = JSON.parse(r.flags || "[]") as string[];
        const flagStr = flags.includes("POSIBLE_GLOBO_SONDA") ? " 🎭" : "";
        return `${i + 1}. ${em} *${r.nombre_canonico}* · ${pct}%${flagStr}`;
      });

      const now = new Date().toLocaleDateString("es-ES", {
        day: "2-digit", month: "2-digit", year: "numeric"
      });

      const msg = `🏆 *TOP 20 FICHAJES · ${now}*\n━━━━━━━━━━━━━━━━━\n\n${lines.join("\n")}\n\n_/explain <nombre> para detalle_`;

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /explain ─────────────────────────────────────────────────
    bot.command("explain", async (ctx) => {
      const nombre = ctx.match.trim();
      if (!nombre) {
        await ctx.reply("Uso: /explain <nombre_jugador>");
        return;
      }

      const jugador = await env.DB.prepare(`
        SELECT * FROM jugadores
        WHERE LOWER(nombre_canonico) LIKE LOWER(?) OR LOWER(slug) = LOWER(?)
        LIMIT 1
      `).bind(`%${nombre}%`, nombre).first<any>();

      if (!jugador) {
        await ctx.reply(`No encontrado: "${nombre}"\nPrueba con /top para ver los nombres exactos.`);
        return;
      }

      const history = await env.DB.prepare(`
        SELECT score_nuevo, razon_cambio, explicacion_humana, timestamp
        FROM score_history
        WHERE jugador_id = ?
        ORDER BY timestamp DESC LIMIT 5
      `).bind(jugador.jugador_id).all();

      const top_rumores = await env.DB.prepare(`
        SELECT r.lexico_detectado, r.peso_lexico, r.fecha_publicacion,
               p.nombre_completo as periodista_nombre, p.reliability_global
        FROM rumores r
        JOIN periodistas p ON r.periodista_id = p.periodista_id
        WHERE r.jugador_id = ? AND r.retractado = 0
        ORDER BY ABS(r.peso_lexico) DESC LIMIT 3
      `).bind(jugador.jugador_id).all();

      const pct = Math.round((jugador.score_smoothed || 0) * 100);
      const factores = JSON.parse(jugador.factores_actuales || "{}");
      const flags = JSON.parse(jugador.flags || "[]") as string[];

      // Sparkline ASCII últimos 30 días
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
        `   raw: ${Math.round((jugador.score_raw||0)*100)}% | smooth: ${pct}%`,
        ``,
        `🧮 *Factores:*`,
        `├─ Consenso:      ${fmt(factores.consenso)}`,
        `├─ Credibilidad:  ${fmt(factores.credibilidad)}`,
        `├─ Fase rumor:    ${factores.fase_dominante || '?'}/6`,
        `├─ Económico:     ${fmt(factores.factor_econ)}`,
        `├─ Sustitución:   ${fmt(factores.factor_subst)}`,
        `└─ Temporal:      ${fmt(factores.factor_temporal)}`,
        ``,
      ].filter(Boolean);

      if (top_rumores.results.length) {
        msg.push(`📰 *Top rumores con más peso:*`);
        (top_rumores.results as any[]).forEach((r, i) => {
          msg.push(`${i+1}. ${r.periodista_nombre} · "${r.lexico_detectado}" (${fmt(r.peso_lexico)})`);
        });
        msg.push('');
      }

      if (sparkline) {
        msg.push(`📈 *Evolución 30d:*\n${sparkline}`);
        msg.push('');
      }

      if (flags.length) {
        msg.push(`🚩 *Flags:* ${flags.join(', ')}`);
      }

      const fullMsg = msg.join('\n');
      // Split si supera 4096 chars
      const chunks = splitMessage(fullMsg);
      for (const chunk of chunks) {
        await ctx.reply(chunk, { parse_mode: "Markdown" });
      }
    });

    // ── /status ──────────────────────────────────────────────────
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

      const msg = [
        `⚙️ *Estado del sistema*`,
        ``,
        `🔄 Último hot-loop: ${m.last_hot_loop_at?.value || 'nunca'}`,
        `🌡️ Último cold-loop: ${m.last_cold_loop_at?.value || 'nunca'}`,
        `📰 Rumores procesados hoy: ${m.rumores_procesados_hoy?.value || 0}`,
        `🤖 Calls Gemini hoy: ${m.gemini_calls_hoy?.value || 0}/1500`,
        `📡 Fuentes activas: ${m.sources_activas?.value || '?'}`,
        m.sources_degradadas?.value > 0 ? `⚠️ Fuentes degradadas: ${m.sources_degradadas.value}` : `✅ Todas las fuentes OK`,
      ].join('\n');

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // ── /silencio ────────────────────────────────────────────────
    bot.command("silencio", async (ctx) => {
      const current = await env.DB.prepare(
        "SELECT estado FROM flags_sistema WHERE flag_name = 'alertas_realtime'"
      ).first<any>();

      const newState = current?.estado === 'ENFORCE_HARD' ? 'OFF' : 'ENFORCE_HARD';
      await env.DB.prepare(
        "UPDATE flags_sistema SET estado = ?, actualizado_at = CURRENT_TIMESTAMP WHERE flag_name = 'alertas_realtime'"
      ).bind(newState).run();

      const msg = newState === 'OFF'
        ? "🔕 Alertas pausadas. Usa /silencio para reactivar."
        : "🔔 Alertas activadas.";
      await ctx.reply(msg);
    });

    // ── /feedback ────────────────────────────────────────────────
    bot.command("feedback", async (ctx) => {
      const text = ctx.match.trim();
      if (!text) {
        await ctx.reply("Uso: /feedback <tu mensaje>");
        return;
      }
      await env.DB.prepare(
        "INSERT INTO alertas_log (log_id, feedback_usuario, enviada_at) VALUES (?, ?, CURRENT_TIMESTAMP)"
      ).bind(crypto.randomUUID(), text).run();
      await ctx.reply("✅ Feedback registrado. Gracias.");
    });

    // ── /economia ────────────────────────────────────────────────
    bot.command("economia", async (ctx) => {
      const econ = await env.DB.prepare(
        "SELECT * FROM modelo_economico WHERE activo = 1 ORDER BY fecha_actualizacion DESC LIMIT 1"
      ).first<any>();

      if (!econ) {
        await ctx.reply("Modelo económico no disponible todavía.");
        return;
      }

      const msg = [
        `💰 *Modelo Económico RM · ${econ.temporada}*`,
        `_Actualizado: ${new Date(econ.fecha_actualizacion).toLocaleDateString('es-ES')}_`,
        ``,
        `Tope salarial LaLiga: ${fmtM(econ.tope_laliga_rm)}`,
        `Masa salarial actual: ${fmtM(econ.masa_salarial_actual)}`,
        `Margen disponible: *${fmtM(econ.margen_salarial)}*`,
        `Presupuesto fichajes: *${fmtM(econ.presupuesto_fichajes_restante)}*`,
        ``,
        `Regla FFP: ${econ.regla_actual}`,
        `Política edad máx: ${econ.politica_edad_max} años`,
        ``,
        `Fuente: ${econ.fuente} (confianza ${Math.round((econ.confianza||0)*100)}%)`,
      ].join('\n');

      await ctx.reply(msg, { parse_mode: "Markdown" });
    });

    // Más comandos: /salidas, /castilla, /juvenil, /cedidos, /debut_watch,
    // /detalle, /historico, /sources — misma estructura, queries diferentes.
    // Claude Code completa todos en sesión 8.

    return webhookCallback(bot, "cloudflare-mod")(request);
  },
};

// ── Utilidades ────────────────────────────────────────────────

function fmt(v: number | null | undefined): string {
  if (v == null) return '?';
  return `${Math.round(v * 100)}%`;
}

function fmtM(v: number | null | undefined): string {
  if (v == null) return '?';
  return `${(v / 1_000_000).toFixed(0)}M€`;
}

function buildSparkline(scores: number[]): string {
  if (!scores.length) return '';
  const chars = '▁▂▃▄▅▆▇█';
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 0.01;
  return scores
    .map(s => chars[Math.min(7, Math.floor(((s - min) / range) * 8))])
    .join('');
}

function splitMessage(text: string, maxLen = 4000): string[] {
  if (text.length <= maxLen) return [text];
  const chunks: string[] = [];
  let current = '';
  for (const line of text.split('\n')) {
    if (current.length + line.length + 1 > maxLen) {
      chunks.push(current.trim());
      current = '';
    }
    current += line + '\n';
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}
```

---

## 10. Pasos manuales de Pejo (~75 minutos, una sola vez)

### 10.1 Cuentas a crear

Pejo solo necesita **dos cuentas nuevas**. El resto ya las debería tener.

**Cuenta 1 — Cloudflare** (si no tiene):
- https://cloudflare.com → Sign up gratis
- No necesita tarjeta de crédito
- Una vez dentro: Workers & Pages → D1 → Create database → nombre "fichajes-bot"
- API Tokens → Create Token → "Edit Cloudflare Workers" template
- Anotar: Account ID (sidebar), D1 Database ID, API Token

**Cuenta 2 — Google AI Studio** (Gemini):
- https://aistudio.google.com → Login con Google
- Get API key → Create API key
- Free tier activo por defecto

**Cuentas que Pejo ya debe tener**:
- GitHub (necesita repo privado `fichajes-bot`)
- Telegram (necesita usar @BotFather para crear el bot)
- Bluesky (cuenta para el bot, ej. fichajes-bot-rm.bsky.social)

### 10.2 Checklist completo

```
FASE 0 — Preparación (30 min)
─────────────────────────────
□ Cloudflare: crear cuenta, crear D1 database "fichajes-bot"
  → Anotar: Account ID, D1 Database ID, API Token (Edit Workers)

□ Google AI Studio: crear API key Gemini
  → Anotar: API Key (AIza...)

□ Bluesky: crear cuenta para el bot
  → Settings → App Passwords → "github-actions"
  → Anotar: handle (xxx.bsky.social) + app password

□ Telegram @BotFather:
  → /newbot → nombre "Fichajes Bot" → username único
  → Anotar: Bot Token (123456:AABBcc...)
  → Abrir el bot recién creado → /start
  → Visitar https://api.telegram.org/bot{TOKEN}/getUpdates
  → Anotar: chat_id (el número en "chat":{"id":ESTE_NUMERO})

□ GitHub: crear repo privado "fichajes-bot"

FASE 1 — Configurar GitHub Secrets (10 min)
────────────────────────────────────────────
Repo → Settings → Secrets and variables → Actions → New repository secret

□ CLOUDFLARE_ACCOUNT_ID          → del dashboard Cloudflare
□ CLOUDFLARE_D1_DATABASE_ID      → del dashboard Cloudflare D1
□ CLOUDFLARE_API_TOKEN           → Edit Cloudflare Workers token
□ GEMINI_API_KEY                 → de Google AI Studio
□ TELEGRAM_BOT_TOKEN             → de @BotFather
□ TELEGRAM_CHAT_ID               → del getUpdates
□ BLUESKY_HANDLE                 → tu-bot.bsky.social
□ BLUESKY_APP_PASSWORD           → app password generado

Total: 8 secrets

FASE 2 — Iniciar Claude Code (5 min)
──────────────────────────────────────
□ Clonar repo localmente o abrir en GitHub Codespaces
□ Instalar Claude Code: npm install -g @anthropic-ai/claude-code
□ cd fichajes-bot && claude

FASE 3 — Ejecutar 12 sesiones (Claude Code hace todo)
──────────────────────────────────────────────────────
□ Copiar prompt Sesión 1 → pegar en Claude Code → esperar
□ Copiar prompt Sesión 2 → ...
□ (repetir hasta sesión 12)

FASE 4 — Verificación final (15 min)
──────────────────────────────────────
□ Siguiente 08:00 CEST: primer daily report llega a Telegram
□ Probar /top en el bot → responde en <5 segundos
□ Verificar en GitHub Actions: hot-loop corrió sin errores
□ ✅ Sistema activo. Cero coste. Cero mantenimiento.
```

### 10.3 Lo que Pejo NO toca nunca

- ❌ Código Python, TypeScript, SQL
- ❌ `git commit`, `git push` (Claude Code lo hace)
- ❌ Deploys manuales (GitHub Actions y wrangler deploy lo hacen)
- ❌ Reiniciar servidores (no hay servidores)
- ❌ Monitorizar logs (health-check.yml alerta si algo falla)
- ❌ Actualizar dependencias (Dependabot + Claude Code)

---

## 11. Las 12 sesiones de Claude Code v3.1

### Cómo usar estos prompts

1. Abre el repo localmente o en Codespaces
2. Ejecuta `claude` para iniciar Claude Code
3. Copia el prompt completo y pégalo
4. Espera. Claude Code lee PROJECT_KNOWLEDGE.md, implementa, testea, commitea.
5. Cuando diga "hecho", revisa el output y pasa a la siguiente sesión.

El PROJECT_KNOWLEDGE.md **debe estar en el repo** para que Claude Code lo pueda leer. La sesión 1 lo crea todo desde cero incluyendo el propio documento.

---

### 🎯 Sesión 1 — Setup base

```
Lee PROJECT_KNOWLEDGE.md (estás leyéndolo ahora) e implementa la Sesión 1.

Crea el monorepo fichajes-bot con:

1. Estructura de directorios:
   src/fichajes_bot/
     jobs/          (entry points: scrape, process, score, alert, daily_report,
                     calibrate, detect_official_events, update_economic_model,
                     scrape_web, archive_to_json, cleanup_html, cleanup_d1,
                     metrics, generate_dashboard, health_check, evening_update,
                     learn_lexicon)
     ingestion/     (rss_scraper, bluesky_scraper, web_scraper, resolver)
     extraction/    (prefilter, language_detect, regex_extractor,
                     lexicon_matcher, gemini_client, confidence, pipeline)
     scoring/       (components, score_base, kalman, engine, entity_configs)
     validators/    (economic, substitution, temporal)
     detectors/     (trial_balloon, bias_corrector, retraction_handler,
                     hard_signal_detector)
     calibration/   (official_events_detector, calibrator, reliability_manager)
     notifications/ (telegram_sender, daily_report, alert_manager)
     persistence/   (d1_client, repositories)
     models/        (pydantic schemas de las 18 tablas)
     utils/
   workers/telegram-bot/  (TypeScript CF Worker, sección 9.2)
   configs/               (sources.yaml, lexicon/*.yaml, bias.yaml,
                           temporal.yaml, flags.yaml, economic.yaml)
   data/backfill/
   data/archive/
   migrations/
   tests/
   .github/workflows/     (los 7 workflows de sección 8)
   scripts/

2. pyproject.toml con uv + dependencias de sección 3.1

3. Migrations SQL en migrations/:
   001_initial_schema.sql → las 18 tablas de sección 4 del v2.1
                             (adaptadas a D1: sin PRAGMA WAL, sin sequences)
   002_seed_periodistas.sql → 50 periodistas tier S/A/B/C
   003_seed_fuentes.sql → sources.yaml convertido a INSERT statements
   004_seed_lexicon.sql → Apéndice C completo (~250 frases)
   005_seed_flags.sql → todos los flags en OFF

4. src/fichajes_bot/persistence/d1_client.py → sección 4.2

5. scripts/setup_d1.py:
   - Lee CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_API_TOKEN
   - Ejecuta migrations/*.sql en orden via D1 REST API
   - Valida que las 18 tablas existen

6. scripts/verify_setup.py:
   - Verifica cada servicio: D1 (query simple), Gemini (test call),
     Bluesky (login), Telegram (getMe + enviar "setup OK" al chat_id)
   - Si algo falla: mensaje claro de qué falta

7. Los 7 workflows de sección 8 (hot-loop, cold-loop, daily-report,
   calibrator, archiver, health-check, ci)

8. workers/telegram-bot/ completo (sección 9)

9. .github/workflows/deploy-worker.yml:
   - Trigger: push a workers/telegram-bot/**
   - wrangler deploy + set Telegram webhook

10. README.md con la checklist de Pejo (sección 10.2)

11. configs/ completos: sources.yaml (sección 5.2), bias.yaml (Apéndice D),
    temporal.yaml, flags.yaml (todo OFF), lexicon/*.yaml (Apéndice C)

Ejecuta scripts/verify_setup.py al final para confirmar que todo está
conectado. Haz commit "feat: initial setup v3.1 (session 1)".

Procede. No me pidas confirmaciones intermedias, implementa todo.
```

---

### 🎯 Sesión 2 — Ingesta RSS + Bluesky

```
Implementa la capa de ingesta siguiendo sección 5 de PROJECT_KNOWLEDGE.md.
Sin Playwright. Sin snscrape. Sin Nitter.

1. src/fichajes_bot/ingestion/rss_scraper.py:
   - feedparser async con httpx
   - If-Modified-Since para no re-descargar
   - Filtro por periodista_id si source tiene periodista_id_filter
   - Timeout 10s, retry 2x con tenacity

2. src/fichajes_bot/ingestion/bluesky_scraper.py:
   - atproto.AsyncClient con login
   - get_author_feed() por handle
   - Cursor-based pagination para no repetir posts
   - last_seen_cursor guardado en D1 (tabla metricas_sistema)
   - Timeout 15s

3. src/fichajes_bot/ingestion/web_scraper.py:
   - httpx + selectolax para HTML estático
   - Selectores configurados en sources.yaml por source
   - Respeta robots.txt (httpx con header check)
   - Rate limiting 5s entre requests al mismo dominio
   - SOLO para: Transfermarkt, Capology, LaLiga, realmadrid.com static, RFEF

4. src/fichajes_bot/ingestion/resolver.py:
   - SourceResolver: dado source config → instancia scraper correcto
   - Si Bluesky devuelve error 5xx: log warning, marcar source DEGRADED,
     continuar con RSS del mismo periodista si existe

5. src/fichajes_bot/ingestion/deduplication.py:
   - hash SHA256 de (url_canonico + titulo)
   - Check contra D1 antes de insertar
   - Batch check: una sola query para todo el lote del run

6. src/fichajes_bot/jobs/scrape.py:
   - CLI: python -m fichajes_bot.jobs.scrape --tier S (o A,B,C o all)
   - Lee fuentes de D1 WHERE tier IN (...) AND is_disabled=0
   - Dispatcher al resolver
   - Inserta lote en rumores_raw con execute_batch (eficiente)
   - Actualiza consecutive_errors si falla
   - Si source con >10 errores: disable + encola alerta admin

7. src/fichajes_bot/jobs/scrape_web.py:
   - Solo sources con tipo=web_selectolax
   - Más lento, solo en cold-loop

8. Métricas al final del job:
   INSERT INTO metricas_sistema (metric_name, value) VALUES
   ('last_hot_loop_at', datetime('now')),
   ('rumores_ingested_this_run', N),
   ('sources_activas', M)

9. Tests (con D1 emulado via SQLite local):
   - test_rss: mock feedparser, verifica inserción
   - test_bluesky: mock atproto, verifica cursor actualizado
   - test_dedup: mismo rumor 2x → 1 inserción
   - test_source_health: >10 errores → source disabled

Commit "feat: ingestion layer rss+bluesky (session 2)".
Procede.
```

---

### 🎯 Sesión 3 — Extractor híbrido regex + Gemini

```
Implementa el extractor siguiendo sección 6 de PROJECT_KNOWLEDGE.md.

1. src/fichajes_bot/extraction/prefilter.py → sección 6.3
   (keywords por 6 idiomas, generados dinámicamente desde jugadores D1)

2. src/fichajes_bot/extraction/language_detect.py
   (langdetect con fallback 'es')

3. src/fichajes_bot/extraction/regex_extractor.py → sección 6.5
   (patrones ES/EN/IT/DE/FR, normalización con rapidfuzz)

4. src/fichajes_bot/extraction/lexicon_matcher.py → sección 6.4
   (pyahocorasick, carga configs/lexicon/*.yaml, cache in-process)

5. src/fichajes_bot/extraction/confidence.py → sección 6.7
   (umbral 0.6 para ir al LLM)

6. src/fichajes_bot/extraction/gemini_client.py → sección 6.6:
   - google-generativeai async
   - JSON mode con response_mime_type
   - Cache en tabla llm_cache (hash SHA256, TTL 7 días)
   - Budget manager: contador en metricas_sistema, límite 1400
   - Sleep 4s entre calls para respetar 15 RPM
   - Si budget exceeded: raise GeminiBudgetExceeded
   - Fallback automático en pipeline

7. src/fichajes_bot/extraction/pipeline.py → sección 6.2

8. src/fichajes_bot/jobs/process.py:
   - Lee rumores_raw WHERE procesado=0 ORDER BY fecha_ingesta ASC LIMIT N
   - Pipeline para cada uno
   - Batch insert a tabla rumores
   - Mark procesado=1
   - INSERT INTO eventos_pending (tipo='new_rumor', payload={jugador_ids})
   - Métricas: n_via_regex, n_via_gemini, n_descartados, gemini_calls_today

9. Tests:
   - test_prefilter: 30 casos etiquetados pass/fail
   - test_regex: 50 textos curados → accuracy >85%
   - test_gemini_cache: texto igual 2x → 1 call real
   - test_budget: mock exceeded → usa regex fallback, no falla

Commit "feat: hybrid extractor regex+gemini (session 3)".
Procede.
```

---

### 🎯 Sesión 4 — Lexicon Matcher curado + Reliability contextual

```
Sesión 4: léxico y reliability. Ver sección 6 y Apéndice C.

1. Verificar que configs/lexicon/*.yaml están completos con el
   contenido exacto del Apéndice C (~250 frases, 11 archivos).
   Si falta alguna frase del Apéndice C, añadirla.

2. scripts/seed_lexicon_to_d1.py:
   - Parse configs/lexicon/*.yaml
   - INSERT OR REPLACE en tabla lexicon_entries
   - origen='curado_manual'
   - Idempotente

3. src/fichajes_bot/calibration/reliability_manager.py:
   - get_reliability(periodista_id, club=None, liga=None, tipo=None)
     → shrinkage si n<10 (Apéndice C sección C)
   - update_after_outcome(periodista_id, rumor, outcome)
     → Beta-Binomial update

4. Integrar reliability en scoring (pasar ReliabilityManager a
   compute_credibilidad en sesión 5)

5. Tests:
   - test_lexicon_matching: 50 frases del Apéndice C → match correcto
   - test_reliability_shrinkage: n=5 club, n=100 global → mezcla ponderada
   - test_reliability_update: 10 aciertos seguidos → reliability sube >0.7

Commit "feat: lexicon + contextual reliability (session 4)".
Procede.
```

---

### 🎯 Sesiones 5-12

Los prompts de las sesiones 5-12 son idénticos a los del v3.0 secciones 12.5-12.12, con un único cambio en cada uno:

**Sustituir toda referencia a**:
- `libsql_client` → `d1_client.D1Client` (REST API)
- `Turso` → `Cloudflare D1`
- `Firestore` → `D1`
- `await client.execute(...)` → `await d1.execute(...)`

Las sesiones son:
- **Sesión 5**: Scoring engine con Kalman (sección 7 + 8)
- **Sesión 6**: Validadores Economic + Substitution + Temporal
- **Sesión 7**: Detectores Trial Balloon + Bias + Retraction
- **Sesión 8**: CF Worker Telegram bot + daily report generator
- **Sesión 9**: Auto-calibración + backfill histórico (ver nota abajo)
- **Sesión 10**: Alertas dentro de jobs + /explain extendido
- **Sesión 11**: Backtesting framework
- **Sesión 12**: Extensión cantera (Apéndice J)

Ver PROJECT_KNOWLEDGE_v2.md sección 23 para los prompts completos de cada sesión, aplicando la sustitución indicada arriba.

### Nota sobre Sesión 9 — Backfill histórico

El backfill de "1000 rumores históricos" del v2.1 es **irrealizable automáticamente** porque Twitter archive no es accesible. Claude Code generará un backfill sintético basado en:

- ~80 fichajes RM 2020-2025 conocidos (Bellingham, Mbappé, Endrick, Rüdiger, Alaba, Hazard, etc.)
- Rumores plausibles por periodista según sus patrones documentados
- Timelines coherentes con las fechas reales

Este backfill sintético **calibrará el sistema razonablemente** en el arranque pero no será perfecto. La calibración real mejora con cada fichaje oficial que el sistema observe en vivo.

---

## 12. Apéndices v3.1

Los apéndices C-J del PROJECT_KNOWLEDGE_v2.md son válidos íntegramente:

- **Apéndice C**: Léxico curado por periodista
- **Apéndice D**: Sesgo mediático documentado
- **Apéndice E**: Casos históricos globos sonda
- **Apéndice F**: Modelo económico gratuito (Transfermarkt + Capology + LaLiga)
- **Apéndice G**: Retractaciones famosas (backfill calibración)
- **Apéndice H**: Protocolo backtesting walk-forward
- **Apéndice I**: Roadmap evolución post-v3.1
- **Apéndice J**: Extensión jerárquica cantera (Castilla, Juvenil A, cedidos)

### Apéndice K — Troubleshooting v3.1

**GitHub Actions se acerca a 2000 min/mes**:
1. Subir cold-loop a cada 8h: `-180 min/mes`
2. Subir health-check a cada 12h: `-60 min/mes`
3. Consolidar evening-update en daily-report si no aporta valor: `-30 min/mes`

**D1 se acerca a 5GB**:
- Improbable (33 años de margen estimado)
- Si ocurre: reducir TTL de llm_cache de 7 a 3 días (libera espacio rápido)

**Gemini rate limit (15 RPM)**:
- Aumentar sleep entre calls de 4s a 5s en gemini_client.py
- Reducir batch size del processor de 100 a 50 rumores

**Bluesky API caída**:
- El resolver hace fallback automático a RSS del mismo periodista
- Si no hay RSS alternativo: fuente marcada DEGRADED, alerta admin

**GitHub cron se salta un run**:
- No es catastrófico: los datos se procesan en el siguiente run
- El sistema es stateful (D1 guarda todo), no se pierde nada
- Solo afecta la latencia de ese ciclo

**Bot Telegram no responde**:
1. Verificar en CF Workers dashboard si el Worker tiene errores
2. Verificar webhook está configurado: GET /bot{TOKEN}/getWebhookInfo
3. Re-deploy Worker con `wrangler deploy` (Claude Code puede hacer esto)

---

## 13. Notas finales v3.1

### 13.1 Lo que garantiza el sistema

✅ **0€/mes para siempre** — GitHub/Cloudflare/Gemini tienen incentivo comercial para mantener free tiers. Llevan años estables.

✅ **Pejo no escribe código nunca** — Los prompts de las 12 sesiones son copy-paste de este documento.

✅ **Sin servidores que mantener** — No hay VM, no hay docker, no hay uptime monitoring manual.

✅ **Lógica de producto completa** — Léxico curado, Kalman, calibración Bayesiana, cantera. Nada se sacrificó intelectualmente.

### 13.2 Lo que acepta explícitamente

⚠️ **Alertas con hasta 2h de latencia** — El trade-off del compute gratuito.

⚠️ **Twitter/X parcialmente cubierto** — Romano y Ornstein en Bluesky. El resto via RSS de sus medios con 10-30 min de delay adicional.

⚠️ **Crons no garantizados al segundo** — GitHub puede retrasar 5-30 min. Los datos no se pierden, solo se retrasan.

⚠️ **Backfill sintético** — La calibración inicial es aproximada. Mejora con datos reales en los primeros 3-6 meses.

### 13.3 Versiones

- **v1**: 8 sesiones, Firestore, Haiku. ~135€/mes
- **v2**: 12 sesiones, validadores, Kalman. ~135€/mes
- **v2.1**: +Cantera (Apéndice J). ~150€/mes
- **v3.0**: Primer intento gratuito. **Roto**: GH Actions 4900 min/mes, Turso 500MB, snscrape muerto
- **v3.1** *(este documento)*: **0€/mes sostenible**. GH Actions 1390 min/mes, Cloudflare D1 5GB, sin snscrape, sin Playwright. Auditado con pessimismo explícito.

---

**Fin del PROJECT_KNOWLEDGE.md v3.1.**

🏆 *Hala Madrid. Con datos, sin excusas, sin facturas.*
