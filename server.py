"""Web app: token minting + live event stream for the technician assistant.

Run alongside the agent:
    python agent.py dev          # the voice agent worker
    python server.py             # this, then open http://localhost:8080
"""
from __future__ import annotations

import asyncio, json, os, re, time
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

from kb import KB_DIR, KnowledgeBase

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


def _safe_name(raw: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9 _-]", "", raw).strip().replace(" ", "-")[:60]
    return (stem or "document") + ".md"


async def kb_add_doc(request: web.Request) -> web.Response:
    """Accept a pasted document or an uploaded .md/.txt and add it to the KB."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    title, body = "", ""

    if request.content_type and request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "title":
                title = (await part.text()).strip()
            elif part.name == "file":
                fname = part.filename or "document"
                if not fname.lower().endswith((".md", ".txt", ".pdf")):
                    return web.json_response(
                        {"error": "only .md, .txt or .pdf files"}, status=400)
                title = title or Path(fname).stem
                raw = await part.read()
                if fname.lower().endswith(".pdf"):
                    import io
                    from pypdf import PdfReader
                    pages = [pg.extract_text() or "" for pg in PdfReader(io.BytesIO(raw)).pages]
                    body = "\n\n".join(t.strip() for t in pages if t.strip())
                    if not body.strip():
                        return web.json_response(
                            {"error": "no text found in that PDF - is it a scan?"},
                            status=400)
                else:
                    body = raw.decode("utf-8", "replace")
    else:
        data = await request.json()
        title = (data.get("title") or "").strip()
        body = (data.get("text") or "").strip()

    if not body.strip():
        return web.json_response({"error": "no content"}, status=400)

    path = KB_DIR / _safe_name(title or "document")
    existing = path.exists() and path.stat().st_size > 0
    # A chunk beginning with "#" is treated as a label, so keep the heading on
    # its own and separate it from the body with a blank line.
    header = "" if body.lstrip().startswith("#") else "# " + (title or "Document") + "\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(("\n\n" if existing else "") + header + body.strip() + "\n")

    kb = KnowledgeBase()
    return web.json_response({"file": path.name, "chunks": len(kb.chunks)})


async def kb_status(request: web.Request) -> web.Response:
    from collections import Counter
    kb = KnowledgeBase()
    by_src = Counter(c.source for c in kb.chunks)
    return web.json_response({"chunks": len(kb.chunks), "sources": dict(by_src)})


async def index(request: web.Request) -> web.Response:
    return web.FileResponse(WEB / "index.html")


app = web.Application(client_max_size=25 * 1024 * 1024)   # allow PDF uploads
app.add_routes([
    web.get("/", index),
    web.get("/api/token", token),
    web.get("/api/events", events),
    web.post("/api/kb", kb_add_doc),
    web.get("/api/kb", kb_status),
    web.static("/static", WEB),
])

def _free_port(start: int = 8080, tries: int = 10) -> int:
    import socket
    for port in range(start, start + tries):
        with socket.socket() as sk:
            # Probe the SAME interface run_app will bind (0.0.0.0), not
            # 127.0.0.1 - otherwise the probe succeeds and the real bind fails.
            try:
                sk.bind(("0.0.0.0", port))
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
