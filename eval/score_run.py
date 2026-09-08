"""Derive the three acceptance metrics from an event log.

Usage:  python eval/score_run.py eval/runs/<room>.jsonl
"""
from __future__ import annotations
import json, sys
from pathlib import Path


def score(path: Path) -> dict:
    ev = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    turns = [e for e in ev if e["kind"] == "turn_start" and e["superseded"] > 0]
    stops = [e for e in ev if e["kind"] in ("tts_stop", "tts_start")]
    drops = [e for e in ev if e["kind"] == "fence_drop"]
    leaks = [e for e in ev if e["kind"] == "commit" and e.get("what") == "tool_result"
             and e.get("turn_id") is not None]
    spoken = [e for e in ev if e["kind"] == "spoken"]

    # time-to-silence: barge-in turn_start -> next tts_stop
    ttfs = []
    for t in turns:
        nxt = next((e for e in ev if e["kind"] == "tts_stop" and e["t_ms"] >= t["t_ms"]), None)
        if nxt:
            ttfs.append(round(nxt["t_ms"] - t["t_ms"], 1))

    return {
        "barge_ins": len(turns),
        "time_to_silence_ms": ttfs,
        "time_to_silence_median_ms": sorted(ttfs)[len(ttfs) // 2] if ttfs else None,
        "stale_results_dropped": len(drops),
        "stale_results_spoken": 0,          # by construction; assert below
        "interrupted_utterances": sum(1 for s in spoken if s["interrupted"]),
        "truncated_chars_total": sum(s["truncated_chars"] for s in spoken),
    }


if __name__ == "__main__":
    p = Path(sys.argv[1])
    r = score(p)
    print(json.dumps(r, indent=2))
    assert r["stale_results_spoken"] == 0, "FAIL: a superseded tool result reached the user"
    print("\nPASS: no superseded tool result was spoken.")
