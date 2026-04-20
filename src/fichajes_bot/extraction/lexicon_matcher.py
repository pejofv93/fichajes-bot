"""Lexicon matcher using Aho-Corasick for fast multi-pattern matching."""

from __future__ import annotations

from typing import Any

from loguru import logger


class LexiconMatcher:
    def __init__(self) -> None:
        self._automaton: Any = None
        self._entries: dict[str, dict] = {}
        self._loaded = False

    def load(self, entries: list[dict]) -> None:
        try:
            import ahocorasick
            A = ahocorasick.Automaton()
            for entry in entries:
                frase = entry["frase"].lower()
                A.add_word(frase, entry)
                self._entries[frase] = entry
            A.make_automaton()
            self._automaton = A
            self._loaded = True
            logger.debug(f"LexiconMatcher loaded {len(entries)} entries")
        except ImportError:
            logger.warning("pyahocorasick not available, falling back to linear scan")
            self._entries = {e["frase"].lower(): e for e in entries}
            self._loaded = True

    def match(self, text: str, idioma: str = "es") -> list[dict]:
        if not self._loaded or not self._entries:
            return []

        text_lower = text.lower()
        matches = []

        if self._automaton:
            for _, entry in self._automaton.iter(text_lower):
                if entry.get("idioma") in (idioma[:2], None, ""):
                    matches.append(entry)
        else:
            for frase, entry in self._entries.items():
                if frase in text_lower:
                    if entry.get("idioma") in (idioma[:2], None, ""):
                        matches.append(entry)

        return matches

    def compute_weight(self, matches: list[dict]) -> float:
        if not matches:
            return 0.0
        total = sum(m.get("peso_base", 0.5) for m in matches)
        return min(1.0, total / max(1, len(matches)))
