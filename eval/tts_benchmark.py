"""TTS comparison: Rime against three alternatives, for one defined use case.

USE CASE
    Spoken output for a hands-busy technician assistant. The listener cannot
    look at a screen and cannot re-read, so the qualities that matter are:
    does it say the identifier correctly, how fast does the first audio arrive,
    and does it fail.

FAIRNESS
    Every provider is reached through the same LiveKit Inference gateway, from
    the same machine, on the same network, in the same session. That controls
    the network path - a comparison across each vendor's own endpoint would
    confound provider latency with geography, which from India is the dominant
    term (see README).

    Voice selection: each provider's own default voice is used. No voice was
    auditioned and picked to favour any provider, including Rime.

WHAT IS MEASURED HERE, AND WHAT IS NOT
    measured   time-to-first-byte, total synthesis time, audio duration,
               reliability over repeated runs, cold vs warm, and text fidelity
               via an independent STT round-trip (word error rate).
    NOT measured  listening quality. That needs human raters and blinding.
               This script emits blinded clips and a sealed manifest so that
               test can be run properly; it does not score it.
    NOT measured  controllability beyond what is documented in
               tts_benchmark.md - the providers expose different control
               surfaces and a single number would misrepresent them.

    Small samples. Findings are exploratory.

Run:
    python eval/tts_benchmark.py            # full run, writes eval/bench/
    python eval/tts_benchmark.py --quick    # 1 repeat, for a smoke test
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import inference
from livekit.agents.utils import http_context

load_dotenv()

OUT = Path("eval/bench")
CLIPS = OUT / "clips"
BLIND = OUT / "blind"

# Rime plus three alternatives. Each provider's own default voice.
PROVIDERS = [
    ("rime/coda",                "Rime"),
    ("cartesia/sonic-3",         "Cartesia"),
    ("deepgram/aura-2",          "Deepgram"),
    ("inworld/inworld-tts-1.5",  "Inworld"),
]

# The corpus is the product's real vocabulary: identifiers, quantities, units
# and out-of-dictionary domain words. Two general sentences are included as a
# control, so a provider that is simply better at plain English is visible.
CORPUS = [
    ("id-1",   "The part is HP-4412."),
    ("id-2",   "Order VX-207, not VX-270."),
    ("num-1",  "Torque to eighteen newton meters."),
    ("num-2",  "Maximum temperature is two hundred degrees celsius."),
    ("oov-1",  "That one uses a viton seal."),
    ("oov-2",  "The PTFE seal is rated higher."),
    ("mix-1",  "HP-4413 takes twenty two newton meters and a PTFE seal."),
    ("gen-1",  "I do not have that in our records."),
    ("gen-2",  "I can take a message and have someone call you back."),
]

REPEATS = 3          # warm runs after the first cold run, per provider per item
PACE_S = float(os.getenv("BENCH_PACE_SECONDS", "2.5"))
# The gateway rate-limits (429) under a tight loop. Pacing keeps every provider
# on equal footing - each is measured under the same request cadence - and the
# retry counts are recorded as the reliability signal rather than hidden.


def wav_seconds(path: Path) -> float:
    """Duration from the PCM payload. Rime's streaming header carries a
    placeholder frame count, so getnframes() cannot be trusted."""
    try:
        with wave.open(str(path)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        return max(path.stat().st_size - 44, 0) / (sr * ch * sw)
    except Exception:
        return 0.0


_NUMWORD = {"zero":"0","oh":"0","one":"1","two":"2","three":"3","four":"4",
            "five":"5","six":"6","seven":"7","eight":"8","nine":"9"}
_TEENS = {"ten":"10","eleven":"11","twelve":"12","thirteen":"13","fourteen":"14",
          "fifteen":"15","sixteen":"16","seventeen":"17","eighteen":"18","nineteen":"19",
          "twenty":"20","thirty":"30","forty":"40","fifty":"50","hundred":"100",
          "thousand":"1000"}


def spoken_digits(text: str) -> str:
    """Digits a listener would write down, in order.

    A part code is only useful if the listener can transcribe it. This maps a
    transcript to the digit string it conveys: "four four one two" -> "4412",
    and "four thousand four hundred and twelve" -> "410004100 12", which does
    NOT match - correctly, because a technician hearing that cannot write the
    code down without doing arithmetic.
    """
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w.isdigit():
            out.append(w)
        elif w in _NUMWORD:
            out.append(_NUMWORD[w])
        elif w in _TEENS:
            out.append(_TEENS[w])
    return "".join(out)


def identifier_ok(reference: str, heard: str) -> bool | None:
    """Did the identifier survive the round trip?

    Returns None when the reference contains no identifier, so general
    sentences do not count towards the score.
    """
    codes = re.findall(r"[A-Z]{2}-?\d{3,}", reference)
    if not codes:
        return None
    want = "".join(re.findall(r"\d", " ".join(codes)))
    return want in spoken_digits(heard)


def letters_ok(reference: str, heard: str) -> bool | None:
    """Did the alphabetic prefix of the identifier survive? "HP" may be spoken
    as "h p" or "hp"; both are fine, "aitch pee" is also fine."""
    codes = re.findall(r"([A-Z]{2})-?\d{3,}", reference)
    if not codes:
        return None
    h = re.sub(r"[^a-z]", "", heard.lower())
    return all(c.lower() in h for c in codes)


async def synth(model: str, text: str, dest: Path) -> dict:
    """One synthesis. Returns timing, or an error record."""
    t0 = time.perf_counter()
    first = None
    frames: list[rtc.AudioFrame] = []
    try:
        tts = inference.TTS(model)
        stream = tts.synthesize(text)
        async for ev in stream:
            if first is None:
                first = (time.perf_counter() - t0) * 1000
            frames.append(ev.frame)
        total = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:120]}

    if not frames:
        return {"ok": False, "error": "no audio returned"}

    sr, ch = frames[0].sample_rate, frames[0].num_channels
    pcm = b"".join(bytes(f.data) for f in frames)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm)
    return {"ok": True, "ttfb_ms": round(first or 0, 1), "total_ms": round(total, 1),
            "sample_rate": sr, "seconds": round(len(pcm) / (sr * ch * 2), 2)}


async def transcribe(path: Path) -> str:
    """Independent STT round-trip. Deepgram nova-3 is used for every provider,
    including Deepgram's own TTS - noted as a possible bias in the write-up."""
    try:
        with wave.open(str(path)) as w:
            sr, ch = w.getframerate(), w.getnchannels()
            data = w.readframes(w.getnframes())
        stt = inference.STT("deepgram/nova-3", language="en")
        stream = stt.stream()
        out: list[str] = []

        interim: list[str] = []

        async def read():
            async for ev in stream:
                t = " ".join(a.text for a in ev.alternatives).strip()
                if not t:
                    continue
                if "FINAL" in str(ev.type).upper():
                    out.append(t)
                else:
                    interim.append(t)

        task = asyncio.create_task(read())
        chunk = int(sr * 0.02) * ch * 2
        for i in range(0, len(data), chunk):
            block = data[i:i + chunk]
            stream.push_frame(rtc.AudioFrame(
                data=block, sample_rate=sr, num_channels=ch,
                samples_per_channel=len(block) // (2 * ch)))
            await asyncio.sleep(0.004)
        # Short clips end before the recogniser decides the turn is over, which
        # truncated transcripts and inflated WER. Feed trailing silence so the
        # endpointer fires on real content rather than on the stream closing.
        silence = bytes(chunk)
        for _ in range(40):                      # ~0.8s
            stream.push_frame(rtc.AudioFrame(
                data=silence, sample_rate=sr, num_channels=ch,
                samples_per_channel=len(silence) // (2 * ch)))
            await asyncio.sleep(0.004)
        stream.end_input()
        try:
            await asyncio.wait_for(task, timeout=25)
        except asyncio.TimeoutError:
            pass
        finally:
            await stream.aclose()
        # Fall back to the longest interim if no final arrived, rather than
        # reporting an empty transcript as a fidelity failure.
        if out:
            return " ".join(out)
        return max(interim, key=len) if interim else ""
    except Exception as exc:
        return "<stt failed: " + type(exc).__name__ + ">"


async def main() -> None:
    quick = "--quick" in sys.argv
    repeats = 1 if quick else REPEATS
    corpus = CORPUS[:3] if quick else CORPUS

    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    async with http_context.open():
        for model, label in PROVIDERS:
            print("\n=== %s (%s) ===" % (label, model))
            for item_id, text in corpus:
                # Cold run: first call to this provider for this item.
                for run in range(repeats + 1):
                    warm = run > 0
                    dest = CLIPS / ("%s_%s_%d.wav" % (label.lower(), item_id, run))
                    res = await synth(model, text, dest)
                    await asyncio.sleep(PACE_S)
                    row = {"provider": label, "model": model, "item": item_id,
                           "text": text, "run": run, "warm": warm, **res}
                    if res.get("ok"):
                        print("  %-8s %-6s %-5s ttfb=%6.0fms total=%6.0fms  %.2fs audio"
                              % (item_id, "warm" if warm else "cold", "", res["ttfb_ms"],
                                 res["total_ms"], res["seconds"]))
                    else:
                        print("  %-8s FAILED  %s" % (item_id, res.get("error")))
                    rows.append(row)

        # Text fidelity: transcribe one warm clip per provider per item.
        print("\n=== text fidelity (STT round-trip, deepgram/nova-3) ===")
        for model, label in PROVIDERS:
            for item_id, text in corpus:
                clip = CLIPS / ("%s_%s_1.wav" % (label.lower(), item_id))
                if not clip.exists():
                    continue
                heard = await transcribe(clip)
                await asyncio.sleep(PACE_S)
                ok_id, ok_ltr = identifier_ok(text, heard), letters_ok(text, heard)
                for r in rows:
                    if r["provider"] == label and r["item"] == item_id and r["run"] == 1:
                        r["heard"] = heard
                        r["identifier_ok"] = ok_id
                        r["letters_ok"] = ok_ltr
                verdict = "n/a" if ok_id is None else ("PASS" if ok_id else "FAIL")
                print("  %-8s %-8s id=%-4s  heard=%r" % (label, item_id, verdict, heard[:56]))

    (OUT / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    # Blinded copies for a listening test: identities live only in the manifest.
    BLIND.mkdir(parents=True, exist_ok=True)
    manifest = {}
    picks = [r for r in rows if r.get("ok") and r["run"] == 1]
    random.Random(7).shuffle(picks)
    for n, r in enumerate(picks, 1):
        src = CLIPS / ("%s_%s_1.wav" % (r["provider"].lower(), r["item"]))
        if src.exists():
            tag = "clip_%03d.wav" % n
            (BLIND / tag).write_bytes(src.read_bytes())
            manifest[tag] = {"provider": r["provider"], "item": r["item"], "text": r["text"]}
    (OUT / "blind_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Summary
    print("\n" + "=" * 62)
    print("%-10s %8s %8s %8s %7s %6s" % ("provider", "ttfb_p50", "ttfb_cold", "audio_s", "id_ok", "fails"))
    for _, label in PROVIDERS:
        got = [r for r in rows if r["provider"] == label]
        warm = sorted(r["ttfb_ms"] for r in got if r.get("ok") and r["warm"])
        cold = [r["ttfb_ms"] for r in got if r.get("ok") and not r["warm"]]
        secs = [r["seconds"] for r in got if r.get("ok") and r["warm"]]
        ids = [r["identifier_ok"] for r in got if r.get("identifier_ok") is not None]
        fails = sum(1 for r in got if not r.get("ok"))
        print("%-10s %8s %8s %8s %7s %6d" % (
            label,
            ("%.0f" % warm[len(warm)//2]) if warm else "-",
            ("%.0f" % (sum(cold)/len(cold))) if cold else "-",
            ("%.2f" % (sum(secs)/len(secs))) if secs else "-",
            ("%d/%d" % (sum(ids), len(ids))) if ids else "-",
            fails))
    print("\nwrote %s, %s, and %d blinded clips" % (OUT / "results.json", OUT / "blind_manifest.json", len(manifest)))


if __name__ == "__main__":
    asyncio.run(main())
