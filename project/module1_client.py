"""Module 1: resilient asyncio WebSocket connection loop.

Requires Python 3.10+ and the `websockets` library (only third-party dep).

Design notes
------------
* Backoff: "full jitter" -> sleep = uniform(0, min(max_delay, base * 2**attempt)).
* The attempt counter only resets after a session stayed up for `stable_after`
  seconds. Otherwise a server that accepts then instantly drops us would be
  hammered in a tight loop.
* Half-open detection has two layers:
    1. Protocol pings (ping_interval / ping_timeout, handled by `websockets`).
    2. An application idle watchdog (idle_timeout): if no data frame arrives
       in that window the session is treated as dead, even if pings are
       still answered (e.g. a proxy that is alive but the feed is stale).
* Every session lives inside `async with`, so the socket is closed on every
  exit path (error, idle timeout, stop, cancellation).
* No module-level mutable state; everything hangs off the instance.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import websockets
from websockets.exceptions import WebSocketException

log = logging.getLogger("module1")

MessageHandler = Callable[[Any], Awaitable[None]]
ConnectHook = Callable[[Any], Awaitable[None]]


@dataclass
class ClientStats:
    connects: int = 0
    disconnects: int = 0
    messages: int = 0
    handler_errors: int = 0
    backoff_delays: list[float] = field(default_factory=list)


class ResilientWSClient:
    def __init__(
        self,
        url: str,
        on_message: MessageHandler,
        *,
        on_connect: Optional[ConnectHook] = None,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        ping_interval: Optional[float] = 20.0,
        ping_timeout: Optional[float] = 20.0,
        idle_timeout: Optional[float] = 30.0,
        open_timeout: float = 10.0,
        close_timeout: float = 2.0,
        stable_after: float = 10.0,
        stop_event: Optional[asyncio.Event] = None,
        rng: Optional[random.Random] = None,
        connect: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if base_delay <= 0 or max_delay < base_delay:
            raise ValueError("need 0 < base_delay <= max_delay")
        self.url = url
        self._on_message = on_message
        self._on_connect = on_connect
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.idle_timeout = idle_timeout
        self.open_timeout = open_timeout
        self.close_timeout = close_timeout
        self.stable_after = stable_after
        self._stop = stop_event if stop_event is not None else asyncio.Event()
        self._rng = rng if rng is not None else random.Random()
        self._connect = connect if connect is not None else websockets.connect
        self._clock = clock
        self.stats = ClientStats()

    def stop(self) -> None:
        self._stop.set()

    def _next_delay(self, attempt: int) -> float:
        ceiling = min(self.max_delay, self.base_delay * (2 ** min(attempt, 32)))
        return self._rng.uniform(0.0, ceiling)

    async def _sleep_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def run(self) -> None:
        """Run until stop() is called or the task is cancelled."""
        attempt = 0
        while not self._stop.is_set():
            session_start: Optional[float] = None
            try:
                async with self._connect(
                    self.url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    open_timeout=self.open_timeout,
                    close_timeout=self.close_timeout,
                ) as ws:
                    session_start = self._clock()
                    self.stats.connects += 1
                    log.info("connected: %s", self.url)
                    if self._on_connect is not None:
                        await self._on_connect(ws)
                    await self._pump(ws)
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
                log.warning("connection ended: %r", exc)
            except Exception:  # supervisor must survive bugs in hooks
                log.exception("unexpected error in session")

            if session_start is not None:
                self.stats.disconnects += 1
                if self._clock() - session_start >= self.stable_after:
                    attempt = 0
            if self._stop.is_set():
                break

            delay = self._next_delay(attempt)
            attempt = min(attempt + 1, 32)
            self.stats.backoff_delays.append(delay)
            log.info("reconnecting in %.3fs (attempt %d)", delay, attempt)
            await self._sleep_or_stop(delay)

    async def _pump(self, ws: Any) -> None:
        stop_wait = asyncio.ensure_future(self._stop.wait())
        try:
            while not self._stop.is_set():
                recv = asyncio.ensure_future(ws.recv())
                try:
                    done, _ = await asyncio.wait(
                        {recv, stop_wait},
                        timeout=self.idle_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise asyncio.TimeoutError(
                            f"no data for {self.idle_timeout}s"
                        )
                    if recv not in done:
                        return  # stop requested
                    message = recv.result()  # may raise ConnectionClosed
                finally:
                    if not recv.done():
                        recv.cancel()
                        await asyncio.gather(recv, return_exceptions=True)
                self.stats.messages += 1
                try:
                    await self._on_message(message)
                except Exception:
                    self.stats.handler_errors += 1
                    log.exception("on_message handler failed")
        finally:
            stop_wait.cancel()
            await asyncio.gather(stop_wait, return_exceptions=True)


async def run(
    url: str,
    on_message: MessageHandler,
    stop: asyncio.Event,
    **kwargs: Any,
) -> None:
    """Uniform entry point used by the fault harness."""
    allowed = set(inspect.signature(ResilientWSClient.__init__).parameters)
    opts = {k: v for k, v in kwargs.items() if k in allowed}
    await ResilientWSClient(url, on_message, stop_event=stop, **opts).run()
