"""Web app: token minting + live event stream for the technician assistant.

Run alongside the agent:
    python agent.py dev          # the voice agent worker
    python server.py             # this, then open http://localhost:8080
"""
from __future__ import annotations

import asyncio, json, os, time
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

ROOM = "techbench"
RUNS = Path("eval/runs")
WEB = Path("web")


async def token(request: web.Request) -> web.Response:
    identity = request.query.get("identity", f"tech-{int(time.time())}")
    grant = api.VideoGrants(room_join=True, room=ROOM, can_publish=True, can_subscribe=True)
    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("Technician")
        .with_grants(grant)
        .to_jwt()
    )
    return web.json_response({"token": jwt, "url": os.environ["LIVEKIT_URL"], "room": ROOM})


async def events(request: web.Request) -> web.StreamResponse:
    """Server-sent events: tail the agent's JSONL log to the browser."""
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
    await resp.prepare(request)
    RUNS.mkdir(parents=True, exist_ok=True)
    seen: dict[Path, int] = {}
    try:
        while True:
            for p in sorted(RUNS.glob("*.jsonl")):
                pos = seen.get(p, 0)
                size = p.stat().st_size
                if size > pos:
                    with p.open("r", encoding="utf-8") as fh:
                        fh.seek(pos)
                        for line in fh:
                            line = line.strip()
                            if line:
                                await resp.write(f"data: {line}\n\n".encode())
                    seen[p] = size
                elif p not in seen:
                    seen[p] = size
            await asyncio.sleep(0.25)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


async def index(request: web.Request) -> web.Response:
    return web.FileResponse(WEB / "index.html")


app = web.Application()
app.add_routes([
    web.get("/", index),
    web.get("/api/token", token),
    web.get("/api/events", events),
    web.static("/static", WEB),
])

def _free_port(start: int = 8080, tries: int = 10) -> int:
    import socket
    for port in range(start, start + tries):
        with socket.socket() as sk:
            sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sk.bind(("127.0.0.1", port))
                return port
            except OSError:
                print("port %d busy, trying %d" % (port, port + 1))
    raise SystemExit("no free port found")


if __name__ == "__main__":
    port = _free_port()
    print("")
    print("  open http://localhost:%d" % port)
    print("")
    web.run_app(app, port=port, print=None)
