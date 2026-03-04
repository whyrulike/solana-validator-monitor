"""Tests for Pydantic event models and Slack message generation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.events import (
    RpcUnhealthyEvent,
    Severity,
    ValidatorDelinquentEvent,
    ValidatorFailoverEvent,
    ValidatorRecoveredEvent,
    ValidatorSlotMissedEvent,
    ValidatorVersionChangeEvent,
)

FIXED_TS = datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc)


class TestValidatorDelinquentEvent:
    def test_defaults(self):
        evt = ValidatorDelinquentEvent(validator_identity="PubkeyABC")
        assert evt.event == "validator.delinquent"
        assert evt.severity == Severity.CRITICAL
        assert evt.reason == "missed_votes"

    def test_slack_message_structure(self):
        evt = ValidatorDelinquentEvent(
            validator_identity="PubkeyABC",
            last_vote_slot=290500000,
            slots_behind=150,
            timestamp=FIXED_TS,
        )
        msg = evt.to_slack_message()
        assert "attachments" in msg
        att = msg["attachments"][0]
        assert att["color"] == "#FF0000"
        # Header text should contain the validator identity info
        blocks = att["blocks"]
        header = blocks[0]
        assert "Delinquent" in header["text"]["text"]

    def test_slack_message_contains_identity(self):
        evt = ValidatorDelinquentEvent(
            validator_identity="MyValidator123",
            timestamp=FIXED_TS,
        )
        msg = evt.to_slack_message()
        msg_str = str(msg)
        assert "MyValidator123" in msg_str


class TestValidatorRecoveredEvent:
    def test_defaults(self):
        evt = ValidatorRecoveredEvent(
            validator_identity="PubkeyABC",
            downtime_seconds=300.0,
        )
        assert evt.event == "validator.recovered"
        assert evt.severity == Severity.INFO

    def test_slack_message_color_info(self):
        evt = ValidatorRecoveredEvent(
            validator_identity="PubkeyABC",
            downtime_seconds=300.0,
            timestamp=FIXED_TS,
        )
        msg = evt.to_slack_message()
        assert msg["attachments"][0]["color"] == "#36A64F"

    def test_downtime_in_message(self):
        evt = ValidatorRecoveredEvent(
            validator_identity="PubkeyABC",
            downtime_seconds=300.0,
            timestamp=FIXED_TS,
        )
        msg_str = str(evt.to_slack_message())
        assert "300" in msg_str


class TestValidatorSlotMissedEvent:
    def test_defaults(self):
        evt = ValidatorSlotMissedEvent(slot=12345)
        assert evt.event == "validator.slot_missed"
        assert evt.severity == Severity.WARNING
        assert evt.reason == "timeout"

    def test_slack_message_color_warning(self):
        evt = ValidatorSlotMissedEvent(slot=12345, timestamp=FIXED_TS)
        msg = evt.to_slack_message()
        assert msg["attachments"][0]["color"] == "#FFA500"

    def test_slot_in_message(self):
        evt = ValidatorSlotMissedEvent(slot=290500100, timestamp=FIXED_TS)
        msg_str = str(evt.to_slack_message())
        assert "290500100" in msg_str


class TestValidatorFailoverEvent:
    def test_defaults(self):
        evt = ValidatorFailoverEvent(old_primary="node-a", new_primary="node-b")
        assert evt.event == "validator.failover"
        assert evt.severity == Severity.CRITICAL
        assert evt.trigger == "health_check_failed"

    def test_slack_message_critical_color(self):
        evt = ValidatorFailoverEvent(
            old_primary="node-a", new_primary="node-b", timestamp=FIXED_TS
        )
        msg = evt.to_slack_message()
        assert msg["attachments"][0]["color"] == "#FF0000"

    def test_nodes_in_message(self):
        evt = ValidatorFailoverEvent(
            old_primary="huawei-sg-01", new_primary="ovh-sg-01", timestamp=FIXED_TS
        )
        msg_str = str(evt.to_slack_message())
        assert "huawei-sg-01" in msg_str
        assert "ovh-sg-01" in msg_str


class TestValidatorVersionChangeEvent:
    def test_defaults(self):
        evt = ValidatorVersionChangeEvent(
            old_version="1.18.22", new_version="1.18.23"
        )
        assert evt.event == "validator.version_change"
        assert evt.severity == Severity.INFO
        assert evt.component == "jito-solana"

    def test_slack_message_info_color(self):
        evt = ValidatorVersionChangeEvent(
            old_version="1.18.22", new_version="1.18.23", timestamp=FIXED_TS
        )
        msg = evt.to_slack_message()
        assert msg["attachments"][0]["color"] == "#36A64F"

    def test_versions_in_message(self):
        evt = ValidatorVersionChangeEvent(
            old_version="1.18.22", new_version="1.18.23", timestamp=FIXED_TS
        )
        msg_str = str(evt.to_slack_message())
        assert "1.18.22" in msg_str
        assert "1.18.23" in msg_str


class TestRpcUnhealthyEvent:
    def test_defaults(self):
        evt = RpcUnhealthyEvent(node_id="rpc-node-01", reason="high_latency")
        assert evt.event == "rpc.unhealthy"
        assert evt.severity == Severity.WARNING

    def test_slack_message_warning_color(self):
        evt = RpcUnhealthyEvent(
            node_id="rpc-node-01",
            reason="high_latency",
            latency_ms=2500.0,
            timestamp=FIXED_TS,
        )
        msg = evt.to_slack_message()
        assert msg["attachments"][0]["color"] == "#FFA500"

    def test_latency_in_message(self):
        evt = RpcUnhealthyEvent(
            node_id="rpc-node-01",
            reason="high_latency",
            latency_ms=2500.0,
            timestamp=FIXED_TS,
        )
        msg_str = str(evt.to_slack_message())
        assert "2500" in msg_str
        assert "rpc-node-01" in msg_str
