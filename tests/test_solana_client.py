"""Tests for the async Solana RPC client."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aioresponses import aioresponses

from src.solana_client import SolanaClient, SolanaRPCError


@pytest_asyncio.fixture
async def client():
    c = SolanaClient(
        rpc_urls=["http://rpc-test:8899"],
        timeout_seconds=5,
        max_retries=2,
    )
    await c.open()
    yield c
    await c.close()


class TestSolanaClientInit:
    def test_requires_at_least_one_url(self):
        with pytest.raises(ValueError):
            SolanaClient(rpc_urls=[])

    def test_stores_urls(self):
        c = SolanaClient(rpc_urls=["http://a:8899", "http://b:8899"])
        assert len(c._urls) == 2


class TestGetVoteAccounts:
    @pytest.mark.asyncio
    async def test_returns_current_and_delinquent(self, client):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "current": [{"nodePubkey": "PubA", "lastVote": 100}],
                "delinquent": [],
            },
        }
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_vote_accounts()
        assert len(result["current"]) == 1
        assert result["current"][0]["nodePubkey"] == "PubA"

    @pytest.mark.asyncio
    async def test_rpc_error_is_raised(self, client):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            with pytest.raises(SolanaRPCError):
                await client.get_vote_accounts()


class TestGetBlockProduction:
    @pytest.mark.asyncio
    async def test_returns_by_identity(self, client):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "value": {
                    "byIdentity": {"PubA": [10, 9]},
                    "range": {"firstSlot": 1, "lastSlot": 100},
                }
            },
        }
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_block_production()
        assert "PubA" in result["value"]["byIdentity"]


class TestGetVersion:
    @pytest.mark.asyncio
    async def test_returns_version_dict(self, client):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"solana-core": "1.18.22", "feature-set": 123},
        }
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_version()
        assert result["solana-core"] == "1.18.22"


class TestGetHealth:
    @pytest.mark.asyncio
    async def test_returns_ok(self, client):
        response = {"jsonrpc": "2.0", "id": 1, "result": "ok"}
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_health()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_unhealthy_rpc_error_returns_error_string(self, client):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32005, "message": "Node is behind"},
        }
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_health()
        assert "error" in result.lower()


class TestGetSlot:
    @pytest.mark.asyncio
    async def test_returns_slot_int(self, client):
        response = {"jsonrpc": "2.0", "id": 1, "result": 290500000}
        with aioresponses() as m:
            m.post("http://rpc-test:8899", payload=response)
            result = await client.get_slot()
        assert result == 290500000


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        c = SolanaClient(
            rpc_urls=["http://rpc-test:8899"],
            timeout_seconds=5,
            max_retries=2,
        )
        await c.open()
        try:
            from aiohttp import ClientConnectionError

            with aioresponses() as m:
                m.post("http://rpc-test:8899", exception=ClientConnectionError())
                m.post(
                    "http://rpc-test:8899",
                    payload={"jsonrpc": "2.0", "id": 2, "result": 99},
                )
                result = await c.get_slot()
            assert result == 99
        finally:
            await c.close()
