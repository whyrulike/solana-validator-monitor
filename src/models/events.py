"""Pydantic v2 event models for the 6 monitored events.

Each model provides a ``to_slack_message()`` method that returns a Slack
Block Kit payload dict ready to be serialised to JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


_SEVERITY_COLORS: Dict[Severity, str] = {
    Severity.CRITICAL: "#FF0000",
    Severity.WARNING: "#FFA500",
    Severity.INFO: "#36A64F",
}

_SEVERITY_EMOJI: Dict[Severity, str] = {
    Severity.CRITICAL: "🔴",
    Severity.WARNING: "🟡",
    Severity.INFO: "🟢",
}


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class BaseEvent(BaseModel):
    """Common fields shared by all events."""

    event: str
    timestamp: datetime = Field(default_factory=_now_utc)
    severity: Severity

    def _build_slack_message(self, title: str, fields: list[Dict[str, Any]]) -> Dict[str, Any]:
        color = _SEVERITY_COLORS[self.severity]
        emoji = _SEVERITY_EMOJI[self.severity]
        ts_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        # Add fields as a section with markdown
        field_texts = [f"*{f['title']}*\n{f['value']}" for f in fields]
        if field_texts:
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": t} for t in field_texts
                    ],
                }
            )

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Event: `{self.event}` | {ts_str} | Severity: *{self.severity.value}*",
                    }
                ],
            }
        )

        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": blocks,
                }
            ]
        }

    def to_slack_message(self) -> Dict[str, Any]:
        raise NotImplementedError


class ValidatorDelinquentEvent(BaseEvent):
    """validator.delinquent – validator went delinquent."""

    event: str = "validator.delinquent"
    severity: Severity = Severity.CRITICAL
    validator_identity: str
    reason: str = "missed_votes"
    last_vote_slot: Optional[int] = None
    slots_behind: Optional[int] = None

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Validator Identity", "value": self.validator_identity},
            {"title": "Reason", "value": self.reason},
        ]
        if self.last_vote_slot is not None:
            fields.append({"title": "Last Vote Slot", "value": str(self.last_vote_slot)})
        if self.slots_behind is not None:
            fields.append({"title": "Slots Behind", "value": str(self.slots_behind)})
        return self._build_slack_message("Validator Delinquent", fields)


class ValidatorRecoveredEvent(BaseEvent):
    """validator.recovered – validator came back online."""

    event: str = "validator.recovered"
    severity: Severity = Severity.INFO
    validator_identity: str
    downtime_seconds: float

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Validator Identity", "value": self.validator_identity},
            {"title": "Downtime", "value": f"{self.downtime_seconds:.0f}s"},
        ]
        return self._build_slack_message("Validator Recovered", fields)


class ValidatorSlotMissedEvent(BaseEvent):
    """validator.slot_missed – leader slot was not produced."""

    event: str = "validator.slot_missed"
    severity: Severity = Severity.WARNING
    slot: int
    reason: str = "timeout"

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Slot", "value": str(self.slot)},
            {"title": "Reason", "value": self.reason},
        ]
        return self._build_slack_message("Leader Slot Missed", fields)


class ValidatorFailoverEvent(BaseEvent):
    """validator.failover – primary switched to secondary."""

    event: str = "validator.failover"
    severity: Severity = Severity.CRITICAL
    old_primary: str
    new_primary: str
    trigger: str = "health_check_failed"

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Old Primary", "value": self.old_primary},
            {"title": "New Primary", "value": self.new_primary},
            {"title": "Trigger", "value": self.trigger},
        ]
        return self._build_slack_message("Validator Failover", fields)


class ValidatorVersionChangeEvent(BaseEvent):
    """validator.version_change – software version changed."""

    event: str = "validator.version_change"
    severity: Severity = Severity.INFO
    old_version: str
    new_version: str
    component: str = "jito-solana"

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Component", "value": self.component},
            {"title": "Old Version", "value": self.old_version},
            {"title": "New Version", "value": self.new_version},
        ]
        return self._build_slack_message("Validator Version Change", fields)


class RpcUnhealthyEvent(BaseEvent):
    """rpc.unhealthy – RPC node is unhealthy or has high latency."""

    event: str = "rpc.unhealthy"
    severity: Severity = Severity.WARNING
    node_id: str
    reason: str
    latency_ms: Optional[float] = None

    def to_slack_message(self) -> Dict[str, Any]:
        fields = [
            {"title": "Node ID", "value": self.node_id},
            {"title": "Reason", "value": self.reason},
        ]
        if self.latency_ms is not None:
            fields.append({"title": "Latency", "value": f"{self.latency_ms:.0f} ms"})
        return self._build_slack_message("RPC Node Unhealthy", fields)
