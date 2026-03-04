"""Asynchronous Solana JSON-RPC client with multi-endpoint failover."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_JSONRPC_VERSION = "2.0"


class SolanaRPCError(Exception):
    """Raised when the RPC returns an error response."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message


class SolanaClient:
    """Async Solana JSON-RPC client supporting multiple endpoints with automatic failover."""

    def __init__(
        self,
        rpc_urls: List[str],
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ) -> None:
        if not rpc_urls:
            raise ValueError("At least one RPC URL must be provided")
        self._urls = list(rpc_urls)
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id = 0

    async def __aenter__(self) -> "SolanaClient":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _request(self, method: str, params: Any = None) -> Any:
        """Execute an RPC call with retry and failover across configured endpoints."""
        payload: Dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            url = self._urls[attempt % len(self._urls)]
            try:
                assert self._session is not None, "Call open() before making requests"
                async with self._session.post(url, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    if "error" in data and data["error"] is not None:
                        err = data["error"]
                        raise SolanaRPCError(
                            code=err.get("code", -1),
                            message=err.get("message", "unknown error"),
                        )
                    return data.get("result")
            except SolanaRPCError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "RPC attempt %d/%d to %s failed: %s",
                    attempt + 1,
                    self._max_retries,
                    url,
                    exc,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))

        raise RuntimeError(
            f"All {self._max_retries} RPC attempts failed for method '{method}'"
        ) from last_exc

    # ------------------------------------------------------------------
    # Public RPC methods
    # ------------------------------------------------------------------

    async def get_vote_accounts(self) -> Dict[str, Any]:
        """Return current and delinquent vote accounts."""
        result = await self._request("getVoteAccounts")
        return result or {}

    async def get_block_production(
        self,
        identity: Optional[str] = None,
        first_slot: Optional[int] = None,
        last_slot: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return block production statistics."""
        config: Dict[str, Any] = {}
        if identity:
            config["identity"] = identity
        if first_slot is not None and last_slot is not None:
            config["range"] = {"firstSlot": first_slot, "lastSlot": last_slot}
        params = [config] if config else []
        result = await self._request("getBlockProduction", params)
        return result or {}

    async def get_version(self) -> Dict[str, Any]:
        """Return the node's software version."""
        result = await self._request("getVersion")
        return result or {}

    async def get_health(self) -> str:
        """Return health string ('ok' when healthy)."""
        try:
            result = await self._request("getHealth")
            return str(result) if result is not None else "ok"
        except SolanaRPCError as exc:
            return f"error: {exc.message}"

    async def get_slot(self) -> int:
        """Return the current slot."""
        result = await self._request("getSlot")
        return int(result) if result is not None else 0

    async def measure_latency(self, url: Optional[str] = None) -> float:
        """Measure round-trip latency (ms) for a getSlot call against the given URL."""
        target_url = url or self._urls[0]
        payload: Dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._next_id(),
            "method": "getSlot",
        }
        assert self._session is not None, "Call open() before making requests"
        start = time.monotonic()
        async with self._session.post(target_url, json=payload) as resp:
            resp.raise_for_status()
            await resp.json(content_type=None)
        return (time.monotonic() - start) * 1000.0
