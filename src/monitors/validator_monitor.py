"""Validator status monitor: detects delinquent / recovered events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict, Optional

from src.models.events import BaseEvent, ValidatorDelinquentEvent, ValidatorRecoveredEvent
from src.solana_client import SolanaClient

logger = logging.getLogger(__name__)

EventCallback = Callable[[BaseEvent], Coroutine]


class ValidatorMonitor:
    """Polls getVoteAccounts and emits delinquent/recovered events."""

    def __init__(
        self,
        client: SolanaClient,
        validator_identities: list[str],
        on_event: EventCallback,
    ) -> None:
        self._client = client
        self._identities = set(validator_identities)
        self._on_event = on_event
        # Maps identity -> datetime when it became delinquent
        self._delinquent_since: Dict[str, datetime] = {}

    async def check(self) -> None:
        """Perform one round of vote-account checks."""
        try:
            data = await self._client.get_vote_accounts()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get vote accounts: %s", exc)
            return

        current_identities: set[str] = set()
        delinquent_identities: set[str] = set()

        for acct in data.get("current", []):
            identity = acct.get("nodePubkey", "")
            if identity in self._identities:
                current_identities.add(identity)

        for acct in data.get("delinquent", []):
            identity = acct.get("nodePubkey", "")
            if identity in self._identities:
                delinquent_identities.add(identity)
                slots_behind = acct.get("slotsBehind")
                last_vote = acct.get("lastVote")
                await self._handle_delinquent(
                    identity,
                    last_vote_slot=last_vote,
                    slots_behind=slots_behind,
                )

        # Check recoveries: was delinquent, now in current
        for identity in list(self._delinquent_since.keys()):
            if identity in current_identities and identity not in delinquent_identities:
                await self._handle_recovered(identity)

    async def _handle_delinquent(
        self,
        identity: str,
        last_vote_slot: Optional[int],
        slots_behind: Optional[int],
    ) -> None:
        if identity in self._delinquent_since:
            return  # already tracking

        now = datetime.now(tz=timezone.utc)
        self._delinquent_since[identity] = now
        logger.warning("Validator %s is delinquent", identity)
        event = ValidatorDelinquentEvent(
            validator_identity=identity,
            last_vote_slot=last_vote_slot,
            slots_behind=slots_behind,
            timestamp=now,
        )
        await self._on_event(event)

    async def _handle_recovered(self, identity: str) -> None:
        since = self._delinquent_since.pop(identity)
        now = datetime.now(tz=timezone.utc)
        downtime = (now - since).total_seconds()
        logger.info("Validator %s recovered after %.0fs", identity, downtime)
        event = ValidatorRecoveredEvent(
            validator_identity=identity,
            downtime_seconds=downtime,
            timestamp=now,
        )
        await self._on_event(event)
