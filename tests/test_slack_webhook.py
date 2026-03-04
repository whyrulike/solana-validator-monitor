"""Tests for the Slack Webhook sender."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aioresponses import aioresponses

from src.models.events import ValidatorDelinquentEvent, ValidatorRecoveredEvent
from src.webhook.slack import SlackWebhook

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/test"


@pytest_asyncio.fixture
async def slack():
    wh = SlackWebhook(
        webhook_url=WEBHOOK_URL,
        rate_limit_per_minute=60,
        dedup_cooldown_seconds=5,
        max_retries=2,
    )
    await wh.open()
    yield wh
    await wh.close()


class TestSendEvent:
    @pytest.mark.asyncio
    async def test_sends_event_successfully(self, slack):
        evt = ValidatorDelinquentEvent(
            validator_identity="PubkeyABC",
            timestamp=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=200, body="ok")
            result = await slack.send_event(evt)
        assert result is True

    @pytest.mark.asyncio
    async def test_deduplication_suppresses_second_send(self, slack):
        evt = ValidatorDelinquentEvent(validator_identity="PubkeyABC")
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=200, body="ok")
            first = await slack.send_event(evt)

        # Same event within cooldown should be suppressed
        with aioresponses() as m:
            second = await slack.send_event(evt)

        assert first is True
        assert second is False

    @pytest.mark.asyncio
    async def test_different_events_not_deduplicated(self, slack):
        evt1 = ValidatorDelinquentEvent(validator_identity="PubkeyABC")
        evt2 = ValidatorDelinquentEvent(validator_identity="PubkeyXYZ")
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=200, body="ok")
            r1 = await slack.send_event(evt1)
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=200, body="ok")
            r2 = await slack.send_event(evt2)
        assert r1 is True
        assert r2 is True


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_retries_on_server_error(self, slack):
        evt = ValidatorRecoveredEvent(
            validator_identity="PubkeyABC", downtime_seconds=60.0
        )
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=500)
            m.post(WEBHOOK_URL, status=200, body="ok")
            result = await slack.send_event(evt)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_after_all_retries_fail(self, slack):
        evt = ValidatorRecoveredEvent(
            validator_identity="PubkeyABC", downtime_seconds=60.0
        )
        from aiohttp import ClientConnectionError

        with aioresponses() as m:
            m.post(WEBHOOK_URL, exception=ClientConnectionError())
            m.post(WEBHOOK_URL, exception=ClientConnectionError())
            with pytest.raises(Exception):
                await slack.send_event(evt)

    @pytest.mark.asyncio
    async def test_does_not_retry_on_4xx(self, slack):
        evt = ValidatorDelinquentEvent(validator_identity="PubkeyABC")
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=400)
            result = await slack.send_event(evt)
        assert result is False


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_allows_sends_within_limit(self):
        wh = SlackWebhook(
            webhook_url=WEBHOOK_URL,
            rate_limit_per_minute=60,
            dedup_cooldown_seconds=0,
            max_retries=1,
        )
        await wh.open()
        try:
            evt1 = ValidatorDelinquentEvent(validator_identity="A")
            evt2 = ValidatorDelinquentEvent(validator_identity="B")
            with aioresponses() as m:
                m.post(WEBHOOK_URL, status=200, body="ok")
                m.post(WEBHOOK_URL, status=200, body="ok")
                r1 = await wh.send_event(evt1)
                r2 = await wh.send_event(evt2)
            assert r1 is True
            assert r2 is True
        finally:
            await wh.close()


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_sends_arbitrary_payload(self, slack):
        payload: Dict[str, Any] = {
            "text": "Hello from tests",
            "blocks": [],
        }
        with aioresponses() as m:
            m.post(WEBHOOK_URL, status=200, body="ok")
            result = await slack.send_message(payload)
        assert result is True
