"""Main entry point: asyncio orchestration of all monitoring tasks."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from asyncio import Task
from typing import List, Optional

from aiohttp import web

from src.config import Config, load_config
from src.models.events import BaseEvent
from src.monitors.failover_monitor import FailoverMonitor
from src.monitors.rpc_monitor import RpcMonitor
from src.monitors.slot_monitor import SlotMonitor
from src.monitors.validator_monitor import ValidatorMonitor
from src.monitors.version_monitor import VersionMonitor
from src.solana_client import SolanaClient
from src.webhook.slack import SlackWebhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _run_loop(name: str, coro_fn, interval: float) -> None:
    """Run a monitoring coroutine in a loop, catching exceptions so one bad check
    doesn't kill the whole task."""
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Monitor '%s' check failed: %s", name, exc)
        await asyncio.sleep(interval)


class MonitorApp:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._tasks: List[Task] = []
        self._webhook: Optional[SlackWebhook] = None
        self._client: Optional[SolanaClient] = None

    async def on_event(self, event: BaseEvent) -> None:
        """Central event handler: forwards to Slack."""
        logger.info("Event: %s", event.model_dump_json())
        if self._webhook:
            try:
                await self._webhook.send_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send Slack notification: %s", exc)

    async def start(self) -> None:
        cfg = self._cfg

        self._client = SolanaClient(
            rpc_urls=cfg.solana.rpc_urls,
            timeout_seconds=cfg.solana.timeout_seconds,
            max_retries=cfg.solana.max_retries,
        )
        await self._client.open()

        self._webhook = SlackWebhook(
            webhook_url=cfg.slack.webhook_url,
            rate_limit_per_minute=cfg.slack.rate_limit_per_minute,
            dedup_cooldown_seconds=cfg.slack.dedup_cooldown_seconds,
        )
        await self._webhook.open()

        _interval = cfg.monitoring.interval_seconds
        _rpc_interval = cfg.monitoring.rpc_health_check_interval

        validator_monitor = ValidatorMonitor(
            client=self._client,
            validator_identities=cfg.validator_identities,
            on_event=self.on_event,
        )
        slot_monitor = SlotMonitor(
            client=self._client,
            validator_identities=cfg.validator_identities,
            on_event=self.on_event,
            slot_miss_threshold=cfg.monitoring.slot_miss_threshold,
        )
        failover_monitor = FailoverMonitor(
            client=self._client,
            nodes=cfg.failover_nodes,
            on_event=self.on_event,
        )
        version_monitor = VersionMonitor(
            client=self._client,
            on_event=self.on_event,
            component=cfg.version.component,
        )
        rpc_monitor = RpcMonitor(
            rpc_urls=cfg.solana.rpc_urls,
            on_event=self.on_event,
            latency_threshold_ms=cfg.monitoring.rpc_latency_threshold_ms,
        )

        self._tasks = [
            asyncio.create_task(
                _run_loop("validator", validator_monitor.check, _interval),
                name="validator",
            ),
            asyncio.create_task(
                _run_loop("slot", slot_monitor.check, _interval),
                name="slot",
            ),
            asyncio.create_task(
                _run_loop("failover", failover_monitor.check, _rpc_interval),
                name="failover",
            ),
            asyncio.create_task(
                _run_loop("version", version_monitor.check, _rpc_interval),
                name="version",
            ),
            asyncio.create_task(
                _run_loop("rpc", rpc_monitor.check, _rpc_interval),
                name="rpc",
            ),
        ]

        logger.info("=== Solana Validator Monitor started ===")
        logger.info("RPC endpoints: %s", cfg.solana.rpc_urls)
        logger.info("Monitoring validators: %s", cfg.validator_identities)
        logger.info("Poll interval: %ds | RPC health interval: %ds", _interval, _rpc_interval)

    async def stop(self) -> None:
        logger.info("Shutting down…")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._client:
            await self._client.close()
        if self._webhook:
            await self._webhook.close()
        logger.info("Shutdown complete.")


async def health_handler(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def main() -> None:
    cfg = load_config()
    app = MonitorApp(cfg)

    # Health-check HTTP server (for Docker / K8s liveness probe)
    web_app = web.Application()
    web_app.router.add_get("/health", health_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Health-check server listening on :8080/health")

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await app.start()

    try:
        await stop_event.wait()
    finally:
        await app.stop()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
