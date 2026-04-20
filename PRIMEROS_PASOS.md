# PRIMEROS_PASOS.md — Guía completa para Pejo

> Este archivo + PROJECT_KNOWLEDGE_v3.1.md son los únicos dos archivos
> que necesitas. Claude Code hace el resto.

---

## PASO 1 — Conseguir las API keys (40 min)

### 1.1 Cloudflare (3 valores)

**Qué es**: donde vive la base de datos del sistema (D1) y el bot de Telegram.
**Coste**: gratis, sin tarjeta de crédito.

1. Ve a https://cloudflare.com → Sign Up
2. Verifica el email
3. En el dashboard, en la barra lateral izquierda busca **Workers & Pages**
4. Haz clic en **D1** → **Create database**
   - Name: `fichajes-bot`
   - Location: Europe (elige la más cercana)
   - Haz clic en Create
   - ⚠️ Apunta el **Database ID** (algo como `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
5. Para el Account ID: míralo en la URL cuando estás en el dashboard
   (`dash.cloudflare.com/TU_ACCOUNT_ID/...`) o en el sidebar bajo tu nombre
   - ⚠️ Apunta el **Account ID**
6. Para el API Token:
   - Clic en tu icono de usuario (arriba derecha) → **My Profile**
   - Pestaña **API Tokens** → **Create Token**
   - Elige la plantilla **Edit Cloudflare Workers**
   - Haz clic en **Continue to summary** → **Create Token**
   - ⚠️ Apunta el **API Token** (solo se muestra una vez)

**Resultado: 3 valores anotados**
```
CLOUDFLARE_ACCOUNT_ID    = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CLOUDFLARE_D1_DATABASE_ID = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
CLOUDFLARE_API_TOKEN     = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

### 1.2 Google AI Studio — Gemini (1 valor)

**Qué es**: el LLM gratuito que extrae información de rumores ambiguos.
**Coste**: gratis (1500 requests/día).

1. Ve a https://aistudio.google.com
2. Haz login con tu cuenta de Google
3. Haz clic en **Get API key** (arriba izquierda)
4. Haz clic en **Create API key in new project**
5. ⚠️ Apunta la **API Key** (empieza por `AIza...`)

**Resultado: 1 valor anotado**
```
GEMINI_API_KEY = AIzaXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

---

### 1.3 Telegram — Bot (2 valores)

**Qué es**: el canal por el que recibes las alertas y el resumen diario.
**Coste**: gratis siempre.

**Crear el bot:**
1. Abre Telegram en tu móvil o escritorio
2. Busca `@BotFather` y abre la conversación
3. Envía el mensaje: `/newbot`
4. Te pedirá un nombre visible: escribe `Fichajes Bot`
5. Te pedirá un username único (debe terminar en `bot`): escribe algo como
   `fichajes_rm_pejo_bot` o cualquier username libre
6. BotFather te responderá con un mensaje que contiene `HTTP API token: XXXXXXX:YYYYY`
   - ⚠️ Apunta ese **Bot Token** completo

**Conseguir tu Chat ID:**
1. Abre el bot que acabas de crear en Telegram y envíale el mensaje `/start`
2. Abre esta URL en tu navegador (sustituyendo TU_TOKEN):
   ```
   https://api.telegram.org/botTU_TOKEN/getUpdates
   ```
   Ejemplo real:
   ```
   https://api.telegram.org/bot123456789:AABBccddEEff/getUpdates
   ```
3. Verás un JSON. Busca la parte que dice `"chat":{"id":` — el número que viene
   después es tu Chat ID
   ```json
   "chat":{"id":123456789,"first_name":"Pejo",...}
   ```
   - ⚠️ Apunta ese **Chat ID** (solo el número, sin comillas)

**Si el JSON está vacío** (`{"ok":true,"result":[]}`): vuelve a Telegram,
envía otro mensaje al bot y recarga la URL.

**Resultado: 2 valores anotados**
```
TELEGRAM_BOT_TOKEN = 123456789:AABBccddEEffGGhhIIjjKKll
TELEGRAM_CHAT_ID   = 123456789
```

---

### 1.4 Bluesky — Bot account (2 valores)

**Qué es**: la cuenta con la que el sistema lee posts de periodistas en Bluesky
(Romano, Ornstein, etc.).
**Coste**: gratis.

1. Ve a https://bsky.app → **Create account**
2. Elige un handle para el bot, como `fichajes-rm.bsky.social`
   (no tiene que ser bonito, nadie lo verá)
3. Completa el registro
4. Una vez dentro: haz clic en **Settings** (ajustes)
5. Ve a **Privacy and Security** → **App Passwords**
6. Haz clic en **Add App Password**
7. Nombre: `github-actions`
8. Haz clic en **Create App Password**
   - ⚠️ Apunta el **App Password** generado (algo como `xxxx-xxxx-xxxx-xxxx`)

**Resultado: 2 valores anotados**
```
BLUESKY_HANDLE       = fichajes-rm.bsky.social
BLUESKY_APP_PASSWORD = xxxx-xxxx-xxxx-xxxx
```

---

### 1.5 GitHub — Repositorio (sin key)

**Qué es**: donde vive el código y donde corren los cron jobs gratis.
**Coste**: gratis (plan free con repos privados).

1. Ve a https://github.com → Sign up (si no tienes cuenta)
2. Haz clic en **New repository** (el botón verde)
3. Repository name: `fichajes-bot`
4. Visibility: **Private** (importante)
5. NO marques ninguna opción de inicialización (sin README, sin .gitignore)
6. Haz clic en **Create repository**

Anota la URL del repo:
```
https://github.com/TU_USUARIO/fichajes-bot
```

---

## PASO 2 — Añadir los 8 secrets a GitHub (10 min)

1. Ve a tu repo en GitHub: `https://github.com/TU_USUARIO/fichajes-bot`
2. Haz clic en **Settings** (pestaña arriba)
3. En el menú izquierdo: **Secrets and variables** → **Actions**
4. Haz clic en **New repository secret**
5. Añade estos 8 secrets uno a uno:

| Name | Value |
|------|-------|
| `CLOUDFLARE_ACCOUNT_ID` | el que anotaste en paso 1.1 |
| `CLOUDFLARE_D1_DATABASE_ID` | el que anotaste en paso 1.1 |
| `CLOUDFLARE_API_TOKEN` | el que anotaste en paso 1.1 |
| `GEMINI_API_KEY` | el que anotaste en paso 1.2 |
| `TELEGRAM_BOT_TOKEN` | el que anotaste en paso 1.3 |
| `TELEGRAM_CHAT_ID` | el que anotaste en paso 1.3 |
| `BLUESKY_HANDLE` | el que anotaste en paso 1.4 |
| `BLUESKY_APP_PASSWORD` | el que anotaste en paso 1.4 |

Para cada secret: escribe el Name, pega el Value, clic en **Add secret**.

---

## PASO 3 — Preparar la carpeta para Claude Code (5 min)

1. Crea una carpeta en tu ordenador: `fichajes-bot/`
2. Dentro de esa carpeta pon **estos dos archivos** que ya tienes descargados:
   ```
   fichajes-bot/
   ├── PROJECT_KNOWLEDGE_v3.1.md
   └── PRIMEROS_PASOS.md          ← este archivo
   ```
3. Abre una terminal en esa carpeta:
   - **Mac/Linux**: Terminal → `cd ~/Downloads/fichajes-bot` (o donde la pusiste)
   - **Windows**: PowerShell → `cd C:\Users\TuNombre\Downloads\fichajes-bot`

---

## PASO 4 — Iniciar Claude Code y ejecutar las sesiones

**Instalar Claude Code** (si no lo tienes):
```bash
npm install -g @anthropic-ai/claude-code
```

**Iniciar Claude Code en la carpeta del proyecto:**
```bash
cd fichajes-bot
claude
```

Claude Code arrancará y verá los dos archivos que tienes en la carpeta.

**Ejecutar las sesiones:**

Dentro de Claude Code, copia y pega el prompt de la **Sesión 1** que está
en la sección 11 del archivo `PROJECT_KNOWLEDGE_v3.1.md`. Claude Code leerá
el documento, implementará todo el código, y hará commit al repo de GitHub.

Cuando diga que ha terminado, pega el prompt de la **Sesión 2**, y así
sucesivamente hasta la **Sesión 12**.

**Importante**: no tienes que hacer nada entre sesiones excepto esperar a que
Claude Code diga que ha terminado. No escribas código, no hagas commits
manuales, no toques archivos.

---

## PASO 5 — Verificación final (5 min)

Al día siguiente a las 08:00 (hora española), deberías recibir el primer
mensaje de resumen en Telegram.

Para comprobarlo antes:
1. Ve a tu repo en GitHub → pestaña **Actions**
2. Verás los workflows corriendo (hot-loop, etc.)
3. Si hay errores, hay un workflow `verify-setup.yml` que puedes lanzar
   manualmente y te dice qué falla

También puedes probar el bot directamente:
- Envíale `/top` en Telegram → debería responder con una lista
- Si responde: todo funciona ✅
- Si no responde: algo falló en el deploy del Worker

---

## RESUMEN — Los 8 secrets que necesitas

```
CLOUDFLARE_ACCOUNT_ID       → de cloudflare.com dashboard
CLOUDFLARE_D1_DATABASE_ID   → de cloudflare.com D1 section
CLOUDFLARE_API_TOKEN        → de cloudflare.com API Tokens
GEMINI_API_KEY              → de aistudio.google.com
TELEGRAM_BOT_TOKEN          → de @BotFather en Telegram
TELEGRAM_CHAT_ID            → de api.telegram.org/bot.../getUpdates
BLUESKY_HANDLE              → tu-bot.bsky.social
BLUESKY_APP_PASSWORD        → de bsky.app Settings → App Passwords
```

---

## Si algo falla

**Cloudflare D1 database not found**: verifica que el Database ID es correcto
y que creaste la base de datos llamada `fichajes-bot`.

**Telegram bot no responde**: verifica que enviaste `/start` al bot antes de
hacer getUpdates. Si el Chat ID es correcto y sigue sin responder, el Worker
de Cloudflare puede no estar desplegado — Claude Code incluye un comando de
deploy que puedes relanzar.

**Gemini API quota exceeded**: raro en las primeras semanas. Si ocurre, el
sistema cae automáticamente a extracción solo-regex sin errores críticos.

**GitHub Actions fallan al inicio**: normal. La Sesión 1 de Claude Code
configura las migrations de la base de datos. Algunos workflows necesitan que
la base de datos esté inicializada antes de correr. Claude Code se encarga de
esto en el orden correcto.

---

*Cualquier duda: pregúntale directamente a Claude Code dentro de la sesión.
Tiene el contexto completo del proyecto en PROJECT_KNOWLEDGE_v3.1.md.*
