"""Long-running, cancellable tools for the voice agent.

Every tool here is deliberately real work, not a sleep: the interruption claim
is only interesting if the thing being interrupted actually costs something.
All of them are awaited inside a task tagged with a turn_id and must pass the
fence in agent.py before anything is spoken.
"""
from __future__ import annotations

import asyncio, html, json, re, urllib.parse
import aiohttp

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


async def web_search(query: str, k: int = 3) -> list[dict]:
    """Live web search. No API key. Returns [{title, snippet, url}]."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    async with aiohttp.ClientSession(headers=UA) as s:
        async with s.post("https://html.duckduckgo.com/html/",
                          data={"q": query}, timeout=aiohttp.ClientTimeout(total=20)) as r:
            page = await r.text()

    out = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        href, title, snip = m.groups()
        clean = lambda x: html.unescape(re.sub(r"<[^>]+>", "", x)).strip()
        u = urllib.parse.unquote(re.sub(r"^.*?uddg=", "", href).split("&")[0])
        out.append({"title": clean(title), "snippet": clean(snip), "url": u})
        if len(out) >= k:
            break
    return out


def speakable(results: list[dict], limit: int = 2) -> str:
    """Compress results into something short enough to say out loud."""
    if not results:
        return "I could not find anything on that."
    parts = [f"{r['title']}. {r['snippet'][:160]}" for r in results[:limit]]
    return " Next, ".join(parts)


if __name__ == "__main__":
    import sys, time
    q = " ".join(sys.argv[1:]) or "Rime AI text to speech latency"
    t0 = time.perf_counter()
    res = asyncio.run(web_search(q))
    dt = (time.perf_counter() - t0) * 1000
    print(f"query: {q}\nlatency: {dt:.0f} ms\nresults: {len(res)}\n")
    for r in res:
        print(" -", r["title"][:80]); print("   ", r["snippet"][:120]); print("   ", r["url"][:90])
    print("\nSPOKEN FORM:\n ", speakable(res))
