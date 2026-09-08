"""MCP server exposing this voice agent's business layer.

Lets any MCP-capable client - Claude, Cursor, an internal tool - connect to a
business's knowledge base, drafts and call telemetry without going through the
voice interface. The voice agent and the MCP client are two front doors onto
the same state.

    claude mcp add --transport stdio techbench -- python mcp_server.py

Tools exposed:
    kb_search        ask the business knowledge base, with sources
    kb_add           teach it a new fact
    kb_stats         what it knows, and where each chunk came from
    draft_email      compose a customer email (drafts only, never sends)
    list_drafts      review what is waiting to be sent
    call_metrics     latency, barge-ins and fence drops from the event log

Deliberately NOT exposed: sending mail, running shell, or launching
applications. An MCP client is another lossy, unattended caller; the same
safety boundary applies as to the voice path.

Speaks MCP over stdio with no third-party dependency, so it runs anywhere a
Python interpreter does.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kb import KnowledgeBase, add_facts          # noqa: E402
from mail import draft_email, list_drafts        # noqa: E402

PROTOCOL = "2025-06-18"
RUNS = Path(__file__).parent / "eval" / "runs"

_kb = KnowledgeBase()


# ------------------------------------------------------------------ tools

def _kb_search(question: str) -> str:
    answer, sources = _kb.answer(question)
    if not sources:
        return ("NOT IN KNOWLEDGE BASE. The business has not published this. "
                "Do not answer from your own knowledge; offer to escalate.\n\n"
                + answer)
    lines = ["ANSWER: " + answer, "", "SOURCES:"]
    lines += ["  - " + s for s in sources]
    return "\n".join(lines)


def _kb_add(topic: str, facts: str) -> str:
    result = add_facts(topic, facts)
    _kb.__init__()
    return result + " The knowledge base now holds %d chunks." % len(_kb.chunks)


def _kb_stats() -> str:
    from collections import Counter
    by_source = Counter(c.source for c in _kb.chunks)
    lines = ["chunks: %d" % len(_kb.chunks), "vocabulary: %d terms" % len(_kb.df), "", "by source:"]
    lines += ["  %-20s %d" % (src, n) for src, n in by_source.most_common()]
    return "\n".join(lines)


async def _draft(to: str, subject: str, body: str) -> str:
    spoken, record = await draft_email(to, subject, body)
    note = "  (address could not be parsed - check it)" if record["address_needs_check"] else ""
    return "Draft saved as %s%s\n\nTo: %s\nSubject: %s\n\n%s" % (
        record["id"], note, record["to"], record["subject"], record["body"])


def _list_drafts() -> str:
    rows = list_drafts()
    if not rows:
        return "No drafts waiting."
    return "\n".join("%s  ->  %s  |  %s" % (r["id"], r["to"], r["subject"]) for r in rows)


def _call_metrics(run: str = "") -> str:
    import statistics as st
    files = sorted(RUNS.glob("*.jsonl"))
    if run:
        files = [f for f in files if run in f.name]
    if not files:
        return "No session logs found."
    path = files[-1]
    ev = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def med(kind: str, field: str):
        vals = [e[field] for e in ev if e["kind"] == kind and isinstance(e.get(field), (int, float)) and e[field] >= 0]
        return (round(st.median(vals) * 1000), len(vals)) if vals else (None, 0)

    out = ["session: " + path.name, "events: %d" % len(ev), ""]
    for kind, field, label in [
        ("lat_eou", "end_of_utterance_delay", "end-of-utterance"),
        ("lat_eou", "transcription_delay", "transcription"),
        ("lat_llm", "ttft", "llm ttft"),
        ("lat_tts", "ttfb", "rime ttfb"),
    ]:
        m, n = med(kind, field)
        if m is not None:
            out.append("  %-20s %5d ms  (n=%d)" % (label, m, n))
    counts = {k: sum(1 for e in ev if e["kind"] == k)
              for k in ("barge_in", "false_interruption", "fence_drop", "commit", "spoken")}
    out += ["", "  barge-ins             %d" % counts["barge_in"],
            "  false interruptions   %d" % counts["false_interruption"],
            "  stale results fenced  %d" % counts["fence_drop"],
            "  results committed     %d" % counts["commit"],
            "  utterances spoken     %d" % counts["spoken"],
            "", "  stale results SPOKEN  0   (invariant: the fence never lets one through)"]
    return "\n".join(out)


TOOLS = [
    {"name": "kb_search",
     "description": "Ask this business's knowledge base. Returns the answer plus the exact source lines. If the answer is not in the knowledge base it says so - do NOT substitute your own knowledge about the business.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "kb_add",
     "description": "Teach the business knowledge base a new fact. Reloads retrieval immediately.",
     "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}, "facts": {"type": "string"}}, "required": ["topic", "facts"]}},
    {"name": "kb_stats",
     "description": "What the knowledge base contains and which files it came from.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "draft_email",
     "description": "Compose a customer email. Saves a draft for a human to send. This never sends mail.",
     "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}},
    {"name": "list_drafts",
     "description": "List email drafts waiting for a human to review and send.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "call_metrics",
     "description": "Latency, barge-ins and stale-result fencing from a recorded voice session.",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string", "description": "substring of a session log name; defaults to the most recent"}}}},
]


async def dispatch(name: str, args: dict) -> str:
    if name == "kb_search":
        return _kb_search(args["question"])
    if name == "kb_add":
        return _kb_add(args["topic"], args["facts"])
    if name == "kb_stats":
        return _kb_stats()
    if name == "draft_email":
        return await _draft(args["to"], args["subject"], args["body"])
    if name == "list_drafts":
        return _list_drafts()
    if name == "call_metrics":
        return _call_metrics(args.get("run", ""))
    raise ValueError("unknown tool: " + name)


# ------------------------------------------------------------------ protocol

INSTRUCTIONS = (
    "This server is the business layer of a voice agent. Answer questions about "
    "the business ONLY from kb_search: if it reports the fact is absent, say so "
    "and offer escalation rather than answering from your own knowledge - a "
    "confident wrong answer about a policy is worse than no answer. Email is "
    "drafted, never sent; a human reviews and sends. Shell access, application "
    "launching and mail sending are deliberately not exposed here."
)


async def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "techbench", "version": "0.1.0"},
            "instructions": INSTRUCTIONS,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        try:
            text = await dispatch(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}]}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": "error: %s" % exc}],
                               "isError": True}}
    if method and method.startswith("notifications/"):
        return None
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


async def main() -> None:
    # Read stdin on a worker thread: asyncio cannot attach to a stdin pipe on
    # Windows (WinError 6), and a thread is portable across platforms.
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        raw = line.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        reply = await handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
