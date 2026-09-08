"""Turn fencing: the mechanism this project exists to demonstrate.

Claim: stopping playback is easy; keeping application state consistent with
what the user actually heard is not. Every async result carries the turn it was
born under. Results from a superseded turn are dropped before they can be
spoken or committed to state.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------- event log

class EventLog:
    """Monotonic, append-only record. Every metric is derived from this file."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._t0 = time.perf_counter()
        self._fh = self.path.open("a", encoding="utf-8")

    def emit(self, kind: str, **fields: Any) -> None:
        rec = {"t_ms": round((time.perf_counter() - self._t0) * 1000, 2), "kind": kind, **fields}
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


# ---------------------------------------------------------------- the fence

@dataclass
class Fenced:
    """A result tagged with the turn that requested it."""
    turn_id: int
    payload: Any


class TurnController:
    """Owns the monotonic turn id and the set of in-flight tasks per turn.

    A new user turn supersedes the previous one: in-flight work is cancelled,
    and anything that still returns is rejected by `accept()`.
    """

    def __init__(self, log: EventLog):
        self._turn_id = 0
        self._tasks: dict[int, set[asyncio.Task]] = {}
        self.log = log
        self.dropped = 0
        self.committed = 0

    @property
    def current(self) -> int:
        return self._turn_id

    def new_turn(self, reason: str = "user_speech") -> int:
        """Advance the turn. Cancel everything the previous turn started."""
        superseded = self._turn_id
        self._turn_id += 1
        self.log.emit("turn_start", turn_id=self._turn_id, superseded=superseded, reason=reason)
        self._cancel(superseded)
        return self._turn_id

    def _cancel(self, turn_id: int) -> None:
        for task in self._tasks.pop(turn_id, set()):
            if not task.done():
                task.cancel()
                self.log.emit("tool_cancelled", turn_id=turn_id)

    def track(self, turn_id: int, task: asyncio.Task) -> None:
        self._tasks.setdefault(turn_id, set()).add(task)

    def accept(self, result: Fenced, what: str) -> bool:
        """The ten lines the whole submission rests on."""
        if result.turn_id != self._turn_id:
            self.dropped += 1
            self.log.emit(
                "fence_drop", what=what,
                result_turn=result.turn_id, current_turn=self._turn_id,
            )
            return False
        self.committed += 1
        self.log.emit("commit", what=what, turn_id=result.turn_id)
        return True


# ------------------------------------------------------------ spoken ledger

@dataclass
class SpokenLedger:
    """What the user ACTUALLY heard - not what we intended to say.

    On interruption, TTS playback is truncated. Conversation history must
    record the truncated text, or the model's context diverges from the
    user's ears. (cf. EchoChain, arXiv:2604.16456 - state-update reasoning
    under interruption.)
    """
    log: EventLog
    heard: list[str] = field(default_factory=list)

    def record(self, intended: str, spoken: str, interrupted: bool) -> None:
        self.heard.append(spoken)
        self.log.emit(
            "spoken", interrupted=interrupted,
            intended_chars=len(intended), spoken_chars=len(spoken),
            truncated_chars=len(intended) - len(spoken),
        )
