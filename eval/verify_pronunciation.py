"""Does Rime's normalize_text preview match what Rime actually synthesizes?

The TTS comparison found Rime rendering HP-4412 as "four thousand four hundred
twelve", while Rime's own normalize_text tool reports it will say "H-P, four
four one two". If the preview and the synthesis disagree, then a pronunciation
map cannot be dismissed on the preview alone - which is how it was dismissed
earlier in this project.

Method: render both the raw code and a hand-written spoken form through the
same model and voice, transcribe each with an independent recogniser, and check
whether the digits survive.
"""
from __future__ import annotations

import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import inference
from livekit.agents.utils import http_context

from eval.tts_benchmark import identifier_ok, spoken_digits, transcribe

load_dotenv()

OUT = Path("eval/audio/verify")

CASES = [
    ("raw-code",    "The part is HP-4412.",                  "4412"),
    ("mapped-code", "The part is H P, four four one two.",   "4412"),
    ("raw-4413",    "HP-4413 needs a PTFE seal.",            "4413"),
    ("mapped-4413", "H P, four four one three needs a P T F E seal.", "4413"),
]


async def render(tts, text: str, dest: Path) -> float:
    frames = []
    async for ev in tts.synthesize(text):
        frames.append(ev.frame)
    sr, ch = frames[0].sample_rate, frames[0].num_channels
    pcm = b"".join(bytes(f.data) for f in frames)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm)
    return len(pcm) / (sr * ch * 2)


async def main() -> None:
    async with http_context.open():
        tts = inference.TTS("rime/coda")
        try:
            print("%-13s %6s  %-5s  %s" % ("case", "secs", "digits", "heard"))
            for name, text, want in CASES:
                dest = OUT / (name + ".wav")
                secs = await render(tts, text, dest)
                await asyncio.sleep(4)
                heard = await transcribe(dest)
                await asyncio.sleep(4)
                got = spoken_digits(heard)
                ok = "PASS" if want in got else "FAIL"
                print("%-13s %6.2f  %-5s  %r" % (name, secs, ok, heard[:56]))
        finally:
            close = getattr(tts, "aclose", None)
            if close:
                try:
                    await close()
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
