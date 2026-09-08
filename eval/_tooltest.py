import asyncio
from dotenv import load_dotenv; load_dotenv()
from livekit.agents import inference
from livekit.agents.llm import ChatContext, function_tool
from livekit.agents.llm.tool_context import ToolContext

@function_tool
async def answer_enquiry(question: str) -> str:
    """Answer any business question: hours, delivery, returns.

    Args:
        question: what the caller asked.
    """
    return "ok"

async def run(model):
    try:
        llm = inference.LLM(model)
        ctx = ChatContext(); ctx.add_message(role="user", content="What are your opening hours?")
        tc = ToolContext([answer_enquiry])
        got = []
        async with llm.chat(chat_ctx=ctx, tools=tc.function_tools.values()) as stream:
            async for c in stream:
                d = getattr(c, "delta", None)
                if d and getattr(d, "tool_calls", None): got.append("TOOLCALL")
                if d and getattr(d, "content", None): got.append("TEXT")
        print("  %-26s -> %s" % (model, ",".join(dict.fromkeys(got)) or "EMPTY"))
    except Exception as e:
        print("  %-26s -> ERROR %s: %s" % (model, type(e).__name__, str(e)[:220]))

async def main():
    for m in ["openai/gpt-oss-120b", "openai/gpt-4.1-mini"]:
        await run(m)

asyncio.run(main())
