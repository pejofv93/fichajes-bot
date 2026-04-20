#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_setup.py -- Verify all external services respond.

Checks:
  1. Cloudflare D1 (query simple)
  2. Gemini Flash (test call)
  3. Bluesky (login check)
  4. Telegram (getMe + send setup message)

Usage:
    python scripts/verify_setup.py
    python scripts/verify_setup.py --skip-telegram-message

Exit code 0 = all OK, 1 = something failed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


async def verify_d1() -> bool:
    print("\n🗄️  Cloudflare D1...")
    required = ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        _fail(f"Missing env vars: {missing}")
        return False

    try:
        from fichajes_bot.persistence.d1_client import D1Client
        client = D1Client()
        rows = await client.execute("SELECT COUNT(*) as n FROM periodistas")
        count = rows[0]["n"] if rows else 0
        _ok(f"D1 accessible | periodistas={count}")

        tables_ok = True
        expected_tables = ["jugadores", "rumores_raw", "lexicon_entries", "flags_sistema"]
        for table in expected_tables:
            try:
                await client.execute(f"SELECT 1 FROM {table} LIMIT 1")
                _ok(f"Table '{table}' exists")
            except Exception as exc:
                _fail(f"Table '{table}' missing: {exc}")
                tables_ok = False

        await client.close()
        return tables_ok
    except Exception as exc:
        _fail(f"D1 connection failed: {exc}")
        return False


async def verify_gemini() -> bool:
    print("\n🤖 Gemini Flash...")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        _fail("GEMINI_API_KEY not set")
        return False

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        # Minimal test — no tokens wasted
        response = model.generate_content("Reply with just the word: OK")
        text = response.text.strip()
        _ok(f"Gemini Flash responding | response='{text[:20]}'")
        return True
    except ImportError:
        _fail("google-generativeai not installed (run: uv pip install --system google-generativeai)")
        return False
    except Exception as exc:
        error_msg = str(exc)
        if "API_KEY_INVALID" in error_msg or "INVALID_ARGUMENT" in error_msg:
            _fail(f"Gemini API key invalid: {error_msg[:100]}")
        elif "quota" in error_msg.lower():
            _fail(f"Gemini quota issue (may be a rate limit, not a config error): {error_msg[:80]}")
        else:
            _fail(f"Gemini error: {error_msg[:100]}")
        return False


async def verify_bluesky() -> bool:
    print("\n🦋 Bluesky...")
    handle = os.environ.get("BLUESKY_HANDLE", "")
    password = os.environ.get("BLUESKY_APP_PASSWORD", "")

    if not handle or not password:
        _fail("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set")
        return False

    try:
        from atproto import AsyncClient
        client = AsyncClient()
        await client.login(handle, password)
        _ok(f"Bluesky login OK | handle={handle}")
        return True
    except ImportError:
        _fail("atproto not installed (run: uv pip install --system atproto)")
        return False
    except Exception as exc:
        _fail(f"Bluesky login failed: {exc}")
        return False


async def verify_telegram(send_message: bool = True) -> bool:
    print("\n📱 Telegram...")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token:
        _fail("TELEGRAM_BOT_TOKEN not set")
        return False

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            # getMe
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            data = r.json()
            if not data.get("ok"):
                _fail(f"Telegram getMe failed: {data}")
                return False
            bot_name = data["result"].get("username", "?")
            _ok(f"Telegram bot OK | @{bot_name}")

            if send_message and chat_id:
                r2 = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "✅ *fichajes-bot v3.1 setup verificado*\n\nEl sistema está operativo. Los crons de GitHub Actions empezarán a correr en el próximo ciclo.\n\n🏆 Hala Madrid.",
                        "parse_mode": "Markdown",
                    },
                )
                msg_data = r2.json()
                if msg_data.get("ok"):
                    _ok(f"Setup message sent to chat_id={chat_id}")
                else:
                    _fail(f"Could not send message: {msg_data}")
                    return False
            elif not chat_id:
                _fail("TELEGRAM_CHAT_ID not set — cannot send test message")
                return False

        return True
    except ImportError:
        _fail("httpx not installed")
        return False
    except Exception as exc:
        _fail(f"Telegram error: {exc}")
        return False


async def main(skip_telegram_msg: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 55)
    print("  fichajes-bot v3.1 — Setup Verification")
    print("=" * 55)

    results = {
        "D1": await verify_d1(),
        "Gemini": await verify_gemini(),
        "Bluesky": await verify_bluesky(),
        "Telegram": await verify_telegram(send_message=not skip_telegram_msg),
    }

    print("\n" + "=" * 55)
    print("  RESULTS")
    print("=" * 55)
    all_ok = True
    for service, ok in results.items():
        status = "✅ OK" if ok else "❌ FAILED"
        print(f"  {service:<12} {status}")
        if not ok:
            all_ok = False

    print("=" * 55)
    if all_ok:
        print("\n🏆 All services verified! Sistema operativo.")
        print("\nNext steps:")
        print("  1. Push this repo to GitHub")
        print("  2. Add the 8 secrets to GitHub repo settings")
        print("  3. Run deploy-worker.yml to deploy the Telegram bot")
        print("  4. Wait for the first hot-loop cron (runs every 2h)")
        return 0
    else:
        print("\n⚠️  Some services failed. Check the messages above.")
        print("   Refer to PRIMEROS_PASOS.md for troubleshooting.")
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-telegram-message", action="store_true")
    args = parser.parse_args()
    code = asyncio.run(main(skip_telegram_msg=args.skip_telegram_message))
    sys.exit(code)
