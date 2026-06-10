"""Shared base class for MQTT publisher lifecycle management.

Both ``MqttPublisher`` (private broker) and ``CommunityMqttPublisher``
(community aggregator) inherit from ``BaseMqttPublisher``, which owns
the connection-loop skeleton, reconnect/backoff logic, and publish method.
Subclasses override a small set of hooks to control configuration checks,
client construction, toast messages, and optional wait-loop behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from abc import ABC, abstractmethod
from typing import Any

import aiomqtt

logger = logging.getLogger(__name__)

_BACKOFF_MIN = 5


def _format_error_detail(exc: Exception) -> str:
    """Return a short operator-facing error string."""
    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


def _broadcast_health() -> None:
    """Push updated health (including MQTT status) to all WS clients."""
    from app.services.radio_runtime import radio_runtime as radio_manager
    from app.websocket import broadcast_health

    broadcast_health(radio_manager.is_connected, radio_manager.connection_info)


class BaseMqttPublisher(ABC):
    """Base class for MQTT publishers with shared lifecycle management.

    Subclasses implement the abstract hooks to control configuration checks,
    client construction, toast messages, and optional wait-loop behavior.

    The settings type is duck-typed — each subclass defines a Protocol
    describing the attributes it expects (e.g. ``PrivateMqttSettings``,
    ``CommunityMqttSettings``). Callers pass ``SimpleNamespace`` instances
    that satisfy the protocol.
    """

    _backoff_max: int = 30
    _log_prefix: str = "MQTT"
    _not_configured_timeout: float | None = None  # None = block forever

    def __init__(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._settings: Any = None
        self._settings_version: int = 0
        self._version_event: asyncio.Event = asyncio.Event()
        self.connected: bool = False
        self.integration_name: str = ""
        self._last_error: str | None = None
        self._error_notified: bool = False
        self._consecutive_publish_failures: int = 0
        self._last_successful_publish: float = 0.0

    def set_integration_name(self, name: str) -> None:
        """Attach the configured fanout-module name for operator-facing logs."""
        self.integration_name = name.strip()

    def _integration_label(self) -> str:
        """Return a concise label for logs, including the configured module name."""
        if self.integration_name:
            return f"{self._log_prefix} [{self.integration_name}]"
        return self._log_prefix

    @property
    def last_error(self) -> str | None:
        """Return the most recent retained connection/publish error."""
        return self._last_error

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self, settings: object) -> None:
        """Start the background connection loop."""
        self._settings = settings
        self._last_error = None
        self._settings_version += 1
        self._version_event.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        """Cancel the background task and disconnect."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        self.connected = False
        self._last_error = None
        self._error_notified = False
        self._consecutive_publish_failures = 0
        self._last_successful_publish = 0.0

    async def restart(self, settings: object) -> None:
        """Called when settings change — stop + start."""
        await self.stop()
        await self.start(settings)

    async def publish(self, topic: str, payload: dict[str, Any], *, retain: bool = False) -> None:
        """Publish a JSON payload. Drops silently if not connected."""
        if self._client is None or not self.connected:
            return
        try:
            # logger.debug("%s publishing to %s", self._integration_label(), topic)
            await self._client.publish(topic, json.dumps(payload), retain=retain)
            # Track successful publish
            self._consecutive_publish_failures = 0
            self._last_successful_publish = time.time()
        except aiomqtt.MqttCodeError as e:
            # Code 4 = "not connected" - this is expected during connection startup race conditions.
            # Silently drop the message as if self.connected was False.
            if e.rc == 4:
                logger.debug(
                    "%s dropping publish during connection handshake (MQTT not ready yet)",
                    self._integration_label(),
                )
                return
            # Other MQTT errors (authentication, protocol, etc.) - log and mark disconnected
            self._consecutive_publish_failures += 1
            logger.warning(
                "%s publish failed on %s with MQTT error code %s: %s (consecutive failures: %d)",
                self._integration_label(),
                topic,
                e.rc,
                e,
                self._consecutive_publish_failures,
            )
            self.connected = False
            self._last_error = _format_error_detail(e)
            self._settings_version += 1
            self._version_event.set()
        except Exception as e:
            self._consecutive_publish_failures += 1
            logger.warning(
                "%s publish failed on %s (consecutive failures: %d). This is usually transient network noise; "
                "if it self-resolves and reconnects, it is generally not a concern. Persistent errors may indicate a problem with your network connection or MQTT broker. Original error: %s",
                self._integration_label(),
                topic,
                self._consecutive_publish_failures,
                e,
                exc_info=True,
            )
            self.connected = False
            self._last_error = _format_error_detail(e)
            # Wake the connection loop so it exits the wait and reconnects
            self._settings_version += 1
            self._version_event.set()

    # ── Abstract hooks ─────────────────────────────────────────────────

    @abstractmethod
    def _is_configured(self) -> bool:
        """Return True when this publisher should attempt to connect."""

    @abstractmethod
    def _build_client_kwargs(self, settings: object) -> dict[str, Any]:
        """Return the keyword arguments for ``aiomqtt.Client(...)``."""

    @abstractmethod
    def _on_connected(self, settings: object) -> tuple[str, str]:
        """Return ``(title, detail)`` for the success toast on connect."""

    @abstractmethod
    def _on_error(self) -> tuple[str, str]:
        """Return ``(title, detail)`` for the error toast on connect failure."""

    # ── Optional hooks ─────────────────────────────────────────────────

    def _should_break_wait(self, elapsed: float) -> bool:
        """Return True to break the inner wait (e.g. token expiry)."""
        return False

    async def _pre_connect(self, settings: object) -> bool:
        """Called before connecting. Return True to proceed, False to retry."""
        return True

    def _on_not_configured(self) -> None:
        """Called each time the loop finds the publisher not configured."""
        return  # no-op by default; subclasses may override

    async def _on_connected_async(self, settings: object) -> None:
        """Async hook called after connection succeeds (before health broadcast).

        Subclasses can override to publish messages immediately after connecting.
        """
        return  # no-op by default

    async def _on_periodic_wake(self, elapsed: float) -> None:
        """Called every ~60s while connected. Subclasses may override."""
        return

    # ── Connection loop ────────────────────────────────────────────────

    async def _connection_loop(self) -> None:
        """Background loop: connect, wait for version change, reconnect on failure."""
        from app.websocket import broadcast_error, broadcast_success

        backoff = _BACKOFF_MIN

        while True:
            if not self._is_configured():
                self._on_not_configured()
                self.connected = False
                self._client = None
                self._version_event.clear()
                try:
                    if self._not_configured_timeout is None:
                        await self._version_event.wait()
                    else:
                        await asyncio.wait_for(
                            self._version_event.wait(),
                            timeout=self._not_configured_timeout,
                        )
                except TimeoutError:
                    continue
                except asyncio.CancelledError:
                    return
                continue

            settings = self._settings
            assert settings is not None  # guaranteed by _is_configured()
            version_at_connect = self._settings_version

            try:
                if not await self._pre_connect(settings):
                    continue

                client_kwargs = self._build_client_kwargs(settings)
                connect_time = time.monotonic()

                # Log connection attempt with broker details for debugging
                broker_info = f"{client_kwargs.get('hostname', 'unknown')}:{client_kwargs.get('port', 'unknown')}"
                transport_info = client_kwargs.get("transport", "tcp")
                logger.info(
                    "%s attempting connection to %s via %s (keepalive=%ds, protocol=%s, timeout=%ss)",
                    self._integration_label(),
                    broker_info,
                    transport_info,
                    client_kwargs.get("keepalive", 60),
                    client_kwargs.get("protocol", "unknown"),
                    client_kwargs.get("timeout", "unknown"),
                )

                async with aiomqtt.Client(**client_kwargs) as client:
                    self._client = client
                    self._last_error = None
                    self._error_notified = False
                    backoff = _BACKOFF_MIN

                    # Give the MQTT connection time to stabilize before marking as connected.
                    # WebSocket connections need longer (2s) for the full TLS + WS + MQTT handshake.
                    # TCP connections can use a shorter delay (1s).
                    # Only set connected=True AFTER this delay to prevent race conditions where
                    # packets try to publish before MQTT CONNACK completes.
                    transport = client_kwargs.get("transport", "tcp")
                    delay = 2.0 if transport == "websockets" else 1.0
                    await asyncio.sleep(delay)
                    self.connected = True
                    self._consecutive_publish_failures = 0
                    self._last_successful_publish = time.time()

                    title, detail = self._on_connected(settings)
                    broadcast_success(title, detail)
                    await self._on_connected_async(settings)
                    _broadcast_health()

                    # Wait until cancelled or settings version changes.
                    # The 60s timeout is a housekeeping wake-up; actual connection
                    # liveness is handled by paho-mqtt's keepalive mechanism.
                    while self._settings_version == version_at_connect:
                        self._version_event.clear()
                        try:
                            await asyncio.wait_for(self._version_event.wait(), timeout=60)
                        except TimeoutError:
                            elapsed = time.monotonic() - connect_time
                            await self._on_periodic_wake(elapsed)
                            if self._should_break_wait(elapsed):
                                break
                            # If we haven't had a successful publish in the last 10 minutes,
                            # the connection may be silently broken. Force reconnect.
                            if self._last_successful_publish > 0:
                                time_since_last_publish = time.time() - self._last_successful_publish
                                if time_since_last_publish > 600:  # 10 minutes
                                    logger.warning(
                                        "%s no successful publishes for %.0f seconds, "
                                        "connection may be silently broken. Forcing reconnect.",
                                        self._integration_label(),
                                        time_since_last_publish,
                                    )
                                    break
                            continue

                # async with exited — client is now closed
                self._client = None
                self.connected = False
                _broadcast_health()

            except asyncio.CancelledError:
                self.connected = False
                self._client = None
                return

            except Exception as e:
                self.connected = False
                self._client = None
                self._last_error = _format_error_detail(e)

                # Windows ProactorEventLoop does not implement add_reader /
                # add_writer, which paho-mqtt requires.  The failure can
                # surface as a direct NotImplementedError (add_writer in
                # __aenter__) or as a generic timeout (add_reader fails
                # inside an event-loop callback, so paho never hears back).
                # Either way, if we're on Windows with Proactor the root
                # cause is the same and retrying won't help.
                _on_proactor = (
                    sys.platform == "win32"
                    and type(asyncio.get_event_loop()).__name__ == "ProactorEventLoop"
                )
                if _on_proactor:
                    broadcast_error(
                        "MQTT unavailable — Windows event loop incompatible",
                        "The default Windows event loop (ProactorEventLoop) does "
                        "not support MQTT. Add --loop none to your uvicorn "
                        "command and restart. See README.md for details.",
                    )
                    _broadcast_health()
                    logger.error(
                        "%s cannot run: Windows ProactorEventLoop does not "
                        "implement add_reader/add_writer required by paho-mqtt. "
                        "Restart uvicorn with '--loop none' to use "
                        "SelectorEventLoop instead. Giving up (will not retry).",
                        self._integration_label(),
                    )
                    return

                if not self._error_notified:
                    title, detail = self._on_error()
                    broadcast_error(title, detail)
                    _broadcast_health()
                    self._error_notified = True
                logger.warning(
                    "%s connection error. This is usually transient network noise; "
                    "if it self-resolves, it is generally not a concern: %s "
                    "(reconnecting in %ds). If this error persists, check your network connection and MQTT broker status.",
                    self._integration_label(),
                    e,
                    backoff,
                    exc_info=True,
                )

                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, self._backoff_max)
