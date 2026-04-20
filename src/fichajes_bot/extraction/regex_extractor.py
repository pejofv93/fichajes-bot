"""Regex-based transfer information extractor."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger


# Operation type patterns by language
_PATTERNS: dict[str, dict[str, list[str]]] = {
    "es": {
        "FICHAJE": [
            r"fichar[áa]\b", r"acuerdo\s+(?:total|cerrado|alcanzado)",
            r"contrato\s+firmado", r"aquí\s+vamos", r"fichaje\s+(?:confirmado|cerrado)",
            r"(?:llega|llegará)\s+al\s+real\s+madrid",
        ],
        "SALIDA": [
            r"no\s+renovar[áa]\b", r"(?:ha\s+pedido|pide)\s+la\s+salida",
            r"salida\s+(?:confirmada|libre|inminente)",
            r"rescisi[oó]n\s+(?:de\s+contrato|acordada)",
            r"(?:cedido|prestado)\s+al\b",
        ],
        "RENOVACION": [
            r"renovaci[oó]n\s+(?:acordada|confirmada|firmada)",
            r"renueva\s+(?:con|hasta)\b",
            r"nuevo\s+contrato\s+firmado",
        ],
    },
    "en": {
        "FICHAJE": [
            r"here\s+we\s+go", r"done\s+deal", r"agreement\s+(?:reached|found)",
            r"contract\s+signed", r"medical\s+(?:scheduled|tomorrow|done)",
            r"fee\s+agreed", r"(?:joins|to\s+join)\s+real\s+madrid",
        ],
        "SALIDA": [
            r"(?:will\s+)?leave(?:s)?\s+real\s+madrid",
            r"(?:has\s+)?asked\s+to\s+leave",
            r"(?:not|no\s+longer)\s+in\s+(?:the\s+)?plans",
            r"contract\s+not\s+renewed", r"(?:on\s+)?loan\s+(?:to|agreed)",
        ],
        "RENOVACION": [
            r"contract\s+extension", r"new\s+deal\s+signed",
            r"renewal\s+confirmed", r"signs\s+new\s+contract",
        ],
    },
    "it": {
        "FICHAJE": [
            r"accordo\s+(?:trovato|raggiunto)", r"fumata\s+bianca",
            r"affare\s+chiuso", r"contratto\s+firmato", r"visite\s+mediche",
        ],
        "SALIDA": [
            r"non\s+rinnover[àa]\b", r"addio\s+confermato",
            r"lascia\s+il\s+real\s+madrid",
        ],
        "RENOVACION": [r"rinnovo\s+firmato"],
    },
    "de": {
        "FICHAJE": [
            r"einigung\s+erzielt", r"deal\s+perfekt", r"transfer\s+fix",
            r"wechsel\s+perfekt", r"unterschrift", r"medizincheck",
        ],
        "SALIDA": [
            r"verl[äa]sst\s+real\s+madrid", r"abgang\s+fix",
            r"kein\s+neuer\s+vertrag",
        ],
        "RENOVACION": [r"vertrag\s+verl[äa]ngert"],
    },
    "fr": {
        "FICHAJE": [
            r"accord\s+trouv[eé]", r"transfert\s+confirm[eé]",
            r"contrat\s+sign[eé]", r"visite\s+m[eé]dicale",
            r"dossier\s+boucl[eé]",
        ],
        "SALIDA": [r"d[eé]part\s+confirm[eé]", r"ne\s+renouvellera\s+pas"],
        "RENOVACION": [r"prolongation\s+sign[eé]e"],
    },
}

# Confidence signals
_HIGH_CONF = re.compile(
    r"here\s+we\s+go|done\s+deal|fumata\s+bianca|acuerdo\s+total|contrato\s+firmado|contract\s+signed",
    re.IGNORECASE,
)
_MED_CONF = re.compile(
    r"agreement|acordado|visite\s+mediche|medical|einigung|accord\s+trouv",
    re.IGNORECASE,
)


class RegexExtractor:
    def extract(self, text: str, idioma: str = "es") -> dict[str, Any] | None:
        lang = idioma[:2].lower() if idioma else "es"
        patterns = _PATTERNS.get(lang, _PATTERNS["es"])

        for tipo, pat_list in patterns.items():
            for pat in pat_list:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    confianza = 0.9 if _HIGH_CONF.search(text) else (0.7 if _MED_CONF.search(text) else 0.55)
                    return {
                        "tipo_operacion": tipo,
                        "lexico_detectado": m.group(0),
                        "confianza": confianza,
                        "idioma": lang,
                        "texto_fragmento": text[:500],
                    }
        return None
