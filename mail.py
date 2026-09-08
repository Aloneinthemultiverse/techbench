"""Compose email by voice. Drafts only - a human sends.

DESIGN DECISION, deliberate and defended in the README:
  Speech recognition is lossy. This project has already observed transcription
  errors in live testing. An email sent on a business's behalf is irreversible:
  a misheard recipient, figure or commitment cannot be recalled. So the agent
  COMPOSES and the human SENDS.

Each draft is written to drafts/ as both .eml (openable in any mail client,
already addressed) and .json (for the UI). The operator reviews it on screen
and sends with one click. The agent never holds mail credentials, so there is
no path from a misheard word to a delivered message.

If you later want true autonomous send, the honest way is a confirmation turn:
read the recipient and subject back, require an explicit spoken "send it", and
log both the readback and the confirmation. That is a behaviour change, not a
transport change, and it should be tested before it is claimed.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from email.message import EmailMessage
from pathlib import Path

DRAFTS = Path(__file__).parent / "drafts"

# Where replies come from. Placeholder - a real deployment sets this per tenant.
FROM_ADDR = "service@example.invalid"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "draft"


def _looks_like_email(addr: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", addr.strip(), re.I))


async def draft_email(to: str, subject: str, body: str) -> tuple[str, dict]:
    """Write a draft to disk. Returns (spoken confirmation, draft record)."""
    to = to.strip()
    # A spoken address is very often mistranscribed. Keep the draft either way,
    # but flag it so the UI shows the operator what to check.
    needs_check = not _looks_like_email(to)

    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = FROM_ADDR
    msg["Subject"] = subject
    msg.set_content(body)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = stamp + "-" + _slug(subject)
    record = {
        "id": name,
        "to": to,
        "subject": subject,
        "body": body,
        "address_needs_check": needs_check,
        "status": "draft",
        "created": stamp,
    }

    def _write() -> None:
        DRAFTS.mkdir(parents=True, exist_ok=True)
        (DRAFTS / (name + ".eml")).write_text(msg.as_string(), encoding="utf-8")
        (DRAFTS / (name + ".json")).write_text(json.dumps(record, indent=2), encoding="utf-8")

    await asyncio.to_thread(_write)

    spoken = "I have drafted that to " + to + ", subject: " + subject + "."
    if needs_check:
        spoken += " I could not make out a valid address, so please check it on screen."
    spoken += " It is waiting for you to send."
    return spoken, record


def list_drafts(limit: int = 20) -> list[dict]:
    if not DRAFTS.exists():
        return []
    out = []
    for path in sorted(DRAFTS.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


if __name__ == "__main__":
    spoken, rec = asyncio.run(draft_email(
        "customer@example.com",
        "Your return request",
        "Thank you for calling. Unused parts can be returned within thirty days "
        "for a full refund. Please include your order number.",
    ))
    print(spoken)
    print("\nsaved:", rec["id"], "| needs address check:", rec["address_needs_check"])
    print("drafts on disk:", len(list_drafts()))
