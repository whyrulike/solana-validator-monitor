"""Version monitor: detects software version changes via getVersion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine, Optional

from src.models.events import BaseEvent, ValidatorVersionChangeEvent
from src.solana_client import SolanaClient

logger = logging.getLogger(__name__)

EventCallback = Callable[[BaseEvent], Coroutine]


class VersionMonitor:
    """Polls getVersion and fires an event when the version changes."""

    def __init__(
        self,
        client: SolanaClient,
        on_event: EventCallback,
        component: str = "jito-solana",
    ) -> None:
        self._client = client
        self._on_event = on_event
        self._component = component
        self._last_version: Optional[str] = None

    async def check(self) -> None:
        """One round of version checking."""
        try:
            data = await self._client.get_version()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get version: %s", exc)
            return

        # Solana RPC returns {"solana-core": "x.y.z", "feature-set": N}
        version = data.get("solana-core") or data.get("version") or ""
        if not version:
            return

        if self._last_version is None:
            logger.info("Initial version recorded: %s", version)
            self._last_version = version
            return

        if version != self._last_version:
            logger.info(
                "Version changed: %s -> %s", self._last_version, version
            )
            event = ValidatorVersionChangeEvent(
                old_version=self._last_version,
                new_version=version,
                component=self._component,
                timestamp=datetime.now(tz=timezone.utc),
            )
            self._last_version = version
            await self._on_event(event)
