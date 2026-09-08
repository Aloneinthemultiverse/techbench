"""Desktop control tools for the voice agent.

SAFETY: allowlist only. Speech recognition is lossy, so a misheard word must
never be able to run an arbitrary command. There is deliberately no free-form
shell tool here, and every action is cancellable and passes through the same
turn fence as any other tool result.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

# Allowlisted applications. Anything not in this map is refused, spoken aloud.
APPS: dict[str, list[str]] = {
    "claude code":   ["cmd", "/c", "start", "", "claude"],
    "vs code":       ["cmd", "/c", "start", "", "code"],
    "code":          ["cmd", "/c", "start", "", "code"],
    "notepad":       ["notepad.exe"],
    "calculator":    ["calc.exe"],
    "file explorer": ["explorer.exe"],
    "browser":       ["cmd", "/c", "start", "", "https://www.google.com"],
    "terminal":      ["cmd", "/c", "start", "", "powershell"],
}

PROJECT_ROOT = Path.home() / "voice-projects"

TEMPLATES: dict[str, dict[str, str]] = {
    "python": {
        "main.py": "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n",
        "requirements.txt": "",
    },
    "web": {
        "index.html": "<!doctype html>\n<title>{name}</title>\n<h1>{name}</h1>\n",
        "style.css": "body { font-family: system-ui; margin: 2rem; }\n",
    },
}


async def open_app(name: str) -> str:
    """Launch an allowlisted desktop application."""
    key = name.strip().lower()
    cmd = APPS.get(key)
    if cmd is None:
        return ("I can open " + ", ".join(sorted(APPS)) +
                ". I will not run anything outside that list.")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return "Opened " + key + "."


async def scaffold_project(kind: str, name: str) -> str:
    """Create a small project skeleton on disk. Real filesystem work."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", name)[:40] or "project"
    kind = kind.strip().lower()
    files = TEMPLATES.get(kind)
    if files is None:
        return "I can scaffold a python project or a web project."

    root = PROJECT_ROOT / safe

    def _write() -> None:
        root.mkdir(parents=True, exist_ok=True)
        for filename, body in files.items():
            (root / filename).write_text(body.replace("{name}", safe), encoding="utf-8")
        (root / "README.md").write_text("# " + safe + "\n", encoding="utf-8")

    await asyncio.to_thread(_write)
    return "Created a " + kind + " project called " + safe + "."


if __name__ == "__main__":
    print("allowlisted apps:", ", ".join(sorted(APPS)))
    print(asyncio.run(scaffold_project("python", "voice test 1")))
    print(asyncio.run(open_app("something dangerous"))[:90])
