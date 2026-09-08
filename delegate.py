"""Delegate a spoken task to Claude Code.

The voice agent does not need its own general-purpose tool layer: Claude Code
already is an agent with file, shell and editor access. This bridges to it in
headless mode and returns a short spoken summary.

SAFETY BOUNDARY - deliberate, and documented in the README:
  * Claude Code runs with its DEFAULT permission model. Permissions are never
    bypassed from a voice command, because speech recognition is lossy and an
    unattended agent acting on a misheard instruction is not recoverable.
  * The working directory is pinned to a sandbox under the user's home.
  * A wall-clock timeout bounds the call; on timeout the process is killed and
    the turn is reported as failed rather than left hanging.
  * The result is fenced like any other tool output, so a task the user has
    already abandoned can never be spoken or written into conversation state.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

SANDBOX = Path.home() / "voice-workspace"

def _claude_exe() -> str:
    """npm installs a .cmd shim on Windows; the extensionless file is a shell
    script that CreateProcess cannot run."""
    import shutil
    from pathlib import Path as _P
    # Prefer the real binary. The npm .cmd shim breaks when the user's home
    # path contains spaces, so resolve past it.
    shim = shutil.which("claude.cmd") or shutil.which("claude")
    if shim:
        real = (_P(shim).parent / "node_modules" / "@anthropic-ai" /
                "claude-code" / "bin" / "claude.exe")
        if real.exists():
            return str(real)
    return shutil.which("claude.exe") or shim or "claude"

TIMEOUT_S = float(os.getenv("DELEGATE_TIMEOUT_SECONDS", "90"))

SPOKEN_LIMIT = 400  # keep spoken turns short; the brief asks for this


async def ask_claude(task: str) -> str:
    """Run a task through Claude Code headless and return a speakable summary."""
    SANDBOX.mkdir(parents=True, exist_ok=True)

    prompt = (
        "You are being driven by a voice assistant, so the user will HEAR your "
        "reply. Answer in at most three short sentences of plain prose. No "
        "markdown, no code blocks, no bullet lists, no file paths unless asked. "
        "Say what you did or found, not how you did it.\n\n"
        "Task: " + task
    )

    proc = await asyncio.create_subprocess_exec(
        _claude_exe(), "-p", prompt,
        cwd=str(SANDBOX),
        stdin=asyncio.subprocess.DEVNULL,   # -p reads stdin otherwise and stalls
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "That took too long, so I stopped it. Try a smaller task."
    except asyncio.CancelledError:
        # The user interrupted. Kill the child so it cannot keep working for a
        # turn that no longer exists.
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        blob = ((out or b"") + b" " + (err or b"")).decode("utf-8", "replace")
        low = blob.lower()
        if "authenticate" in low or "401" in low or "token" in low:
            return ("Claude Code is not signed in on this machine. "
                    "Run claude login in a terminal, then ask me again.")
        detail = [l for l in blob.strip().splitlines() if l.strip()]
        return "That task failed. " + (detail[-1][:120] if detail else "")

    text = (out or b"").decode("utf-8", "replace").strip()
    if not text:
        return "It finished but returned nothing to say."
    return text[:SPOKEN_LIMIT]


if __name__ == "__main__":
    import sys, time
    t = " ".join(sys.argv[1:]) or "In one sentence, what directory are you in?"
    t0 = time.perf_counter()
    print(asyncio.run(ask_claude(t)))
    print("\nlatency: %.1f s" % (time.perf_counter() - t0))
