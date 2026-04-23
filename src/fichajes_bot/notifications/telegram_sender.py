"""Async Telegram sender with 429 retry logic and 1.1s inter-message throttle."""

from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger


class AsyncTelegramSender:
    """Async Telegram message sender.

    Must be used as an async context manager to share the underlying
    httpx.AsyncClient across calls:

        async with AsyncTelegramSender(token, chat_id) as sender:
            ok = await sender.send_message("hello")
    """

    _BASE = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str | int) -> None:
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._client: httpx.AsyncClient | None = None
        self._last_send_time: float = 0.0

    async def __aenter__(self) -> "AsyncTelegramSender":
        self._client = httpx.AsyncClient(base_url=self._BASE, timeout=30.0)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "AsyncTelegramSender must be used as an async context manager."
            )
        return self._client

    async def send_message(
        self, text: str, parse_mode: str = "Markdown"
    ) -> bool:
        """Send a single message. Returns True on success, False on failure.

        On HTTP 429 reads retry_after from the Telegram error body, sleeps
        exactly that many seconds, then retries once. Always sleeps 1.1s
        at the end (before the next call) regardless of outcome.
        """
        client = self._get_client()
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        url = f"/bot{self._token}/sendMessage"

        try:
            r = await client.post(url, json=payload)

            if r.status_code == 429:
                retry_after = 5
                try:
                    body = r.json()
                    retry_after = int(
                        body.get("parameters", {}).get("retry_after", 5)
                    )
                except Exception:
                    pass
                logger.warning(
                    f"Telegram 429 — sleeping {retry_after}s then retrying once"
                )
                await asyncio.sleep(retry_after)

                r = await client.post(url, json=payload)
                if r.status_code == 429:
                    logger.error("Telegram 429 on retry — not retrying further")
                    return False

            if r.status_code == 200:
                return True

            # 400 with parse_mode → markdown entity error; retry as plain text
            if r.status_code == 400 and parse_mode:
                logger.warning(
                    f"Telegram 400 (markdown parse error) — "
                    f"retrying without parse_mode. body={r.text[:200]}"
                )
                plain_payload = {k: v for k, v in payload.items() if k != "parse_mode"}
                r = await client.post(url, json=plain_payload)
                if r.status_code == 200:
                    return True

            logger.error(
                f"Telegram sendMessage failed: status={r.status_code} "
                f"body={r.text[:200]}"
            )
            return False

        except Exception as exc:
            logger.error(f"Telegram sendMessage exception: {exc}")
            return False
        finally:
            await asyncio.sleep(1.1)
            self._last_send_time = time.monotonic()

    async def send_message_splitted(
        self, text: str, max_len: int = 4000
    ) -> list[bool]:
        """Split text into chunks and send each chunk sequentially.

        Returns a list of bool, one per chunk (True = sent OK). The 1.1s
        throttle inside send_message is the only inter-chunk delay needed.
        """
        chunks = split_message(text, max_len)
        results: list[bool] = []
        for chunk in chunks:
            ok = await self.send_message(chunk)
            results.append(ok)
        return results


def split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a Markdown message into chunks that do not exceed max_len.

    Splits on line boundaries. Never breaks inside a fenced code block
    (``` ... ```) because that would produce invalid Markdown.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    in_code_block = False

    for line in text.split("\n"):
        if line.startswith("```"):
            in_code_block = not in_code_block

        line_cost = len(line) + 1  # +1 for the newline we'll re-add

        if not in_code_block and current_len + line_cost > max_len and current_lines:
            chunks.append("\n".join(current_lines).strip())
            current_lines = []
            current_len = 0

        current_lines.append(line)
        current_len += line_cost

    if current_lines:
        tail = "\n".join(current_lines).strip()
        if tail:
            chunks.append(tail)

    return chunks or [text]
