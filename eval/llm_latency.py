"""TTFT benchmark across LiveKit Inference models. Voice agents live or die on
time-to-first-token, so pick the model by measurement, not reputation."""
import asyncio, statistics as st, time
from dotenv import load_dotenv; load_dotenv()
from livekit.agents import inference
from livekit.agents.llm import ChatContext

MODELS = [
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
    "google/gemini-3.1-flash-lite",
    "xai/grok-4-1-fast-non-reasoning",
    "openai/gpt-oss-120b",
]
PROMPT = "A caller asks about your return policy. Reply in one short sentence."

async def ttft(model, n=3):
    out = []
    for _ in range(n):
        try:
            llm = inference.LLM(model)
            ctx = ChatContext(); ctx.add_message(role="user", content=PROMPT)
            t0 = time.perf_counter(); first = None
            async with llm.chat(chat_ctx=ctx) as stream:
                async for _c in stream:
                    if first is None:
                        first = (time.perf_counter() - t0) * 1000
                        break
            if first: out.append(first)
        except Exception as e:
            return None, type(e).__name__
    return out, None

async def main():
    print("%-34s %8s %8s" % ("model", "median", "best"))
    for m in MODELS:
        vals, err = await ttft(m)
        if err or not vals:
            print("%-34s   %s" % (m, err or "no data")); continue
        print("%-34s %6.0fms %6.0fms" % (m, st.median(vals), min(vals)))

asyncio.run(main())
