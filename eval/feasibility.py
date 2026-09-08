from dotenv import load_dotenv; load_dotenv()
import inspect
from livekit.agents import AgentSession, TurnHandlingOptions, inference, text_transforms
from livekit.plugins import rime

ok=[];bad=[]
def t(name, fn):
    try: fn(); ok.append(name)
    except Exception as e: bad.append(f"{name}: {type(e).__name__}: {e}")

t("rime.TTS(coda/lyra/speed_alpha)", lambda: rime.TTS(model="coda", speaker="lyra", speed_alpha=0.9))
t("inference.STT(deepgram/nova-3)", lambda: inference.STT("deepgram/nova-3", language="multi"))
t("inference.LLM(gpt-4.1-mini)",    lambda: inference.LLM("openai/gpt-4.1-mini"))
t("TurnHandlingOptions(interruption)", lambda: TurnHandlingOptions(interruption={"resume_false_interruption":True,"false_interruption_timeout":1.0}))
t("text_transforms.replace",       lambda: text_transforms.replace({"viton":"vye-tonn"}))

print("--- component construction ---")
for o in ok: print("  OK  ", o)
for b in bad: print("  FAIL", b)

print("\n--- AgentSession kwargs ---")
sig=inspect.signature(AgentSession.__init__).parameters
for k in ["stt","llm","tts","turn_handling","tts_text_transforms","stt_context_options"]:
    print(f"  {'OK     ' if k in sig else 'MISSING'} {k}")

print("\n--- event names we hook ---")
try:
    import livekit.agents.voice.events as ev
    names=sorted(n for n in dir(ev) if n.endswith("Event"))
    print("  available:", ", ".join(names))
except Exception as e:
    print("  (could not enumerate:", e, ")")
