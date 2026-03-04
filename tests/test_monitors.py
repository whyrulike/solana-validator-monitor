"""Tests for the individual monitor modules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.config import FailoverNodeConfig
from src.models.events import (
    BaseEvent,
    ValidatorDelinquentEvent,
    ValidatorFailoverEvent,
    ValidatorRecoveredEvent,
    ValidatorSlotMissedEvent,
    ValidatorVersionChangeEvent,
)
from src.monitors.failover_monitor import FailoverMonitor
from src.monitors.rpc_monitor import RpcMonitor
from src.monitors.slot_monitor import SlotMonitor
from src.monitors.validator_monitor import ValidatorMonitor
from src.monitors.version_monitor import VersionMonitor
from src.solana_client import SolanaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_client() -> SolanaClient:
    client = MagicMock(spec=SolanaClient)
    client.get_vote_accounts = AsyncMock(
        return_value={"current": [], "delinquent": []}
    )
    client.get_block_production = AsyncMock(
        return_value={"value": {"byIdentity": {}, "range": {}}}
    )
    client.get_version = AsyncMock(return_value={"solana-core": "1.18.22"})
    client.get_health = AsyncMock(return_value="ok")
    client.get_slot = AsyncMock(return_value=100)
    return client


async def collect_events(events: List[BaseEvent], event: BaseEvent) -> None:
    events.append(event)


# ---------------------------------------------------------------------------
# ValidatorMonitor
# ---------------------------------------------------------------------------

class TestValidatorMonitor:
    @pytest.mark.asyncio
    async def test_delinquent_event_fired(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        client.get_vote_accounts = AsyncMock(
            return_value={
                "current": [],
                "delinquent": [
                    {
                        "nodePubkey": "ValidatorPubkey1",
                        "lastVote": 290500000,
                        "slotsBehind": 150,
                    }
                ],
            }
        )
        monitor = ValidatorMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()
        assert len(events) == 1
        assert isinstance(events[0], ValidatorDelinquentEvent)
        assert events[0].validator_identity == "ValidatorPubkey1"
        assert events[0].last_vote_slot == 290500000
        assert events[0].slots_behind == 150

    @pytest.mark.asyncio
    async def test_delinquent_not_fired_twice(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        client.get_vote_accounts = AsyncMock(
            return_value={
                "current": [],
                "delinquent": [{"nodePubkey": "ValidatorPubkey1", "lastVote": 100}],
            }
        )
        monitor = ValidatorMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()
        await monitor.check()
        assert len(events) == 1  # only one delinquent event

    @pytest.mark.asyncio
    async def test_recovered_event_fired(self):
        events: List[BaseEvent] = []
        client = make_mock_client()

        # First call: delinquent
        client.get_vote_accounts = AsyncMock(
            return_value={
                "current": [],
                "delinquent": [{"nodePubkey": "ValidatorPubkey1", "lastVote": 100}],
            }
        )
        monitor = ValidatorMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()
        assert len(events) == 1
        assert isinstance(events[0], ValidatorDelinquentEvent)

        # Second call: recovered
        client.get_vote_accounts = AsyncMock(
            return_value={
                "current": [{"nodePubkey": "ValidatorPubkey1", "lastVote": 200}],
                "delinquent": [],
            }
        )
        await monitor.check()
        assert len(events) == 2
        assert isinstance(events[1], ValidatorRecoveredEvent)
        assert events[1].downtime_seconds >= 0

    @pytest.mark.asyncio
    async def test_ignores_unknown_validators(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        client.get_vote_accounts = AsyncMock(
            return_value={
                "current": [],
                "delinquent": [{"nodePubkey": "SomeOtherValidator", "lastVote": 100}],
            }
        )
        monitor = ValidatorMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_rpc_error_does_not_raise(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        client.get_vote_accounts = AsyncMock(side_effect=RuntimeError("RPC down"))
        monitor = ValidatorMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()  # Should not raise
        assert len(events) == 0


# ---------------------------------------------------------------------------
# SlotMonitor
# ---------------------------------------------------------------------------

class TestSlotMonitor:
    @pytest.mark.asyncio
    async def test_slot_missed_event_fired(self):
        events: List[BaseEvent] = []
        client = make_mock_client()

        # First check: baseline
        client.get_block_production = AsyncMock(
            return_value={
                "value": {
                    "byIdentity": {"ValidatorPubkey1": [10, 9]},
                    "range": {"firstSlot": 1, "lastSlot": 100},
                }
            }
        )
        monitor = SlotMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
            slot_miss_threshold=2,
        )
        await monitor.check()
        assert len(events) == 0  # First call just sets baseline

        # Second check: 5 new slots, only 2 produced -> 3 missed >= threshold 2
        client.get_block_production = AsyncMock(
            return_value={
                "value": {
                    "byIdentity": {"ValidatorPubkey1": [15, 11]},
                    "range": {"firstSlot": 1, "lastSlot": 105},
                }
            }
        )
        await monitor.check()
        assert len(events) == 1
        assert isinstance(events[0], ValidatorSlotMissedEvent)

    @pytest.mark.asyncio
    async def test_no_event_within_threshold(self):
        events: List[BaseEvent] = []
        client = make_mock_client()

        client.get_block_production = AsyncMock(
            return_value={
                "value": {
                    "byIdentity": {"ValidatorPubkey1": [10, 9]},
                    "range": {"firstSlot": 1, "lastSlot": 100},
                }
            }
        )
        monitor = SlotMonitor(
            client=client,
            validator_identities=["ValidatorPubkey1"],
            on_event=lambda e: collect_events(events, e),
            slot_miss_threshold=5,
        )
        await monitor.check()

        # Only 1 missed slot, threshold is 5
        client.get_block_production = AsyncMock(
            return_value={
                "value": {
                    "byIdentity": {"ValidatorPubkey1": [14, 13]},
                    "range": {"firstSlot": 1, "lastSlot": 104},
                }
            }
        )
        await monitor.check()
        assert len(events) == 0


# ---------------------------------------------------------------------------
# VersionMonitor
# ---------------------------------------------------------------------------

class TestVersionMonitor:
    @pytest.mark.asyncio
    async def test_no_event_on_first_check(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        monitor = VersionMonitor(
            client=client,
            on_event=lambda e: collect_events(events, e),
            component="jito-solana",
        )
        await monitor.check()
        assert len(events) == 0
        assert monitor._last_version == "1.18.22"

    @pytest.mark.asyncio
    async def test_version_change_event_fired(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        monitor = VersionMonitor(
            client=client,
            on_event=lambda e: collect_events(events, e),
            component="jito-solana",
        )
        await monitor.check()  # records 1.18.22

        client.get_version = AsyncMock(return_value={"solana-core": "1.18.23"})
        await monitor.check()

        assert len(events) == 1
        assert isinstance(events[0], ValidatorVersionChangeEvent)
        assert events[0].old_version == "1.18.22"
        assert events[0].new_version == "1.18.23"
        assert events[0].component == "jito-solana"

    @pytest.mark.asyncio
    async def test_no_event_when_version_unchanged(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        monitor = VersionMonitor(
            client=client,
            on_event=lambda e: collect_events(events, e),
        )
        await monitor.check()
        await monitor.check()
        assert len(events) == 0


# ---------------------------------------------------------------------------
# RpcMonitor
# ---------------------------------------------------------------------------

class TestRpcMonitor:
    @pytest.mark.asyncio
    async def test_unhealthy_event_on_high_latency(self):
        events: List[BaseEvent] = []

        async def mock_check_url(url: str) -> None:
            from src.models.events import RpcUnhealthyEvent
            evt = RpcUnhealthyEvent(
                node_id="localhost:8899",
                reason="high_latency",
                latency_ms=3000.0,
            )
            await collect_events(events, evt)

        monitor = RpcMonitor(
            rpc_urls=["http://localhost:8899"],
            on_event=lambda e: collect_events(events, e),
            latency_threshold_ms=1000,
        )
        monitor._check_url = mock_check_url
        await monitor.check()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_unhealthy_event_on_connection_error(self):
        events: List[BaseEvent] = []
        from aioresponses import aioresponses
        from aiohttp import ClientConnectionError

        monitor = RpcMonitor(
            rpc_urls=["http://rpc-unreachable:8899"],
            on_event=lambda e: collect_events(events, e),
            latency_threshold_ms=1000,
        )
        with aioresponses() as m:
            m.post(
                "http://rpc-unreachable:8899",
                exception=ClientConnectionError("connection refused"),
            )
            await monitor.check()
        assert len(events) == 1
        assert events[0].reason == "unreachable"


# ---------------------------------------------------------------------------
# FailoverMonitor
# ---------------------------------------------------------------------------

class TestFailoverMonitor:
    @pytest.mark.asyncio
    async def test_failover_event_after_threshold(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        nodes = [
            FailoverNodeConfig(
                id="primary",
                rpc_url="http://primary:8899",
                is_primary=True,
                health_check_failures_threshold=2,
            ),
            FailoverNodeConfig(
                id="secondary",
                rpc_url="http://secondary:8899",
                is_primary=False,
                health_check_failures_threshold=2,
            ),
        ]
        monitor = FailoverMonitor(
            client=client,
            nodes=nodes,
            on_event=lambda e: collect_events(events, e),
        )

        # Make primary fail and secondary healthy
        async def mock_check_node(node: FailoverNodeConfig) -> bool:
            return node.id != "primary"

        monitor._check_node = mock_check_node

        await monitor.check()  # 1 failure
        assert len(events) == 0

        await monitor.check()  # 2 failures -> threshold reached
        assert len(events) == 1
        assert isinstance(events[0], ValidatorFailoverEvent)
        assert events[0].old_primary == "primary"
        assert events[0].new_primary == "secondary"

    @pytest.mark.asyncio
    async def test_no_failover_when_primary_healthy(self):
        events: List[BaseEvent] = []
        client = make_mock_client()
        nodes = [
            FailoverNodeConfig(
                id="primary",
                rpc_url="http://primary:8899",
                is_primary=True,
                health_check_failures_threshold=3,
            ),
        ]
        monitor = FailoverMonitor(
            client=client,
            nodes=nodes,
            on_event=lambda e: collect_events(events, e),
        )

        async def mock_check_node(_node: FailoverNodeConfig) -> bool:
            return True

        monitor._check_node = mock_check_node
        await monitor.check()
        assert len(events) == 0
