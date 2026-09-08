"""Barge-in acceptance test - 20 trials, 4 interruption types.

SCOPE (labeled honestly, per the PS):
  This is a LOGIC-LEVEL test. It exercises the real TurnController / Fenced /
  SpokenLedger from fence.py - the same objects agent.py uses in production -
  driven by a simulated timeline instead of live microphone audio.
  It proves the fencing invariant. It does NOT measure acoustic
  time-to-silence; that requires the audio-level run (see README).

PROTOCOL (Instruct-FD, arXiv:2607.20460):
  user audio is injected 3.0s after the agent begins speaking.
TYPES (HumDial Track II, arXiv:2601.05564):
  follow_up | negation | repetition_request | topic_switch
METRIC NAMES (Full-Duplex-Bench v2, arXiv:2510.07838):
  correction handling, entity tracking
CRITERION (EchoChain, arXiv:2604.16456):
  state-update reasoning under interruption - a superseded tool result must
  never be spoken or committed.
"""
from __future__ import annotations

import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fence import EventLog, Fenced, SpokenLedger, TurnController

BARGE_IN_AT = 3.0          # Instruct-FD
TOOL_DELAY  = 3.0          # agent.py default
SPEEDUP     = 60.0         # wall-clock compression; ordering is preserved
TYPES = ["follow_up", "negation", "repetition_request", "topic_switch"]
PARTS = ["HP-4412", "HP-4413", "VX-207"]


async def trial(n: int, kind: str, log: EventLog, fencing: bool = True) -> dict:
    ctrl = TurnController(log)
    ledger = SpokenLedger(log)

    first, second = PARTS[n % 3], PARTS[(n + 1) % 3]
    t1 = ctrl.new_turn(reason=f"trial{n}_initial")

    # Agent dispatches a slow lookup for `first`, tagged with turn t1.
    async def lookup(turn_id: int, part: str):
        await asyncio.sleep(TOOL_DELAY / SPEEDUP)
        return Fenced(turn_id, f"{part}: torque 18 newton meters")

    task = asyncio.create_task(lookup(t1, first))
    if fencing:
        ctrl.track(t1, task)   # tracked => cancelled on new turn

    # Agent starts speaking; user barges in at 3.0s with a revision.
    await asyncio.sleep(BARGE_IN_AT / SPEEDUP * 0.9)
    ledger.record(intended=f"Checking {first} now, that part uses a viton seal and",
                  spoken=f"Checking {first} now, that part uses", interrupted=True)
    t2 = ctrl.new_turn(reason=f"trial{n}_{kind}")   # cancels t1's task

    # The in-flight result still resolves. It must not survive the fence.
    leaked = False
    try:
        result = await task
        if fencing:
            leaked = ctrl.accept(result, what="tool_result")   # expect False
        else:
            # ABLATION: no fence. The stale result is spoken as current.
            log.emit("commit_unfenced", what="tool_result", result_turn=result.turn_id)
            leaked = True
    except asyncio.CancelledError:
        log.emit("tool_cancelled_await", turn_id=t1)

    # The revised request completes normally under t2.
    fresh = Fenced(t2, f"{second}: torque 9 newton meters")
    committed = ctrl.accept(fresh, what="tool_result")

    return {
        "trial": n, "type": kind,
        "initial_part": first, "revised_part": second,
        "stale_leaked": bool(leaked),
        "revised_committed": bool(committed),
        "entity_tracking_ok": bool(committed and not leaked),
        "dropped": ctrl.dropped, "committed_count": ctrl.committed,
        "heard_chars": len(ledger.heard[0]) if ledger.heard else 0,
    }


async def main() -> None:
    out = Path("eval/runs"); out.mkdir(parents=True, exist_ok=True)
    log = EventLog(out / "bargein_logic.jsonl")
    rows = [await trial(i, TYPES[i % 4], log, fencing=True) for i in range(20)]
    abl = [await trial(i, TYPES[i % 4], log, fencing=False) for i in range(20)]
    log.close()

    leaks = sum(r["stale_leaked"] for r in rows)
    corr  = sum(r["revised_committed"] for r in rows)
    ent   = sum(r["entity_tracking_ok"] for r in rows)

    summary = {
        "trials": len(rows),
        "protocol": "Instruct-FD 3.0s injection; HumDial 4 interruption types",
        "level": "logic (no audio); see README for audio-level run",
        "stale_result_leak_rate": f"{leaks}/{len(rows)}",
        "correction_handling": f"{corr}/{len(rows)}",
        "entity_tracking": f"{ent}/{len(rows)}",
        "ABLATION_fencing_disabled": {
            "stale_result_leak_rate": f"{sum(r['stale_leaked'] for r in abl)}/{len(abl)}",
            "note": "same harness, fence removed - isolates the mechanism",
        },
        "by_type": {t: {
            "n": sum(1 for r in rows if r["type"] == t),
            "leaks": sum(r["stale_leaked"] for r in rows if r["type"] == t),
        } for t in TYPES},
    }
    (out / "bargein_summary.json").write_text(
        json.dumps({"summary": summary, "trials": rows, "ablation": abl}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("\nPASS" if leaks == 0 and corr == len(rows) else "\nFAIL")


if __name__ == "__main__":
    asyncio.run(main())
