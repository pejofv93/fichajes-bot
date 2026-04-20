"""Aho-Corasick lexicon matcher loaded from D1 lexicon_entries table.

One instance per pipeline run. Loads entries from DB once, caches in memory.
Falls back to linear scan if pyahocorasick is not installed.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger


class LexiconMatcher:
    """Load lexicon from DB and match against text."""

    def __init__(self) -> None:
        self._automaton: Any = None
        self._entries_by_frase: dict[str, dict] = {}
        self._loaded = False

    def load_from_list(self, entries: list[dict]) -> None:
        """Load from a list of dicts (e.g. from DB rows)."""
        self._entries_by_frase = {}
        try:
            import ahocorasick  # type: ignore[import]
            A = ahocorasick.Automaton()
            for e in entries:
                frase = e.get("frase", "").lower()
                if frase:
                    A.add_word(frase, e)
                    self._entries_by_frase[frase] = e
            A.make_automaton()
            self._automaton = A
            logger.debug(f"LexiconMatcher: Aho-Corasick loaded {len(entries)} entries")
        except ImportError:
            logger.debug("LexiconMatcher: pyahocorasick not available, using linear scan")
            self._automaton = None
            for e in entries:
                frase = e.get("frase", "").lower()
                if frase:
                    self._entries_by_frase[frase] = e
        self._loaded = True

    def match(self, text: str, idioma: str = "es") -> list[dict]:
        """Return all lexicon entries found in *text* for *idioma*."""
        if not self._loaded or not self._entries_by_frase:
            return []

        lang2 = idioma[:2].lower() if idioma else "es"
        text_lower = text.lower()
        matches: list[dict] = []
        seen_frases: set[str] = set()

        if self._automaton is not None:
            for _, entry in self._automaton.iter(text_lower):
                frase = entry.get("frase", "").lower()
                entry_lang = (entry.get("idioma") or "")[:2].lower()
                if entry_lang in (lang2, "") and frase not in seen_frases:
                    matches.append(entry)
                    seen_frases.add(frase)
        else:
            for frase, entry in self._entries_by_frase.items():
                if frase in text_lower:
                    entry_lang = (entry.get("idioma") or "")[:2].lower()
                    if entry_lang in (lang2, "") and frase not in seen_frases:
                        matches.append(entry)
                        seen_frases.add(frase)

        return matches

    def compute_weight(self, matches: list[dict]) -> float:
        """Aggregate weight from matched entries.

        Strategy: take the MAX peso_base (best signal), then boost for
        multiple independent signals, capped at 1.0.
        """
        if not matches:
            return 0.0

        # Use learned weight if available, else base weight
        weights = [
            float(m.get("peso_aprendido") or m.get("peso_base") or 0.5)
            for m in matches
        ]
        weights.sort(reverse=True)

        # Primary signal + diminishing returns for corroborating signals
        score = weights[0]
        for w in weights[1:]:
            score = min(1.0, score + w * 0.15)
        return round(score, 4)

    def best_tipo(self, matches: list[dict]) -> Optional[str]:
        """Return the tipo_operacion of the highest-weight match."""
        if not matches:
            return None
        best = max(
            matches,
            key=lambda m: float(m.get("peso_aprendido") or m.get("peso_base") or 0),
        )
        return best.get("tipo_operacion")

    def best_fase(self, matches: list[dict]) -> Optional[int]:
        """Return the highest fase_rumor among matches (most advanced signal)."""
        fases = [m.get("fase_rumor") for m in matches if m.get("fase_rumor")]
        return max(fases) if fases else None


from typing import Optional  # noqa: E402
