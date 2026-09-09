# Controlled delivery — rendered A/B variants

The brief asks that delivery claims "hold the model and voice constant, render at
least two text variants, save the clips, and explain which wording or punctuation
changed the result."

**Held constant across every clip:** model `coda`, speaker `lyra`,
`speedAlpha 0.9`, endpoint `https://users.rime.ai/v1/rime-tts`, PCM/WAV.
**Only the input text changes.** Clips are committed in `eval/audio/delivery/`.

Duration is computed from the PCM payload, not the WAV header — Rime's streaming
response carries a placeholder frame count (`2147483647`), so `wave.getnframes()`
is meaningless here. That is itself worth knowing if you script against this API.

---

## 1. Part codes — no intervention needed

| Clip | Input text | What Rime speaks | Duration |
|---|---|---|---|
| `1a-code-plain` | `The part is HP-4412.` | "The part is **H-P, four four one two**." | 3.27 s |
| `1b-code-spaced` | `The part is H P, four four one two.` | "The part is H P, four four one two." | 4.34 s |

**Result: the hand-written variant is worse.** Rime's normalizer already expands
`HP-4412` correctly, and pre-spacing the code only adds **1.07 s (+33%)** of
speech for an identical rendering. A spoken-form map for part codes was written,
tested here, and **deleted from the agent**.

For a hands-busy technician a third of a second per code compounds across a call.
The shipped agent passes raw codes to Rime.

---

## 2. Punctuation controls chunking, and chunking costs time

| Clip | Input text | Duration |
|---|---|---|
| `2a-spec-runon` | `HP-4412 has 18 newton meters torque, viton seal, 200 celsius max.` | 10.47 s |
| `2b-spec-chunked` | `HP-4412. Torque, eighteen newton meters. Seal, viton. Maximum, two hundred celsius.` | 11.63 s |

**Result: chunking costs 1.16 s (+11%) and is worth it here.** Full stops between
fields give the listener a boundary per value. A technician with both hands
occupied is holding three numbers in their head; the run-on version delivers them
as one continuous phrase with no place to latch on.

This is a deliberate trade of latency for intelligibility, made because the
listener cannot re-read. The opposite trade would be correct for a screen.

---

## 3. Respelling an out-of-dictionary word

`check_dictionary` reports `viton`, `ptfe` and `vx` as out-of-dictionary.

| Clip | Input text | Duration |
|---|---|---|
| `3a-seal-plain` | `That one uses a viton seal.` | 2.48 s |
| `3b-seal-respell` | `That one uses a vye-tonn seal.` | 2.38 s |

**Result: respelling is free — 0.10 s shorter, not longer.** Out-of-dictionary
words still synthesize, but the pronunciation is not guaranteed, and a
mispronounced seal material means the technician fits the wrong part. Since the
cost is zero, the shipped agent respells via `tts_text_transforms`.

**Listen to both.** This is the one pair where the measurement cannot decide it
for you: duration is near-identical, and the question is whether the respelled
form is actually clearer to a listener who knows the material.

---

## 4. Fillers cost real time

| Clip | Input text | Duration |
|---|---|---|
| `4a-nofiller` | `Checking now.` | 1.41 s |
| `4b-filler` | `Okay, checking that now.` | 2.03 s |

**Result: the filler costs 0.62 s (+44%) and buys nothing.** On an
acknowledgement — the one utterance whose entire job is to be fast — that is the
worst place in the conversation to spend it. The agent's system prompt requires
one or two short sentences and no conversational padding.

---

## What this changed in the shipped product

1. **Removed** the spoken-form map for part codes. Measured as redundant and 33% slower.
2. **Kept** respelling for `viton` / `ptfe` / `vx`. Measured as free.
3. **Kept** short sentences and no fillers. Measured at 44% overhead on acknowledgements.
4. **Chunk specification readouts** with full stops between fields, accepting +11% duration for a boundary per value.

## Limitations

- Single renders, no repeats: Rime is deterministic enough for these comparisons
  but no variance is reported.
- Duration is a proxy for delivery cost, not for intelligibility. Only the
  listening comparison decides §3, and that judgement is one person's.
- All clips are English, `coda`/`lyra`. Nothing here transfers to the other
  languages or voices without re-rendering.

## Reproduce

Render clips: see the `render()` block in this project's history, or POST to
`https://users.rime.ai/v1/rime-tts` with `speaker=lyra`, `modelId=coda`,
`speedAlpha=0.9`. Normalization previews come from Rime's MCP `normalize_text`;
dictionary coverage from `check_dictionary` (see `pronunciation_check.md`).
