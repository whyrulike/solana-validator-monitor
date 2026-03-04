"""Slack Incoming Webhook sender with Block Kit formatting, retry, rate limiting and dedup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

import aiohttp

from src.models.events import BaseEvent

logger = logging.getLogger(__name__)


class SlackWebhook:
    """Send Slack messages via Incoming Webhook with retry, rate limiting and deduplication."""

    def __init__(
        self,
        webhook_url: str,
        rate_limit_per_minute: int = 30,
        dedup_cooldown_seconds: int = 300,
        max_retries: int = 3,
    ) -> None:
        self._webhook_url = webhook_url
        self._rate_limit = rate_limit_per_minute
        self._dedup_cooldown = dedup_cooldown_seconds
        self._max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None

        # Sliding window of send timestamps for rate limiting
        self._send_times: Deque[float] = deque()
        # Dedup cache: event_key -> last_sent_timestamp
        self._dedup_cache: Dict[str, float] = {}

    async def __aenter__(self) -> "SlackWebhook":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _dedup_key(self, event: BaseEvent) -> str:
        """Return a stable string key for deduplication."""
        payload = json.dumps(
            {"event": event.event, "data": event.model_dump(exclude={"timestamp"})},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _is_duplicate(self, key: str) -> bool:
        last = self._dedup_cache.get(key)
        if last is None:
            return False
        return (time.monotonic() - last) < self._dedup_cooldown

    def _record_send(self, key: str) -> None:
        now = time.monotonic()
        self._send_times.append(now)
        self._dedup_cache[key] = now

    async def _wait_for_rate_limit(self) -> None:
        """Block until we are within the allowed rate limit."""
        window = 60.0
        while True:
            now = time.monotonic()
            # Remove timestamps older than the window
            while self._send_times and now - self._send_times[0] >= window:
                self._send_times.popleft()
            if len(self._send_times) < self._rate_limit:
                break
            wait_time = window - (now - self._send_times[0]) + 0.05
            logger.debug("Rate limit reached; waiting %.2fs", wait_time)
            await asyncio.sleep(wait_time)

    async def send_event(self, event: BaseEvent) -> bool:
        """Format and send an event to Slack. Returns True on success."""
        key = self._dedup_key(event)
        if self._is_duplicate(key):
            logger.debug("Duplicate event suppressed: %s", event.event)
            return False

        message = event.to_slack_message()
        return await self.send_message(message, dedup_key=key)

    async def send_message(
        self, payload: Dict[str, Any], dedup_key: Optional[str] = None
    ) -> bool:
        """Send an arbitrary Block Kit payload to Slack. Returns True on success."""
        await self._wait_for_rate_limit()

        assert self._session is not None, "Call open() before sending messages"

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                async with self._session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", "1"))
                        logger.warning("Slack rate limited; retrying after %.1fs", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    resp.raise_for_status()
                    if dedup_key:
                        self._record_send(dedup_key)
                    logger.debug("Slack message sent successfully")
                    return True
            except aiohttp.ClientResponseError as exc:
                last_exc = exc
                if exc.status and 400 <= exc.status < 500 and exc.status != 429:
                    logger.error("Slack rejected message (status %d): %s", exc.status, exc)
                    return False
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Slack send attempt %d/%d failed: %s",
                    attempt + 1,
                    self._max_retries,
                    exc,
                )

            # Exponential backoff
            if attempt < self._max_retries - 1:
                backoff = 2**attempt
                logger.debug("Retrying in %ds…", backoff)
                await asyncio.sleep(backoff)

        logger.error("Failed to send Slack message after %d retries", self._max_retries)
        if last_exc:
            raise last_exc
        return False
