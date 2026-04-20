"""Job: update_economic_model — scrape LaLiga + Capology and persist economic model.

Data flow:
  1. LaLiga transparencia → tope_laliga_rm (salary cost-limit for RM)
  2. Capology            → masa_salarial_actual (total squad payroll)
  3. margen              = tope - masa_actual
  4. presupuesto         = margen × max_ratio_salarial (from configs/economic.yaml)
  5. INSERT INTO modelo_economico (activo=1); mark all prior rows activo=0

Runs in cold-loop.yml BEFORE score --full so EconomicValidator reads fresh data.
"""

from __future__ import annotations

import asyncio
import argparse
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from loguru import logger
from selectolax.parser import HTMLParser

from fichajes_bot.persistence.d1_client import D1Client

_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent / "configs"

# Fallback values when scraping fails (last known public data)
_FALLBACK_TOPE_M = 780.0    # €M — RM 2025-26 cost-limit estimate
_FALLBACK_MASA_M = 580.0    # €M — RM approximate squad payroll
_FFP_RATIO_DEFAULT = 0.70   # presupuesto = margen × this

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; fichajes-bot/3.1; "
        "+https://github.com/pejofeve/fichajes-bot)"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}


def _load_config() -> dict:
    try:
        return yaml.safe_load(
            (_CONFIGS_DIR / "economic.yaml").read_text(encoding="utf-8")
        ) or {}
    except Exception:
        return {}


def _parse_millions(text: str) -> float | None:
    """Extract a numeric value (in millions €) from scraped text."""
    clean = text.strip().replace("\xa0", " ").replace(".", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", clean)
    if not m:
        return None
    try:
        val = float(m.group(1))
        # If already > 1000, treat as raw euros → convert to millions
        if val > 10_000:
            val /= 1_000_000
        return val if val > 0 else None
    except ValueError:
        return None


async def _scrape_laliga_tope(http: httpx.AsyncClient) -> float | None:
    """Scrape LaLiga transparencia for RM cost-limit (tope salarial)."""
    url = "https://www.laliga.com/transparencia/limites-coste-plantilla"
    try:
        r = await http.get(url, timeout=25.0)
        r.raise_for_status()
        tree = HTMLParser(r.text)

        for node in tree.css("tr, .club-row, [data-club], .transparencia-row"):
            text = node.text(separator=" ").lower()
            if "real madrid" not in text and "madrid" not in text:
                continue
            numbers = re.findall(r"[\d]{3,}(?:[.,]\d+)*", text)
            for raw in numbers:
                val = _parse_millions(raw)
                if val and 100 < val < 2_000:
                    logger.info(f"LaLiga tope scraped: {val:.0f}M€")
                    return val

        logger.warning("LaLiga tope: RM row not found in page, will use fallback")
    except Exception as exc:
        logger.warning(f"LaLiga tope scrape failed: {exc}")
    return None


async def _scrape_capology_masa(http: httpx.AsyncClient) -> float | None:
    """Scrape Capology for RM total squad payroll."""
    url = "https://www.capology.com/club/real-madrid/salaries"
    try:
        r = await http.get(url, timeout=25.0)
        r.raise_for_status()
        tree = HTMLParser(r.text)

        # Try to find an aggregate total first
        for node in tree.css("tfoot td, .total-row td, .aggregate"):
            val = _parse_millions(node.text().strip())
            if val and 50 < val < 1_500:
                logger.info(f"Capology masa (aggregate): {val:.0f}M€")
                return val

        # Fall back to summing individual salary rows
        salaries: list[float] = []
        for node in tree.css("td.number, td.salary, .player-salary"):
            val = _parse_millions(node.text().strip())
            if val and 0.2 < val < 120:
                salaries.append(val)
        if len(salaries) >= 5:
            total = sum(salaries)
            logger.info(f"Capology masa (summed {len(salaries)} rows): {total:.0f}M€")
            return total

        logger.warning("Capology: no usable salary data found, will use fallback")
    except Exception as exc:
        logger.warning(f"Capology scrape failed: {exc}")
    return None


def _current_season() -> str:
    now = datetime.now(timezone.utc)
    y = now.year
    if now.month >= 7:
        return f"{y}-{str(y + 1)[-2:]}"
    return f"{y - 1}-{str(y)[-2:]}"


async def run(**kwargs) -> None:
    logger.info("update_economic_model: starting")
    config = _load_config()

    ffp_ratio = (
        config.get("ffp", {}).get("max_ratio_salarial")
        or _FFP_RATIO_DEFAULT
    )

    async with httpx.AsyncClient(
        headers=_HEADERS,
        follow_redirects=True,
        timeout=30.0,
    ) as http:
        tope_scraped = await _scrape_laliga_tope(http)
        masa_scraped = await _scrape_capology_masa(http)

    tope_m = tope_scraped or _FALLBACK_TOPE_M
    masa_m = masa_scraped or _FALLBACK_MASA_M

    scraped_both = tope_scraped is not None and masa_scraped is not None
    fuente     = "laliga+capology" if scraped_both else "fallback"
    confianza  = 0.85 if scraped_both else (0.60 if tope_scraped or masa_scraped else 0.30)

    margen_m     = max(0.0, tope_m - masa_m)
    presupuesto_m = margen_m * ffp_ratio

    temporada = _current_season()
    econ_id   = str(uuid.uuid4())

    async with D1Client() as db:
        await db.execute("UPDATE modelo_economico SET activo = 0")

        await db.execute(
            """INSERT INTO modelo_economico
               (econ_id, temporada, tope_laliga_rm, masa_salarial_actual,
                margen_salarial, presupuesto_fichajes_estimado,
                presupuesto_fichajes_restante, regla_actual,
                politica_edad_max, activo, fecha_actualizacion, fuente, confianza)
               VALUES (?,?,?,?,?,?,?,?,?,1,datetime('now'),?,?)""",
            [
                econ_id,
                temporada,
                round(tope_m * 1_000_000),
                round(masa_m * 1_000_000),
                round(margen_m * 1_000_000),
                round(presupuesto_m * 1_000_000),
                round(presupuesto_m * 1_000_000),
                config.get("ffp", {}).get("regla_viabilidad") or "1_to_1",
                int(config.get("politica", {}).get("edad_maxima_fichaje") or 30),
                fuente,
                confianza,
            ],
        )

    logger.info(
        f"update_economic_model: {temporada} | "
        f"tope={tope_m:.0f}M masa={masa_m:.0f}M "
        f"margen={margen_m:.0f}M presupuesto={presupuesto_m:.0f}M "
        f"(fuente={fuente} confianza={confianza:.0%})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Update RM economic model from scraping")
    parser.add_argument("--full", action="store_true", default=False)
    parser.add_argument("--job", default="update_economic_model")
    args = parser.parse_args()
    asyncio.run(run(**vars(args)))


if __name__ == "__main__":
    main()
