"""RPC health monitor: checks latency and health of all configured RPC nodes."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Coroutine, List

import aiohttp

from src.models.events import BaseEvent, RpcUnhealthyEvent

logger = logging.getLogger(__name__)

EventCallback = Callable[[BaseEvent], Coroutine]


class RpcMonitor:
    """Performs health checks + latency measurement on a list of RPC endpoints."""

    def __init__(
        self,
        rpc_urls: List[str],
        on_event: EventCallback,
        latency_threshold_ms: int = 2000,
    ) -> None:
        self._urls = rpc_urls
        self._on_event = on_event
        self._threshold_ms = latency_threshold_ms

    def _node_id(self, url: str) -> str:
        """Derive a human-readable node ID from a URL."""
        return url.split("//")[-1].split("/")[0]

    async def check(self) -> None:
        """One round of RPC health checks for all endpoints."""
        for url in self._urls:
            await self._check_url(url)

    async def _check_url(self, url: str) -> None:
        node_id = self._node_id(url)
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
        timeout = aiohttp.ClientTimeout(total=10)
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    latency_ms = (time.monotonic() - start) * 1000.0

                    result = data.get("result", "")
                    if str(result).lower() != "ok":
                        reason = f"unhealthy_response: {result}"
                        await self._emit_unhealthy(node_id, reason, latency_ms)
                        return

                    if latency_ms > self._threshold_ms:
                        await self._emit_unhealthy(node_id, "high_latency", latency_ms)
                        return

                    logger.debug("RPC %s healthy (%.0f ms)", node_id, latency_ms)

        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.warning("RPC %s unreachable: %s", node_id, exc)
            await self._emit_unhealthy(node_id, "unreachable", latency_ms)

    async def _emit_unhealthy(
        self, node_id: str, reason: str, latency_ms: float
    ) -> None:
        event = RpcUnhealthyEvent(
            node_id=node_id,
            reason=reason,
            latency_ms=latency_ms,
            timestamp=datetime.now(tz=timezone.utc),
        )
        await self._on_event(event)
