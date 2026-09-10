"""Drive an Android phone by voice, via Google's ARTEMIS.

A technician with both hands inside a machine cannot pick up a phone. This
bridges a spoken instruction to ARTEMIS, which turns natural language into
Android automation over ADB, and speaks back what it found.

    "Open the manual app and search for HP-4412"
    "What's the battery level on the phone"

SAFETY BOUNDARY, same reasoning as delegate.py:
  * A phone is a device with someone's messages, banking and camera on it.
    Speech recognition is lossy, so this is scoped: tasks run through ARTEMIS's
    own agent, which is designed for UI automation, and the task text is passed
    through unchanged rather than being turned into shell.
  * A wall-clock timeout bounds the call; the child is killed on interruption
    so it cannot keep driving the phone for a turn that no longer exists.
  * The result is fenced like any other tool output.

REQUIRES: ARTEMIS installed and a device connected (`artemis doctor` all green).
If either is missing the agent says so in one sentence instead of hanging.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

ARTEMIS_DIR = Path(os.getenv("ARTEMIS_DIR", str(Path.home() / "artemis")))
TIMEOUT_S = float(os.getenv("ANDROID_TIMEOUT_SECONDS", "180"))
PROFILE = os.getenv("ARTEMIS_PROFILE", "flash")   # cheapest tier
SPOKEN_LIMIT = 320


def _python() -> str | None:
    """ARTEMIS's own interpreter, so we do not depend on uv being on PATH."""
    exe = ARTEMIS_DIR / ".venv" / "Scripts" / "python.exe"
    if exe.exists():
        return str(exe)
    exe = ARTEMIS_DIR / ".venv" / "bin" / "python"
    return str(exe) if exe.exists() else None


def _strip(text: str) -> str:
    """ARTEMIS prints boxed, coloured console output. Reduce it to prose the
    agent can speak: no ANSI, no box drawing, no repeated whitespace."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"[│┌┐└┘├┤┬┴┼─═║╔╗╚╝•●▪]", " ", text)
    return " ".join(text.split())


async def phone_task(task: str) -> str:
    """Run one spoken instruction on the connected phone. Returns speakable text."""
    python = _python()
    if python is None:
        return ("The phone automation tool is not installed on this machine, "
                "so I cannot drive the phone.")

    proc = await asyncio.create_subprocess_exec(
        python, "-m", "artemis", "run", task, "--profile", PROFILE,
        cwd=str(ARTEMIS_DIR),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "That took too long on the phone, so I stopped it."
    except asyncio.CancelledError:
        # The user interrupted. Kill the child so it stops driving the phone
        # for a turn that no longer exists.
        proc.kill()
        await proc.wait()
        raise

    blob = _strip(((out or b"") + b" " + (err or b"")).decode("utf-8", "replace"))
    low = blob.lower()

    if "no android device" in low or "none found" in low:
        return "No phone is connected, so I cannot run that."
    if "no llm key" in low or "llm providers" in low and "missing" in low:
        return "The phone automation tool has no model key configured."
    if proc.returncode != 0 and not blob:
        return "The phone task failed and returned nothing."

    # ARTEMIS ends with its answer; take the tail, which is the result rather
    # than the setup chatter.
    return blob[-SPOKEN_LIMIT:] if blob else "The phone task finished with no output."


if __name__ == "__main__":
    import sys, time
    t = " ".join(sys.argv[1:]) or "Tell me the battery level."
    t0 = time.perf_counter()
    print(asyncio.run(phone_task(t)))
    print("\nlatency: %.1f s" % (time.perf_counter() - t0))
