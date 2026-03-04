"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from src.config import (
    Config,
    FailoverNodeConfig,
    MonitoringConfig,
    SlackConfig,
    SolanaConfig,
    VersionConfig,
)
from src.solana_client import SolanaClient
from src.webhook.slack import SlackWebhook


@pytest.fixture
def sample_config() -> Config:
    cfg = Config()
    cfg.solana = SolanaConfig(
        rpc_urls=["http://localhost:8899"],
        timeout_seconds=5,
        max_retries=2,
    )
    cfg.slack = SlackConfig(
        webhook_url="https://hooks.slack.com/test",
        rate_limit_per_minute=60,
        dedup_cooldown_seconds=10,
    )
    cfg.monitoring = MonitoringConfig(
        interval_seconds=5,
        rpc_health_check_interval=10,
        rpc_latency_threshold_ms=1000,
        slot_miss_threshold=2,
    )
    cfg.validator_identities = ["ValidatorPubkey1", "ValidatorPubkey2"]
    cfg.failover_nodes = [
        FailoverNodeConfig(
            id="primary-node",
            rpc_url="http://primary:8899",
            is_primary=True,
            health_check_failures_threshold=3,
        ),
        FailoverNodeConfig(
            id="secondary-node",
            rpc_url="http://secondary:8899",
            is_primary=False,
            health_check_failures_threshold=3,
        ),
    ]
    cfg.version = VersionConfig(component="jito-solana")
    return cfg


@pytest_asyncio.fixture
async def mock_solana_client() -> SolanaClient:
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
    client.measure_latency = AsyncMock(return_value=50.0)
    return client


@pytest_asyncio.fixture
async def events_collected() -> List:
    """A list that collects events emitted by monitors during tests."""
    return []
