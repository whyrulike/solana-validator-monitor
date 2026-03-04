"""Configuration management: loads YAML config and applies environment variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class SolanaConfig:
    rpc_urls: List[str] = field(default_factory=lambda: ["https://api.mainnet-beta.solana.com"])
    timeout_seconds: int = 30
    max_retries: int = 3


@dataclass
class SlackConfig:
    webhook_url: str = ""
    rate_limit_per_minute: int = 30
    dedup_cooldown_seconds: int = 300


@dataclass
class MonitoringConfig:
    interval_seconds: int = 10
    rpc_health_check_interval: int = 30
    rpc_latency_threshold_ms: int = 2000
    slot_miss_threshold: int = 5


@dataclass
class FailoverNodeConfig:
    id: str = ""
    rpc_url: str = ""
    is_primary: bool = False
    health_check_failures_threshold: int = 3


@dataclass
class VersionConfig:
    component: str = "jito-solana"


@dataclass
class Config:
    solana: SolanaConfig = field(default_factory=SolanaConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    validator_identities: List[str] = field(default_factory=list)
    failover_nodes: List[FailoverNodeConfig] = field(default_factory=list)
    version: VersionConfig = field(default_factory=VersionConfig)


def _load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _apply_env_overrides(cfg: Config) -> None:
    """Apply environment variable overrides. ENV vars take priority over YAML."""
    # Solana RPC
    rpc_urls_env = os.environ.get("SOLANA_RPC_URLS")
    if rpc_urls_env:
        cfg.solana.rpc_urls = [u.strip() for u in rpc_urls_env.split(",") if u.strip()]

    timeout_env = os.environ.get("SOLANA_TIMEOUT_SECONDS")
    if timeout_env:
        cfg.solana.timeout_seconds = int(timeout_env)

    max_retries_env = os.environ.get("SOLANA_MAX_RETRIES")
    if max_retries_env:
        cfg.solana.max_retries = int(max_retries_env)

    # Slack
    webhook_url_env = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook_url_env:
        cfg.slack.webhook_url = webhook_url_env

    rate_limit_env = os.environ.get("SLACK_RATE_LIMIT_PER_MINUTE")
    if rate_limit_env:
        cfg.slack.rate_limit_per_minute = int(rate_limit_env)

    dedup_env = os.environ.get("SLACK_DEDUP_COOLDOWN_SECONDS")
    if dedup_env:
        cfg.slack.dedup_cooldown_seconds = int(dedup_env)

    # Monitoring
    interval_env = os.environ.get("MONITOR_INTERVAL_SECONDS")
    if interval_env:
        cfg.monitoring.interval_seconds = int(interval_env)

    rpc_interval_env = os.environ.get("RPC_HEALTH_CHECK_INTERVAL")
    if rpc_interval_env:
        cfg.monitoring.rpc_health_check_interval = int(rpc_interval_env)

    rpc_latency_env = os.environ.get("RPC_LATENCY_THRESHOLD_MS")
    if rpc_latency_env:
        cfg.monitoring.rpc_latency_threshold_ms = int(rpc_latency_env)

    slot_miss_env = os.environ.get("SLOT_MISS_THRESHOLD")
    if slot_miss_env:
        cfg.monitoring.slot_miss_threshold = int(slot_miss_env)

    # Validator identities
    identities_env = os.environ.get("VALIDATOR_IDENTITIES")
    if identities_env:
        cfg.validator_identities = [i.strip() for i in identities_env.split(",") if i.strip()]

    # Version component
    component_env = os.environ.get("VERSION_COMPONENT")
    if component_env:
        cfg.version.component = component_env


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file and apply environment variable overrides."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config.yaml")

    raw = _load_yaml(config_path)

    cfg = Config()

    # Solana section
    solana_raw = raw.get("solana", {})
    if solana_raw:
        cfg.solana = SolanaConfig(
            rpc_urls=solana_raw.get("rpc_urls", cfg.solana.rpc_urls),
            timeout_seconds=solana_raw.get("timeout_seconds", cfg.solana.timeout_seconds),
            max_retries=solana_raw.get("max_retries", cfg.solana.max_retries),
        )

    # Slack section
    slack_raw = raw.get("slack", {})
    if slack_raw:
        cfg.slack = SlackConfig(
            webhook_url=slack_raw.get("webhook_url", cfg.slack.webhook_url),
            rate_limit_per_minute=slack_raw.get(
                "rate_limit_per_minute", cfg.slack.rate_limit_per_minute
            ),
            dedup_cooldown_seconds=slack_raw.get(
                "dedup_cooldown_seconds", cfg.slack.dedup_cooldown_seconds
            ),
        )

    # Monitoring section
    monitoring_raw = raw.get("monitoring", {})
    if monitoring_raw:
        cfg.monitoring = MonitoringConfig(
            interval_seconds=monitoring_raw.get(
                "interval_seconds", cfg.monitoring.interval_seconds
            ),
            rpc_health_check_interval=monitoring_raw.get(
                "rpc_health_check_interval", cfg.monitoring.rpc_health_check_interval
            ),
            rpc_latency_threshold_ms=monitoring_raw.get(
                "rpc_latency_threshold_ms", cfg.monitoring.rpc_latency_threshold_ms
            ),
            slot_miss_threshold=monitoring_raw.get(
                "slot_miss_threshold", cfg.monitoring.slot_miss_threshold
            ),
        )

    # Validator identities
    cfg.validator_identities = raw.get("validator_identities", cfg.validator_identities)

    # Failover nodes
    failover_raw = raw.get("failover_nodes", [])
    cfg.failover_nodes = [
        FailoverNodeConfig(
            id=fn.get("id", ""),
            rpc_url=fn.get("rpc_url", ""),
            is_primary=fn.get("is_primary", False),
            health_check_failures_threshold=fn.get("health_check_failures_threshold", 3),
        )
        for fn in failover_raw
    ]

    # Version section
    version_raw = raw.get("version", {})
    if version_raw:
        cfg.version = VersionConfig(component=version_raw.get("component", cfg.version.component))

    # Apply environment variable overrides last
    _apply_env_overrides(cfg)

    return cfg
