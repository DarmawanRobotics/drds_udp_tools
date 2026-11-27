from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

# kinds kept in the replay history for freshly connected GUIs
HISTORY_KINDS = {"tx", "rx", "log", "session", "suite"}


class EventBus:
    """Fan-out of engine events to WebSocket clients (drop-oldest on overflow)."""

    def __init__(self, history: int = 1500) -> None:
        self._subs: set[asyncio.Queue] = set()
        self.history: deque[dict] = deque(maxlen=history)
        self._seq = 0
        self.dropped = 0

    def publish(self, kind: str, payload: dict[str, Any]) -> dict:
        self._seq += 1
        ev = {"seq": self._seq, "kind": kind, "ts": time.time(), **payload}
        if kind in HISTORY_KINDS:
            self.history.append(ev)
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(ev)
        return ev

    def subscribe(self, maxsize: int = 4000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def recent(self, limit: int = 300, kinds: set[str] | None = None) -> list[dict]:
        items = [e for e in self.history if not kinds or e["kind"] in kinds]
        return items[-limit:]

    @property
    def subscribers(self) -> int:
        return len(self._subs)
