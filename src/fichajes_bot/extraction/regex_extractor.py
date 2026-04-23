"""Regex-based transfer extractor.

Extracts:
  - tipo_operacion  (FICHAJE / SALIDA / RENOVACION / CESION)
  - jugador_nombre  (best-effort regex, normalised with rapidfuzz later)
  - fase_rumor      (1-6)
  - lexico_detectado (matched phrase)
  - confianza       (0.0-1.0)
  - idioma

Confidence tiers:
  HIGH  ≥ 0.85 — phase-6 phrases ("here we go", "contrato firmado", …)
  MED   ≥ 0.70 — phase 4-5 phrases (medical, fee agreed, acuerdo personal)
  LOW   ≥ 0.55 — phase 2-3 phrases (negociaciones, oferta, contactos)
  WEAK  ≥ 0.40 — phase 1 (interés, sondeo, rumour)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Typed result ──────────────────────────────────────────────────────────────

@dataclass
class RegexResult:
    tipo_operacion: str
    fase_rumor: int
    lexico_detectado: str
    confianza: float
    idioma: str
    texto_fragmento: str
    jugador_nombre: Optional[str] = None
    club_destino: Optional[str] = None
    negation_found: bool = False


# ── Negation patterns (reduce confidence by 0.3) ────────────────────────────

_NEGATION = re.compile(
    r"\b(no\s+hay|descartado|desmiente|fake|falso|totalmente\s+falso"
    r"|not\s+happening|denied|no\s+agreement|deal\s+off|talks\s+collapsed"
    r"|smentito|dementiert|d[eé]menti|kein\s+wechsel)\b",
    re.IGNORECASE,
)

# ── Known Real Madrid target / squad names (partial list for extraction) ─────

_KNOWN_NAMES = [
    # Current squad (2025-26)
    "Mbappé", "Mbappe", "Bellingham", "Vinícius", "Vinicius",
    "Rodrygo", "Valverde", "Modric", "Kroos", "Camavinga",
    "Tchouaméni", "Tchouameni", "Rüdiger", "Rudiger", "Alaba",
    "Carvajal", "Militão", "Militao", "Courtois", "Lunin",
    "Ancelotti", "Endrick",
    # 2024-25 transfer targets mentioned frequently
    "Trent", "Alexander-Arnold", "Huijsen",
    "Mikel Merino", "Merino", "Dani Carvajal",
    "Xabi Alonso", "Alonso", "Haaland", "Salah",
    "De Bruyne", "Kane", "Lewandowski", "Benzema",
    "Yamal", "Pedri", "Gavi",
    "Gyökeres", "Gyokeres", "Isak", "Osimhen",
    "Wirtz", "Florian Wirtz", "Zubimendi",
    "Jonathan David", "Lamine",
    # 2025-26 GN frequent targets
    "Mac Allister", "Yildiz", "Mastantuono", "Rashford",
    "Sandro Tonali", "Tonali", "Nico Paz", "Víctor Muñoz",
]

# Build a regex that captures any known name
_KNOWN_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in sorted(_KNOWN_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Generic name pattern: "FirstName Surname" format
_GENERIC_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÜ][a-záéíóúüñàèìòùâêîôûäëïöü]{2,}"
    r"(?:\s+[A-ZÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÜ][a-záéíóúüñàèìòùâêîôûäëïöü]{2,}){1,2})\b"
)

# ── Patterns: (regex, tipo_operacion, fase, base_confidence) ─────────────────

_LANG_PATTERNS: dict[str, list[tuple[str, str, int, float]]] = {
    "es": [
        # Phase 6 — confirmed
        (r"aquí\s+vamos",                              "FICHAJE",    6, 0.98),
        (r"ya\s+es\s+oficial",                         "FICHAJE",    6, 0.99),
        (r"fichaje\s+(?:confirmado|oficial)",          "FICHAJE",    6, 0.99),
        (r"compra\s+confirmada",                       "FICHAJE",    6, 0.98),
        (r"contrato\s+firmado",                        "FICHAJE",    6, 0.97),
        (r"done\s+deal",                               "FICHAJE",    6, 0.97),
        (r"acuerdo\s+total\s+alcanzado",               "FICHAJE",    6, 0.95),
        (r"presentaci[oó]n\s+(?:oficial|prevista)",    "FICHAJE",    6, 0.96),
        # Phase 5 — imminent
        (r"acuerdo\s+cerrado",                         "FICHAJE",    5, 0.90),
        (r"trato\s+cerrado",                           "FICHAJE",    5, 0.88),
        (r"traspaso\s+acordado",                       "FICHAJE",    5, 0.89),
        (r"(?:pasa|pasar[aá])\s+el\s+m[eé]dico",      "FICHAJE",    5, 0.93),
        (r"revisi[oó]n\s+m[eé]dica",                  "FICHAJE",    5, 0.92),
        (r"viaje\s+para\s+pasar\s+el\s+reconocimiento","FICHAJE",   5, 0.93),
        (r"en\s+Madrid\s+para\s+firmar",               "FICHAJE",    5, 0.95),
        (r"en\s+camino\s+a\s+Madrid",                  "FICHAJE",    5, 0.90),
        (r"clausula\s+(?:de\s+rescisi[oó]n\s+)?activada","FICHAJE", 5, 0.91),
        (r"liberaci[oó]n\s+de\s+cl[aá]usula",         "FICHAJE",    5, 0.90),
        # Phase 4 — personal agreement
        (r"acuerdo\s+personal\s+alcanzado",            "FICHAJE",    4, 0.82),
        (r"acuerdo\s+con\s+el\s+jugador",              "FICHAJE",    4, 0.80),
        (r"transfer\s+fee\s+agreed",                   "FICHAJE",    4, 0.83),
        (r"contraoferta\s+enviada",                    "FICHAJE",    4, 0.70),
        (r"cifra\s+acordada",                          "FICHAJE",    4, 0.78),
        (r"pendiente\s+del\s+acuerdo\s+entre\s+clubes","FICHAJE",   4, 0.75),
        # Phase 3 — negotiations
        (r"negociaciones?\s+avanzadas?",               "FICHAJE",    3, 0.65),
        (r"oferta\s+(?:presentada|formal|oficial)",    "FICHAJE",    3, 0.63),
        (r"propuesta\s+sobre\s+la\s+mesa",             "FICHAJE",    3, 0.60),
        (r"primera\s+oferta\s+rechazada",              "FICHAJE",    3, 0.55),
        (r"el\s+Madrid\s+ha\s+llegado\s+a\s+un\s+acuerdo","FICHAJE",3, 0.68),
        # Phase 2 — contacts
        (r"contactos?\s+directos?",                    "FICHAJE",    2, 0.50),
        (r"(?:el\s+)?(?:Real\s+Madrid|Madrid)\s+(?:quiere|sigue)\s+(?:al?\s+)?",
                                                       "FICHAJE",    2, 0.45),
        (r"sondeo\s+del\s+(?:Real\s+)?Madrid",         "FICHAJE",    2, 0.42),
        # Phase 1 — interest
        (r"inter[eé]s\s+del\s+(?:Real\s+)?Madrid",    "FICHAJE",    1, 0.35),
        (r"en\s+la\s+agenda\s+del\s+Madrid",           "FICHAJE",    1, 0.30),
        # Salida (departure)
        (r"venta\s+cerrada",                           "SALIDA",     6, 0.96),
        (r"no\s+renovar[aá]\b",                        "SALIDA",     3, 0.75),
        (r"(?:ha\s+pedido|pide)\s+la\s+salida",        "SALIDA",     3, 0.72),
        (r"salida\s+(?:confirmada|libre|inminente)",   "SALIDA",     5, 0.87),
        (r"rescisi[oó]n\s+(?:acordada|de\s+contrato)", "SALIDA",    5, 0.90),
        (r"sale\s+libre\s+en\s+(?:junio|enero|verano)","SALIDA",    4, 0.80),
        (r"(?:fuera\s+de|no\s+cuenta\s+para)\s+(?:los\s+)?planes", "SALIDA", 3, 0.68),
        (r"en\s+la\s+lista\s+de\s+ventas",             "SALIDA",     3, 0.65),
        (r"fin\s+de\s+contrato",                       "SALIDA",     4, 0.72),
        # Cesión
        (r"cedido\s+(?:al?|a\s+la?)\s+",              "CESION",     5, 0.85),
        (r"cesi[oó]n\s+confirmada",                    "CESION",     6, 0.95),
        (r"(?:prestado|cedido)\s+por\s+",              "CESION",     5, 0.82),
        # Renovación
        (r"renovaci[oó]n\s+(?:acordada|confirmada|firmada)","RENOVACION",5, 0.88),
        (r"renueva\s+(?:con|hasta)\b",                 "RENOVACION", 4, 0.75),
        (r"nuevo\s+contrato\s+firmado",                "RENOVACION", 6, 0.98),
        (r"extiende\s+su\s+contrato",                  "RENOVACION", 6, 0.93),
    ],

    "en": [
        # Phase 6
        (r"here\s+we\s+go",                            "FICHAJE",    6, 0.98),
        (r"done\s+deal(?:\s+confirmed)?",              "FICHAJE",    6, 0.97),
        (r"contract\s+signed",                         "FICHAJE",    6, 0.98),
        (r"signing\s+confirmed",                       "FICHAJE",    6, 0.99),
        (r"move\s+confirmed",                          "FICHAJE",    6, 0.96),
        # Phase 5
        (r"medical\s+(?:scheduled|tomorrow|done|completed)","FICHAJE",5, 0.93),
        (r"will\s+undergo\s+(?:a\s+)?medical",         "FICHAJE",    5, 0.93),
        (r"on\s+his\s+way\s+to\s+(?:Real\s+)?Madrid", "FICHAJE",    5, 0.92),
        (r"clubs?\s+(?:have|has)\s+reached\s+agreement","FICHAJE",  5, 0.88),
        (r"agreement\s+reached",                       "FICHAJE",    5, 0.87),
        (r"release\s+clause\s+activated",              "FICHAJE",    5, 0.92),
        (r"(?:Real\s+)?Madrid\s+close\s+to\s+signing", "FICHAJE",   4, 0.72),
        # Phase 4
        (r"(?:transfer\s+)?fee\s+agreed",              "FICHAJE",    4, 0.83),
        (r"personal\s+terms\s+agreed",                 "FICHAJE",    4, 0.85),
        (r"verbally\s+agreed",                         "FICHAJE",    4, 0.78),
        (r"bid\s+accepted",                            "FICHAJE",    4, 0.80),
        (r"in\s+advanced?\s+talks",                    "FICHAJE",    3, 0.65),
        (r"exclusive\s+negotiations?",                 "FICHAJE",    4, 0.75),
        # Phase 3
        (r"formal\s+(?:bid|offer)\s+submitted",        "FICHAJE",    3, 0.65),
        (r"(?:Real\s+)?Madrid\s+(?:preparing|submitting)\s+(?:an?\s+)?(?:offer|bid)",
                                                       "FICHAJE",    3, 0.60),
        (r"bid\s+rejected",                            "FICHAJE",    3, 0.55),
        (r"improved\s+offer\s+submitted",              "FICHAJE",    3, 0.62),
        # Phase 2
        (r"(?:Real\s+)?Madrid\s+(?:have|has)\s+made\s+contact","FICHAJE",2, 0.50),
        (r"(?:Real\s+)?Madrid\s+(?:are|is)\s+(?:tracking|monitoring)","FICHAJE",2, 0.42),
        (r"(?:Real\s+)?Madrid\s+(?:want|wants)\s+",   "FICHAJE",    2, 0.45),
        # Phase 1
        (r"(?:Real\s+)?Madrid\s+(?:are|is)\s+interested\s+in","FICHAJE",1, 0.35),
        # ── GN-style interest/rumour headlines (conf < THRESHOLD → Gemini) ───
        # "Real Madrid eye move for Mac Allister"
        (r"(?:Real\s+)?Madrid\s+eye(?:ing)?(?:\s+move)?(?:\s+for)?\b","FICHAJE",2, 0.42),
        # "Real Madrid keen on Yildiz"
        (r"(?:Real\s+)?Madrid\s+keen\s+on\b",         "FICHAJE",    1, 0.38),
        # "Real Madrid sets sights on Osimhen"
        (r"(?:Real\s+)?Madrid\s+set[s]?\s+sights\s+on\b","FICHAJE", 2, 0.42),
        # "Real Madrid plotting / chasing move"
        (r"(?:Real\s+)?Madrid\s+(?:plot(?:ting)?|chasing|pursuing)\s+","FICHAJE",2, 0.40),
        # "Real Madrid targeting / reportedly targeting X"
        (r"(?:Real\s+)?Madrid\s+(?:reportedly\s+)?target(?:ing)?\s+","FICHAJE",1, 0.38),
        # "X linked to/with Real Madrid"  /  "Real Madrid linked with X"
        (r"\blinked?\s+(?:to|with)\s+(?:Real\s+)?Madrid\b","FICHAJE",1, 0.35),
        (r"(?:Real\s+)?Madrid\s+linked?\s+with\b",    "FICHAJE",    1, 0.35),
        # "X on Real Madrid's radar / shortlist"
        (r"\bon\s+(?:Real\s+)?Madrid(?:'s)?\s+(?:radar|shortlist|wishlist)\b","FICHAJE",1, 0.35),
        # "X is (back) on the table for Real Madrid"
        (r"\b(?:back\s+)?on\s+(?:the\s+)?table\s+for\s+(?:Real\s+)?Madrid\b","FICHAJE",2, 0.42),
        # ── GN-style departure hints (another club approaching RM player) ────
        # "Liverpool offered blockbuster deal for Real Madrid star Vinicius"
        (r"\boffer(?:ed)?\s+(?:\w+\s+){0,3}(?:deal|bid)\s+for\s+(?:Real\s+)?Madrid\b","SALIDA",2, 0.40),
        # "Man Utd want(s) Real Madrid player/star/midfielder"
        (r"\b(?:want(?:s)?|eye(?:ing)?)\s+(?:Real\s+)?Madrid(?:'s)?\s+(?:star|player|forward|midfielder|defender|winger|attacker)\b","SALIDA",2, 0.38),
        # "Real Madrid player/star wanted (in the Bundesliga / by Arsenal)"
        (r"(?:Real\s+)?Madrid\s+(?:star|player|man)\s+wanted\b","SALIDA",  2, 0.40),
        # "Man Utd want giant Real Madrid raid" / "raid Real Madrid"
        (r"\b(?:raid|approach(?:ing)?)\s+(?:Real\s+)?Madrid\b","SALIDA",   2, 0.38),
        (r"(?:Real\s+)?Madrid\s+raid\b",                       "SALIDA",   2, 0.38),
        # "Arsenal in talks with Real Madrid star / close circle"
        (r"\btalks?\s+with\s+(?:Real\s+)?Madrid(?:'s)?\s+(?:star|player|forward|midfielder|defender|winger|close)\b","SALIDA",3, 0.55),
        # Departure
        (r"sale\s+agreed",                             "SALIDA",     6, 0.95),
        (r"will\s+not\s+renew",                        "SALIDA",     3, 0.75),
        (r"(?:has\s+)?asked\s+to\s+leave",             "SALIDA",     3, 0.72),
        (r"contract\s+not\s+renewed",                  "SALIDA",     5, 0.88),
        (r"exit\s+agreed",                             "SALIDA",     5, 0.87),
        (r"(?:not\s+)?(?:in|part\s+of)\s+(?:the\s+)?(?:manager|coach|club)\s+plans",
                                                       "SALIDA",     3, 0.65),
        (r"put\s+up\s+for\s+sale",                     "SALIDA",     3, 0.62),
        (r"leaving\s+in\s+the\s+(?:summer|winter|january|june)",
                                                       "SALIDA",     3, 0.65),
        # Loan
        (r"on\s+loan\s+to\b",                          "CESION",     5, 0.88),
        (r"loan\s+(?:move\s+)?agreed",                 "CESION",     5, 0.90),
        # Renewal
        (r"contract\s+extension(?:\s+signed)?",        "RENOVACION", 5, 0.85),
        (r"new\s+deal\s+signed",                       "RENOVACION", 6, 0.95),
        (r"renewal\s+confirmed",                       "RENOVACION", 6, 0.94),
        (r"signs?\s+new\s+contract",                   "RENOVACION", 6, 0.95),
        # sign / joins for direct transfer confirmation
        (r"(?:Real\s+)?Madrid\s+sign(?:s)?\s+\w",      "FICHAJE",    5, 0.82),
        (r"joins?\s+(?:Real\s+)?Madrid\b",             "FICHAJE",    6, 0.88),
        (r"to\s+sign\s+for\s+(?:Real\s+)?Madrid",      "FICHAJE",    5, 0.85),
    ],

    "it": [
        (r"accordo\s+(?:trovato|raggiunto)",           "FICHAJE",    5, 0.90),
        (r"fumata\s+bianca",                           "FICHAJE",    6, 0.96),
        (r"affare\s+chiuso",                           "FICHAJE",    6, 0.95),
        (r"colpo\s+fatto",                             "FICHAJE",    6, 0.96),
        (r"contratto\s+firmato",                       "FICHAJE",    6, 0.98),
        (r"visite\s+mediche",                          "FICHAJE",    5, 0.93),
        (r"offerta\s+accettata",                       "FICHAJE",    4, 0.82),
        (r"trattativa\s+avanzata",                     "FICHAJE",    3, 0.65),
        (r"offerta\s+presentata",                      "FICHAJE",    3, 0.62),
        (r"il\s+(?:Real\s+)?Madrid\s+vuole",           "FICHAJE",    2, 0.42),
        (r"intesa\s+raggiunta",                        "FICHAJE",    5, 0.87),
        (r"non\s+rinnover[àa]",                        "SALIDA",     3, 0.75),
        (r"addio\s+confermato",                        "SALIDA",     6, 0.95),
        (r"lascia\s+il\s+(?:Real\s+)?Madrid",          "SALIDA",     5, 0.85),
        (r"cessione\s+(?:accordata|confermata)",       "CESION",     5, 0.90),
        (r"rinnovo\s+firmato",                         "RENOVACION", 6, 0.96),
        (r"rinnovo\s+(?:accordato|confermato)",        "RENOVACION", 5, 0.87),
    ],

    "de": [
        (r"einigung\s+erzielt",                        "FICHAJE",    5, 0.88),
        (r"deal\s+perfekt",                            "FICHAJE",    6, 0.96),
        (r"wechsel\s+perfekt",                         "FICHAJE",    6, 0.96),
        (r"transfer\s+fix",                            "FICHAJE",    6, 0.96),
        (r"medizincheck",                              "FICHAJE",    5, 0.93),
        (r"unterschrift",                              "FICHAJE",    6, 0.95),
        (r"ablösesumme\s+vereinbart",                  "FICHAJE",    4, 0.82),
        (r"einig\s+geworden",                          "FICHAJE",    5, 0.87),
        (r"angebot\s+eingereicht",                     "FICHAJE",    3, 0.62),
        (r"interesse\s+(?:von|des)\s+(?:Real\s+)?Madrid","FICHAJE", 1, 0.35),
        (r"verl[äa]sst\s+(?:Real\s+)?Madrid",          "SALIDA",    5, 0.85),
        (r"abgang\s+fix",                              "SALIDA",     6, 0.94),
        (r"kein\s+neuer\s+vertrag",                    "SALIDA",     4, 0.75),
        (r"vertrag\s+l[äa]uft\s+aus",                  "SALIDA",    4, 0.72),
        (r"vertrag\s+verl[äa]ngert",                   "RENOVACION",6, 0.95),
    ],

    "fr": [
        (r"accord\s+trouv[eé]",                        "FICHAJE",    5, 0.88),
        (r"accord\s+entre\s+clubs",                    "FICHAJE",    5, 0.87),
        (r"visite\s+m[eé]dicale",                      "FICHAJE",    5, 0.93),
        (r"transfert\s+confirm[eé]",                   "FICHAJE",    6, 0.97),
        (r"contrat\s+sign[eé]",                        "FICHAJE",    6, 0.98),
        (r"dossier\s+boucl[eé]",                       "FICHAJE",    6, 0.95),
        (r"en\s+passe\s+de\s+signer",                  "FICHAJE",    5, 0.88),
        (r"accord\s+personnel",                        "FICHAJE",    4, 0.82),
        (r"offre\s+formul[eé]e",                       "FICHAJE",    3, 0.62),
        (r"le\s+(?:Real\s+)?Madrid\s+veut",            "FICHAJE",    2, 0.42),
        (r"d[eé]part\s+confirm[eé]",                   "SALIDA",     6, 0.95),
        (r"ne\s+renouvellera\s+pas",                   "SALIDA",     3, 0.75),
        (r"pr[eê]t\s+confirm[eé]",                     "CESION",     6, 0.94),
        (r"mis\s+sur\s+le\s+march[eé]",                "SALIDA",     3, 0.62),
        (r"prolongation\s+sign[eé]e",                  "RENOVACION", 6, 0.96),
    ],
}

# Pre-compile all patterns once at import time
_COMPILED: dict[str, list[tuple[re.Pattern, str, int, float]]] = {
    lang: [
        (re.compile(pat, re.IGNORECASE | re.UNICODE), tipo, fase, conf)
        for pat, tipo, fase, conf in pats
    ]
    for lang, pats in _LANG_PATTERNS.items()
}

# Known club names for context detection
_CLUBS = [
    "Real Madrid", "Barcelona", "Manchester City", "Manchester United",
    "Chelsea", "Arsenal", "Liverpool", "Juventus", "Inter", "Milan",
    "PSG", "Paris Saint-Germain", "Bayern", "Dortmund", "Atletico",
    "Atlético de Madrid", "Sevilla", "Valencia", "Betis", "Napoli",
    "Roma", "Lazio", "Porto", "Benfica", "Ajax", "Chelsea",
]
_CLUB_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in sorted(_CLUBS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Names that must never be identified as players (media, brands, phrases)
_NAME_BLACKLIST: frozenset[str] = frozenset({
    # Phrases
    "Real Madrid", "Transfer News", "Breaking News", "Here We Go",
    "Done Deal", "Transfer Talk", "Transfer Window", "Premier League",
    "Champions League", "Europa League", "La Liga", "Serie",
    # Journalists / analysts
    "Fabrizio Romano", "David Ornstein", "Matteo Moretto", "Gianluca Di",
    # Media outlets
    "Sports Illustrated", "Sky Sports", "BBC Sport", "The Athletic",
    "Marca", "Mundo Deportivo", "Cadena Ser", "Relevo", "Kicker",
    "Gazzetta Dello", "France Football", "Daily Mail", "Daily Mirror",
    "Goal", "ESPN", "CBS Sports", "NBC Sports", "Caught Offside",
    "Football Insider", "Football Italia", "Bild", "Der Spiegel",
})


class RegexExtractor:
    """Stateless regex-based extractor. Thread-safe."""

    def extract(self, text: str, idioma: str = "es") -> Optional[RegexResult]:
        """Return best RegexResult or None if no pattern matches."""
        if not text:
            return None

        lang = (idioma or "es")[:2].lower()
        patterns = _COMPILED.get(lang) or _COMPILED["es"]

        # Try language-specific patterns first, then English as cross-language fallback
        result = self._try_patterns(text, patterns, lang)
        if result is None and lang != "en":
            result = self._try_patterns(text, _COMPILED["en"], "en")

        if result is None:
            return None

        # Apply negation penalty
        if _NEGATION.search(text):
            result.confianza = max(0.0, result.confianza - 0.30)
            result.negation_found = True

        # Extract player name
        result.jugador_nombre = self._extract_name(text)
        result.club_destino = self._extract_dest_club(text)
        result.texto_fragmento = text[:500]

        return result

    def _try_patterns(
        self, text: str, patterns: list[tuple[re.Pattern, str, int, float]], lang: str
    ) -> Optional[RegexResult]:
        best: Optional[RegexResult] = None
        for compiled, tipo, fase, base_conf in patterns:
            m = compiled.search(text)
            if m:
                candidate = RegexResult(
                    tipo_operacion=tipo,
                    fase_rumor=fase,
                    lexico_detectado=m.group(0).strip(),
                    confianza=base_conf,
                    idioma=lang,
                    texto_fragmento="",
                )
                if best is None or candidate.confianza > best.confianza:
                    best = candidate
        return best

    def _extract_name(self, text: str) -> Optional[str]:
        # Try known names first (highest precision)
        m = _KNOWN_NAME_RE.search(text)
        if m:
            return m.group(1)
        # Generic Name Surname pattern (lower precision)
        candidates = _GENERIC_NAME_RE.findall(text[:600])
        for c in candidates:
            if c not in _NAME_BLACKLIST and len(c) > 4:
                return c
        return None

    def _extract_dest_club(self, text: str) -> Optional[str]:
        clubs = _CLUB_RE.findall(text)
        for club in clubs:
            if "madrid" not in club.lower():
                return club
        return None


# Allow direct Optional import at module level
from typing import Optional  # noqa: E402
