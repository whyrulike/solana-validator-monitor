"""Failover monitor: detects primary-node failures and triggers failover events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict, List, Optional

from src.config import FailoverNodeConfig
from src.models.events import BaseEvent, ValidatorFailoverEvent
from src.solana_client import SolanaClient

logger = logging.getLogger(__name__)

EventCallback = Callable[[BaseEvent], Coroutine]


class FailoverMonitor:
    """Health-checks primary/secondary nodes and fires failover events."""

    def __init__(
        self,
        client: SolanaClient,
        nodes: List[FailoverNodeConfig],
        on_event: EventCallback,
    ) -> None:
        self._base_client = client
        self._nodes = nodes
        self._on_event = on_event
        # Consecutive failure counters per node id
        self._failure_counts: Dict[str, int] = {n.id: 0 for n in nodes}
        self._current_primary: Optional[str] = next(
            (n.id for n in nodes if n.is_primary), None
        )
        self._failover_triggered = False

    async def check(self) -> None:
        """One round of node health checks."""
        for node in self._nodes:
            healthy = await self._check_node(node)
            if healthy:
                self._failure_counts[node.id] = 0
            else:
                self._failure_counts[node.id] += 1
                logger.warning(
                    "Node %s health check failed (%d consecutive)",
                    node.id,
                    self._failure_counts[node.id],
                )

        await self._evaluate_failover()

    async def _check_node(self, node: FailoverNodeConfig) -> bool:
        """Return True if the node is healthy."""
        import aiohttp  # imported here to keep top-level imports clean

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth",
            }
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(node.rpc_url, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    result = data.get("result", "")
                    return str(result).lower() == "ok"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Node %s unreachable: %s", node.id, exc)
            return False

    async def _evaluate_failover(self) -> None:
        """Trigger failover when the current primary has exceeded its failure threshold."""
        if self._current_primary is None:
            return

        primary_node = next(
            (n for n in self._nodes if n.id == self._current_primary), None
        )
        if primary_node is None:
            return

        failures = self._failure_counts.get(self._current_primary, 0)
        threshold = primary_node.health_check_failures_threshold

        if failures >= threshold:
            # Find a healthy secondary
            new_primary = next(
                (
                    n.id
                    for n in self._nodes
                    if n.id != self._current_primary
                    and self._failure_counts.get(n.id, 0) == 0
                ),
                None,
            )
            if new_primary is None:
                logger.error("No healthy secondary found for failover!")
                return

            old_primary = self._current_primary
            self._current_primary = new_primary
            # Leave the old primary's failure count intact so it can only become
            # a failover candidate again after it naturally recovers (count drops
            # to 0 via successful health checks), preventing rapid oscillation.

            logger.critical(
                "Failover triggered: %s -> %s", old_primary, new_primary
            )
            event = ValidatorFailoverEvent(
                old_primary=old_primary,
                new_primary=new_primary,
                trigger="health_check_failed",
                timestamp=datetime.now(tz=timezone.utc),
            )
            await self._on_event(event)
