"""Slot monitor: detects missed leader slots via getBlockProduction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict, List, Optional

from src.models.events import BaseEvent, ValidatorSlotMissedEvent
from src.solana_client import SolanaClient

logger = logging.getLogger(__name__)

EventCallback = Callable[[BaseEvent], Coroutine]


class SlotMonitor:
    """Polls getBlockProduction and fires events for missed leader slots."""

    def __init__(
        self,
        client: SolanaClient,
        validator_identities: List[str],
        on_event: EventCallback,
        slot_miss_threshold: int = 5,
    ) -> None:
        self._client = client
        self._identities = set(validator_identities)
        self._on_event = on_event
        self._threshold = slot_miss_threshold
        # Track the last seen leader-slot counts per identity to avoid re-alerting
        self._last_blocks_produced: Dict[str, int] = {}
        self._last_leader_slots: Dict[str, int] = {}

    async def check(self) -> None:
        """One round of block-production checks."""
        try:
            data = await self._client.get_block_production()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get block production: %s", exc)
            return

        value = data.get("value", {})
        by_identity = value.get("byIdentity", {})

        for identity in self._identities:
            counts = by_identity.get(identity)
            if counts is None:
                continue

            # counts = [leaderSlots, blocksProduced]
            if not isinstance(counts, (list, tuple)) or len(counts) < 2:
                continue

            leader_slots: int = counts[0]
            blocks_produced: int = counts[1]

            prev_leader = self._last_leader_slots.get(identity, leader_slots)
            prev_blocks = self._last_blocks_produced.get(identity, blocks_produced)

            new_leader = leader_slots - prev_leader
            new_blocks = blocks_produced - prev_blocks
            missed = new_leader - new_blocks

            if new_leader > 0 and missed >= self._threshold:
                logger.warning(
                    "Validator %s missed %d/%d slots", identity, missed, new_leader
                )
                # Report for each missed slot; here we emit one summary event
                range_info = value.get("range", {})
                slot = range_info.get("lastSlot", leader_slots)
                event = ValidatorSlotMissedEvent(
                    slot=slot,
                    reason="block_not_produced",
                    timestamp=datetime.now(tz=timezone.utc),
                )
                await self._on_event(event)

            self._last_leader_slots[identity] = leader_slots
            self._last_blocks_produced[identity] = blocks_produced
