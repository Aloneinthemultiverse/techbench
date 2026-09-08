"""Hands-busy field technician assistant - Rime as primary spoken output.

Hard voice problem: interruption and recovery during in-flight tool work.
Claim: stopping playback is easy; keeping application state consistent with
what the user actually heard is not.

Rime config (recorded here and in README as the PS requires):
  model    : coda          (Rime flagship; alternatives mistv3, arcana)
  speaker  : lyra          (coda default; catalog pulled live from Rime MCP)
  language : eng
  format   : PCM           (livekit-plugins-rime always outputs PCM)
  transport: WebRTC via LiveKit Cloud
  provider : Rime, direct plugin with our own key (NOT LiveKit Inference)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    TurnHandlingOptions,
    cli,
    MetricsCollectedEvent,
    inference,
    metrics,
    room_io,
    text_transforms,
)
from livekit.agents.llm import function_tool
from livekit.plugins import openai, rime

from fence import EventLog, Fenced, SpokenLedger, TurnController
from delegate import ask_claude
from kb import KnowledgeBase, add_facts
from mail import draft_email
from pc import open_app, scaffold_project
from tools import speakable, web_search

load_dotenv()
logger = logging.getLogger("tech-assistant")

TOOL_DELAY = float(os.getenv("TOOL_DELAY_SECONDS", "3.0"))
RUN_DIR = Path("eval/runs")
KB = KnowledgeBase()   # business facts, loaded once at import

# Active speech provider, surfaced for observability (PS requires this).
ACTIVE_TTS_PROVIDER = "rime"

# Synthetic parts catalog - no real data (PS: use synthetic data).
# Pronunciation fixes, chosen from EVIDENCE, not guesswork.
#
# Rime's normalize_text already renders part codes correctly:
#   "HP-4412"  ->  "H-P, four four one two"     (no fix needed)
# But check_dictionary flags these as out-of-dictionary, and a mispronounced
# seal material makes the technician fit the wrong part:
#   viton, ptfe, vx
# See eval/pronunciation_check.md for the before/after transcript.
SPOKEN_FORMS = {
    "viton": "vye-tonn",
    "PTFE": "P T F E",
    "ptfe": "P T F E",
    "VX": "V X",
}

# Rime coda voice catalog, pulled live from Rime's MCP (never hardcoded guesses).
# Each entry is a (lang, speaker) pair verified to exist for model "coda".
LANGUAGES = {
    "english": ("eng", "lyra"),
    "hindi":   ("hin", "nadi"),
    "spanish": ("spa", "alba"),
    "french":  ("fra", "marielle"),
}

PARTS = {
    "hp-4412": {"torque_nm": 18, "seal": "viton", "temp_max_c": 200},
    "hp-4413": {"torque_nm": 22, "seal": "ptfe", "temp_max_c": 260},
    "vx-207":  {"torque_nm": 9,  "seal": "nitrile", "temp_max_c": 120},
}


class TechnicianAgent(Agent):
    def __init__(self, controller: TurnController, log: EventLog) -> None:
        super().__init__(
            instructions=(
                "You help a caller hands-free. One or two short sentences per "
                "reply. Digits spoken singly. No markdown, emoji or lists. "
                "Business questions: use answer_enquiry only, never memory. "
                "Email is drafted, never sent; read the address back. "
                "Only allowlisted apps open; say what is available otherwise. "
                "If the user revises mid-answer, answer only the new request "
                "and never mention the abandoned one. "
                "Before calling a slow tool, say one short line such as "
                "'Checking now.' so the caller knows you heard them."
            ),
        )
        self.controller = controller
        self.log = log

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Greet the technician in one short sentence and offer to look up a part."
        )

    @function_tool
    async def answer_enquiry(self, context: RunContext, question: str) -> str:
        """Answer any business question: hours, delivery, returns, warranty,
        payment, complaints. Required - never answer these from memory.

        Args:
            question: what the caller asked.
        """
        turn_id = self.controller.current
        if KB.maybe_reload():                 # documents added from the console
            self.log.emit("kb_reloaded", turn_id=turn_id, chunks=len(KB.chunks))
        answer, sources = KB.answer(question)
        self.log.emit("tool_return", turn_id=turn_id, tool="kb",
                      grounded=bool(sources), n_sources=len(sources))
        if not self.controller.accept(Fenced(turn_id, answer), what="kb"):
            return "(superseded - discarded)"
        return answer

    @function_tool
    async def compose_email(self, context: RunContext, to: str, subject: str,
                            body: str) -> str:
        """Draft a customer email for a human to send. Never sends.

        Args:
            to: recipient address.
            subject: subject line.
            body: full sentences.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, tool="email", subject=subject[:60])
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.
        spoken, record = await draft_email(to, subject, body)
        self.log.emit("tool_return", turn_id=turn_id, tool="email",
                      draft_id=record["id"],
                      address_needs_check=record["address_needs_check"])
        if not self.controller.accept(Fenced(turn_id, spoken), what="email"):
            return "(superseded - discarded)"
        return spoken

    @function_tool
    async def remember_fact(self, context: RunContext, topic: str, facts: str) -> str:
        """Save a new business fact for future callers.

        Args:
            topic: short heading.
            facts: the information, in full sentences.
        """
        turn_id = self.controller.current
        result = await asyncio.to_thread(add_facts, topic, facts)
        KB.__init__()                      # reload so the next caller sees it
        self.log.emit("kb_updated", turn_id=turn_id, topic=topic[:60],
                      chunks=len(KB.chunks))
        if not self.controller.accept(Fenced(turn_id, result), what="kb_write"):
            return "(superseded - discarded)"
        return result

    @function_tool
    async def delegate_task(self, context: RunContext, task: str) -> str:
        """Hand a coding or file task to Claude Code.

        Args:
            task: what to do.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, tool="delegate", task=task[:80])
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.
        try:
            result = await ask_claude(task)
        except asyncio.CancelledError:
            self.log.emit("tool_cancelled", turn_id=turn_id, tool="delegate")
            raise
        self.log.emit("tool_return", turn_id=turn_id, tool="delegate")
        if not self.controller.accept(Fenced(turn_id, result), what="delegate"):
            return "(superseded - discarded)"
        return result

    @function_tool
    async def open_application(self, context: RunContext, name: str) -> str:
        """Open a desktop application by name.

        Args:
            name: claude code, vs code, notepad, calculator, file explorer,
                  browser, or terminal.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, tool="open_app", target=name)
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.
        result = await open_app(name)
        self.log.emit("tool_return", turn_id=turn_id, tool="open_app")
        if not self.controller.accept(Fenced(turn_id, result), what="open_app"):
            return "(superseded - discarded)"
        return result

    @function_tool
    async def make_project(self, context: RunContext, kind: str, name: str) -> str:
        """Create a new project folder on disk.

        Args:
            kind: python or web.
            name: what to call the project.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, tool="scaffold", kind=kind, name=name)
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.
        result = await scaffold_project(kind, name)
        self.log.emit("tool_return", turn_id=turn_id, tool="scaffold")
        if not self.controller.accept(Fenced(turn_id, result), what="scaffold"):
            return "(superseded - discarded)"
        return result

    @function_tool
    async def switch_language(self, context: RunContext, language: str) -> str:
        """Switch spoken language.

        Args:
            language: english, hindi, spanish, or french.
        """
        key = language.strip().lower()
        if key not in LANGUAGES:
            return f"I can speak {', '.join(LANGUAGES)}. Which would you like?"

        lang, speaker = LANGUAGES[key]
        # Rime voices are language-specific: the speaker changes with the lang.
        self.session.tts.update_options(lang=lang, speaker=speaker)
        self.log.emit("language_switch", turn_id=self.controller.current,
                      lang=lang, speaker=speaker, provider=ACTIVE_TTS_PROVIDER)
        return f"Switched to {key}."

    @function_tool
    async def search_web(self, context: RunContext, query: str) -> str:
        """Search the live web for current information.

        Args:
            query: what to search for.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, tool="web_search", query=query)

        # CONTINUITY: speak first, keep listening while the search runs.
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.

        results = await web_search(query, k=3)
        self.log.emit("tool_return", turn_id=turn_id, tool="web_search", n=len(results))

        payload = speakable(results)
        # THE FENCE - identical treatment to every other tool.
        if not self.controller.accept(Fenced(turn_id, payload), what="web_search"):
            return "(superseded - discarded)"
        return payload

    @function_tool
    async def lookup_part(self, context: RunContext, part_number: str) -> str:
        """Look up torque, seal material, and max temperature for a part.

        Args:
            part_number: The part identifier, e.g. HP-4412.
        """
        turn_id = self.controller.current
        self.log.emit("tool_dispatch", turn_id=turn_id, part=part_number, delay_s=TOOL_DELAY)

        # CONTINUITY: acknowledge immediately so the session is audibly alive,
        # then keep listening while the lookup runs. The user can add a
        # constraint, ask for status, interrupt, or cancel during this window.
        # Continuity ack removed: a second concurrent TTS stream per tool call
        # crashed livekit_ffi soxr (LSX_FFT_BR == NULL). The LLM still
        # acknowledges verbally before the tool returns.

        # The stress knob: a fixed delay, so a barge-in lands mid-flight.
        await asyncio.sleep(TOOL_DELAY)

        spec = PARTS.get(part_number.lower().replace(" ", ""))
        payload = (
            f"{part_number}: torque {spec['torque_nm']} newton meters, "
            f"{spec['seal']} seal, max {spec['temp_max_c']} celsius."
            if spec else f"No record for {part_number}."
        )
        self.log.emit("tool_return", turn_id=turn_id, part=part_number)

        # THE FENCE. If the user has moved on, this result is dead.
        if not self.controller.accept(Fenced(turn_id, payload), what="tool_result"):
            return "(superseded - discarded)"
        return payload


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    log = EventLog(RUN_DIR / f"{ctx.room.name}.jsonl")
    controller = TurnController(log)
    ledger = SpokenLedger(log)
    log.emit("session_start", room=ctx.room.name, tts_provider=ACTIVE_TTS_PROVIDER,
             rime_model="coda", rime_speaker="lyra", tool_delay_s=TOOL_DELAY)

    session: AgentSession = AgentSession(
        # Back to nova-3: with ink-whisper no transcription arrived at all, and
        # its mic-side resampling sits on the same soxr path that was aborting
        # the process. nova-3 is the configuration that ran a full 1731-event
        # session. Whisper alternative, if revisiting:
        #   inference.STT("cartesia/ink-whisper")
        stt=inference.STT("deepgram/nova-3", language="en"),
        # Chosen by measurement, not reputation. TTFT from India, n=3 each
        # (eval/llm_latency.py): gpt-oss-120b 908ms, gpt-4.1-nano 1064ms,
        # gpt-4.1-mini 1134ms, gemini-3.1-flash-lite 1193ms, and the model
        # branded "fast" - grok-4-1-fast-non-reasoning - was 4647ms.
        llm=inference.LLM("openai/gpt-4.1-mini"),
        # Rime is the primary spoken output - direct plugin, our own key.
        # NOTE: do NOT pass sample_rate. Forcing 24000 crashes livekit_ffi's
        # soxr resampler (assertion FFT_LEN == -1 in fft4g_cache.h). Plugin
        # default (22050) is the tested path.
        # 48000 Hz is what WebRTC wants, so nothing is resampled and soxr is
        # never invoked. livekit_ffi's soxr FFT cache crashes when several TTS
        # streams create and destroy resamplers concurrently - which is what
        # the per-tool session.say() acks cause (LSX_FFT_BR == NULL,
        # fft4g_cache.h:13). Rime honours samplingRate=48000; verified against
        # the API directly, 139244 bytes vs 71046 at 22050 for the same text.
        # Do NOT set an intermediate rate such as 24000: that still resamples
        # and crashes differently (FFT_LEN == -1, line 15).
        tts=rime.TTS(model="coda", speaker="lyra", speed_alpha=0.9,
                     sample_rate=48000),
        # Blocks interruptions briefly after the agent starts speaking so the
        # client can calibrate acoustic echo cancellation. Without this the
        # agent hears its own voice and self-interrupts (the "radio" artifact).
        # 3.0 s felt unresponsive: interruptions are blocked for that whole
        # window while AEC calibrates. 1.5 s still calibrates on a headset.
        aec_warmup_duration=3.0,
        turn_handling=TurnHandlingOptions(
            interruption={
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.0,
            },
            # preemptive_generation is DISABLED deliberately. Enabling it
            # crashed livekit_ffi.dll's soxr resampler
            # (assertion LSX_FFT_BR == NULL, fft4g_cache.h:13): speculative
            # generations create and cancel TTS streams concurrently, and the
            # soxr FFT cache is not safe under that. Same component that
            # crashed on a forced sample_rate (FFT_LEN == -1, line 15).
            # Latency cost is real; a crashing demo costs more.
        ),
        tts_text_transforms=[
            "filter_emoji",
            "filter_markdown",
            # Force spoken forms for part codes even if the LLM emits the raw code.
            *[text_transforms.replace({code: spoken})
              for code, spoken in SPOKEN_FORMS.items()],
        ],
        # Bias STT toward our domain vocabulary (input-side precision).
        stt_context_options={"keyterms": [
            "HP-4412", "HP-4413", "VX-207", "viton", "PTFE", "nitrile",
            "torque", "newton meters", "seal", "celsius", "look up", "instead",
        ]},
    )

    # --- interruption wiring -------------------------------------------
    # TODO(verify against your installed livekit-agents): confirm the exact
    # event names and the field carrying truncated spoken text. Run
    #   python -c "import livekit.agents as a; print(a.__version__)"
    # and check the AgentSession events in the SDK reference. The fence and
    # ledger below are correct regardless; only the hook names may differ.

    # ---- latency: LiveKit measures the hops for us; we just record them ----
    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        kind = getattr(m, "type", "")
        if kind == "eou_metrics":
            log.emit("lat_eou", turn_id=controller.current,
                     end_of_utterance_delay=getattr(m, "end_of_utterance_delay", None),
                     transcription_delay=getattr(m, "transcription_delay", None))
        elif kind == "llm_metrics":
            log.emit("lat_llm", turn_id=controller.current,
                     ttft=getattr(m, "ttft", None))
        elif kind == "tts_metrics":
            log.emit("lat_tts", turn_id=controller.current,
                     ttfb=getattr(m, "ttfb", None), provider=ACTIVE_TTS_PROVIDER)
        metrics.log_metrics(m)

    @session.on("user_input_transcribed")
    def _on_user_turn(ev) -> None:
        if getattr(ev, "is_final", True):
            controller.new_turn(reason="user_speech")

    @session.on("speech_created")
    def _on_speech(ev) -> None:
        log.emit("tts_start", turn_id=controller.current)

    @session.on("overlapping_speech")
    def _on_overlap(ev) -> None:
        # User spoke while the agent was speaking: the barge-in moment.
        # time_to_silence is measured from here to the next agent_state=listening.
        log.emit("barge_in", turn_id=controller.current)

    @session.on("agent_false_interruption")
    def _on_false(ev) -> None:
        # Backchannel ("mhm"), not a real interruption - agent resumes.
        log.emit("false_interruption", turn_id=controller.current)

    @session.on("agent_state_changed")
    def _on_state(ev) -> None:
        state = getattr(ev, "new_state", None)
        log.emit("agent_state", state=str(state), turn_id=controller.current)
        if str(state) in ("listening", "AgentState.listening"):
            log.emit("tts_stop", turn_id=controller.current)

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = getattr(ev, "item", None)
        if item is not None and getattr(item, "role", None) == "assistant":
            spoken = getattr(item, "text_content", "") or ""
            interrupted = bool(getattr(item, "interrupted", False))
            ledger.record(intended=spoken, spoken=spoken, interrupted=interrupted)

    async def _summary() -> None:
        log.emit("session_end", dropped=controller.dropped, committed=controller.committed)
        log.close()

    ctx.add_shutdown_callback(_summary)

    await session.start(
        agent=TechnicianAgent(controller, log),
        room=ctx.room,
        room_options=room_io.RoomOptions(),
    )


if __name__ == "__main__":
    cli.run_app(server)
