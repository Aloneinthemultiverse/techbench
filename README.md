# Techbench — a voice agent that does not speak stale answers

A hands-busy field technician assistant. The technician's hands are inside a machine; the entire interface is speech. **Rime provides all spoken output.**

The hard voice problem it solves is not "can it be interrupted" — LiveKit gives that away for free. It is what happens to the work that was *already in flight* when the interruption arrived.

> **Claim.** Stopping playback is easy. Keeping application state consistent with what the user actually heard is not.

Full method, numbers and limitations: **[RIME_EVIDENCE.md](RIME_EVIDENCE.md)**.

## Why this is not a consumer assistant

A general assistant can already be interrupted. What it cannot do is show you
what happened to work that was already in flight — there is no event log, no
way to test whether a cancelled tool call re-entered conversation state, and no
way to audit what the user actually heard.

That inspectability is the point, and it is what the enterprise voice market
buys: contact centres, field operations, healthcare and public services need
behaviour that can be tested before deployment and audited afterwards, running
in infrastructure they control. This project is built for that shape of
problem — one narrow job, done deterministically, with an append-only record of
every turn, cancellation and dropped result.

## The failure being prevented

```
You:    "Search for Dragon Hatchling."
Agent:  starts searching (2s of real network work)
You:    (1s in) "No — search for Rime latency instead."
Agent:  audio stops. Looks correct.
        ...at 2s the first search returns anyway.
```

Without protection the agent now speaks the Dragon Hatchling result — a correct answer to a question you withdrew — and writes it into conversation history, so every later turn is built on a false record of what was said.

Measured: with fencing disabled this happens on **20 of 20** interrupted turns.

## The mechanism: turn fencing

Every user turn increments a monotonic `turn_id`. Every async result is tagged with the turn that requested it. Before anything is spoken or committed (`fence.py`):

```python
if result.turn_id != self._turn_id:
    return False          # superseded - dropped, never spoken
```

A new turn also cancels the previous turn's tasks. The fence catches results that win the race against cancellation. It is tool-agnostic: adding a tool requires no new thinking about interruption.

A second component, the **Spoken Ledger**, records what was *actually played* when Rime is cut off mid-sentence, not what was intended — so the model's memory matches the user's ears.

## Coverage of the brief's voice problems

One problem is **claimed and measured**. The others are implemented as product
quality and are reported, not claimed - no acceptance test is run for them.

| Voice problem | Status |
|---|---|
| **Interruption and recovery** | **CLAIMED + MEASURED** - turn fencing; 0/20 vs 20/20 ablation; live `fence_drop` logged |
| Conversation continuity during tool work | implemented - spoken ack before the delay, session stays live, user can revise or cancel mid-flight |
| Perceived response time | instrumented across all five hops (n=189); geography analysed, not optimised |
| Pronunciation and controlled delivery | evidence-driven - `normalize_text` / `check_dictionary`; `speed_alpha=0.9`; see `eval/pronunciation_check.md` |
| Multilingual and code-switched speech | implemented - `switch_language` tool; Rime `coda` in eng/hin/spa/fra with per-language speakers pulled from the live catalog; `ink-whisper` is multilingual on input if swapped in |
| Expressive and persistent voice identity | partial - one voice, one persona, consistent across turns |
| Evaluation and observability | built - append-only event log, live console, scorer, ablation harness |
| Telephony and adverse audio | **not attempted** - no SIP trunk. The brief is explicit that browser-microphone results do not prove telephone performance, so no claim is made. The architecture is transport-agnostic (LiveKit supports SIP), but that is an untested statement of design, not a result. |

## Results

| Condition | Stale results spoken |
|---|---|
| Fencing enabled | **0 / 20** |
| Fencing disabled | **20 / 20** |

Live session (1731 events, 133 utterances, 34 interrupted). **That session ran
with `cartesia/ink-whisper` as STT**; the shipped configuration now uses
`deepgram/nova-3`, because ink-whisper silently ignores `stt_context_options`
keyterms (it logs "keyterms are not supported by this STT"). Every other
component is unchanged, but the transcription figure below belongs to
ink-whisper, not to the shipped STT.

| Metric | Median |
|---|---|
| End-of-utterance | 948 ms |
| Transcription (STT) | 385 ms |
| LLM TTFT | 1143 ms (gpt-4.1-mini) |
| **Rime TTFB** | **369 ms** |
| Time to silence | 1053 ms (n=6, noisy — see limitations) |

Barge-ins: 6. False interruptions correctly ignored: 3.

**The fence fired live:** of 17 tool results, 16 committed and 1 dropped —
`fence_drop what=web_search result_turn=12 current_turn=13`. A search from a
superseded turn was killed before synthesis. Stale results spoken: **0**.

### Model choice by measurement

Voice agents live or die on time-to-first-token, so the LLM was chosen by
benchmark rather than reputation (`eval/llm_latency.py`, n=3 each, from India):

| Model | Median TTFT |
|---|---|
| `openai/gpt-oss-120b` (fastest measured) | **908 ms** |
| `openai/gpt-4.1-nano` | 1064 ms |
| **`openai/gpt-4.1-mini`** (shipped) | 1134 ms |
| `google/gemini-3.1-flash-lite` | 1193 ms |
| `xai/grok-4-1-fast-non-reasoning` | 4647 ms |

gpt-oss-120b measured fastest, but gpt-4.1-mini is what ships: it is the
configuration verified across the recorded 1731-event session, and stability
was preferred over a ~200 ms gain on submission day. The model branded "fast"
was five times slower than the fastest. Note these
figures include a ~500 ms India-to-US round trip, so they compress the real
differences between models and should not be read as provider benchmarks.

## Architecture

```
mic -> LiveKit (WebRTC, India South) -> nova-3 (STT)
                                          |
                                   TURN CONTROLLER  turn_id = N
                                          |
                        gpt-4.1-mini -> TOOL (tagged N)
                                          |
                                    >>> THE FENCE <<<
                                 N == current ?  speak : drop
                                          |
                        RIME coda/lyra -> LiveKit -> speaker
                                          |
                          SPOKEN LEDGER + EVENT LOG (JSONL)
                                          |
                               live UI  +  eval/score_run.py
```

One append-only JSONL log is the single source of truth. The browser tails it live over SSE; the scorer reads the same file afterwards. **The demo and the evidence come from identical data.**

## MCP server — plug the business layer into any AI

`mcp_server.py` exposes the same business layer over MCP, so a company can
connect it to Claude, Cursor or an internal tool without using the voice
interface at all. Voice and MCP are two front doors onto one state: a fact
added by voice is immediately visible to the MCP client, and vice versa.

    claude mcp add --transport stdio techbench -- python mcp_server.py

| Tool | Does |
|---|---|
| `kb_search` | ask the knowledge base; returns the answer **with source lines** |
| `kb_add` | teach it a fact; reloads retrieval immediately |
| `kb_stats` | what it knows and which file each chunk came from |
| `draft_email` | compose a customer email — **drafts only, never sends** |
| `list_drafts` | what is waiting for a human to send |
| `call_metrics` | latency, barge-ins and fence drops from a recorded session |

**Deliberately not exposed:** sending mail, running shell, launching
applications. An MCP client is another unattended caller, so the same safety
boundary applies as to the voice path.

`kb_search` returns `NOT IN KNOWLEDGE BASE` when the fact is absent, and the
server's MCP instructions tell the connecting model to escalate rather than
substitute its own knowledge — the grounding rule survives the hop to another AI.

No third-party dependency: raw JSON-RPC over stdio, reading stdin on a worker
thread because asyncio cannot attach to a stdin pipe on Windows.

## Rime configuration

| Field | Value |
|---|---|
| Model | `coda` |
| Speaker | `lyra` (per-language: `nadi`, `alba`, `marielle`) |
| Language | `eng` (switchable: `hin`, `spa`, `fra`) |
| Endpoint | `wss://users-ws.rime.ai` (streaming) |
| Audio format | PCM, 22050 Hz, mono |
| Transport | WebRTC via LiveKit Cloud (India South) |
| Integration | `livekit-plugins-rime` 1.8.0, direct plugin, own API key |
| Controls | `speed_alpha=0.9` |

**No TTS fallback.** Rime is the only speech provider in the judged flow; if it fails the agent has no voice. The active provider is displayed in the UI header at all times, as required.

## Third-party services

| Service | Role | Key required |
|---|---|---|
| **Rime** | text-to-speech (primary spoken output) | yes |
| LiveKit Cloud | WebRTC transport, VAD, turn detection, barge-in, AEC | yes |
| `deepgram/nova-3` (en) | streaming speech-to-text | via LiveKit Inference |
| `openai/gpt-4.1-mini` | reasoning | via LiveKit Inference |
| DuckDuckGo HTML | live web search tool | no |

### Business enquiries — grounded retrieval

`answer_enquiry` answers callers from a folder of plain-text business facts
(`kb/`) rather than from the model's memory: hours, delivery, returns,
warranty, payments, escalation.

Retrieval is deliberately simple — TF-IDF over sentence chunks, no embedding
service, no vector database. That keeps it **inspectable**: every spoken answer
traces to the exact source line that produced it, which is what a
compliance-shaped deployment needs.

**Keep the knowledge base clean.** Retrieval is TF-IDF, so a large unrelated
document dominates by sheer chunk count. During testing an unrelated 6 KB
review file was uploaded by mistake and contributed 50 of 83 chunks, which
started pulling answers from it. Only upload customer-facing business facts.

**Grounding rule:** below a score floor the agent says *"I do not have that in
our records, I can take a message"* and offers escalation. It does not guess. A
confident wrong answer about a refund policy is worse than no answer. Verified:
asked "what is the capital of France", it declines rather than answering.

Business data in `kb/business.md` is **synthetic** — no real company, customer
or record.

### Email — drafted by voice, sent by a human

`compose_email` writes a real `.eml` (plus JSON for the console) into `drafts/`,
addressed and ready. **It never sends.**

That is a deliberate design decision, not an unfinished feature. Speech
recognition is lossy — this project observed transcription errors during live
testing — and a sent email is irreversible: a misheard recipient, figure or
commitment cannot be recalled. The agent composes; the operator reviews on
screen and sends. The agent holds no mail credentials, so there is no path from
a misheard word to a delivered message. A spoken address that does not parse is
flagged `address_needs_check` and the agent says so out loud.

The honest route to autonomous send is a confirmation turn — read the recipient
and subject back, require an explicit spoken "send it", log both. That is a
behaviour change to be tested before it is claimed, not a transport change.

### Getting information into the knowledge base

Four routes, in order of how much you are adding:

0. **The web console** — an "Add knowledge" panel: paste a policy or price list,
   or upload a `.md` / `.txt`. Non-text uploads are refused. The panel shows the
   live fact count, and the running agent picks the document up on its next
   question via an mtime check — **no restart**. Verified: 29 to 33 facts across
   a pasted document and an uploaded file, both retrievable immediately.

1. **Bulk** — drop `.md` or `.txt` files into `kb/`. Sentences become chunks;
   `##` headings are treated as labels, not answers.
2. **By voice** — `remember_fact("Holiday hours", "We are closed on the twenty
   fifth of December.")`. Appends to `kb/learned.md` and reloads immediately,
   so the next caller gets the new answer. Verified: 27 chunks to 29, both new
   facts retrievable.
3. **Correction during a call** — same tool, used when the operator hears the
   agent get something wrong.

### Delegating to Claude Code

`delegate_task` hands a longer task to Claude Code headless. Verified working:
"create voicecheck7.txt containing 'it works'" produced the real file in ~11 s.

It is given an explicit tool **allowlist — Read, Write, Edit, Glob, Grep — and
never Bash.** Permissions are not blanket-bypassed: speech recognition is lossy,
and an unattended agent running arbitrary shell on a misheard instruction is
not recoverable. The call is sandboxed to `~/voice-workspace`, bounded by a
wall-clock timeout, killed on interruption, and fenced like any other result.

**Known failure mode:** the delegated agent can report confidently and be
wrong. In testing it once claimed a file existed when the directory was empty.
The bridge speaks its summary verbatim and does not verify it.

### Desktop control — safety

`open_application` uses a strict **allowlist** (`pc.py`). There is deliberately
no free-form shell tool: speech recognition is lossy, and a misheard word must
never be able to run an arbitrary command. Anything off the list is refused out
loud, naming what *is* available. `make_project` writes only under
`~/voice-projects/` with a sanitised name. Both are cancellable and pass
through the same turn fence as every other tool.

## What is live vs simulated

| Component | Status |
|---|---|
| Voice conversation, STT, LLM, Rime TTS | **live** |
| `search_web` | **live** — real network request, ~1.9 s |
| `lookup_part` | **synthetic** data, **injected** 3.0 s delay (the stress knob) |
| `open_application` / `make_project` | **live** — real processes launched, real files written |
| `switch_language` | **live** — changes Rime lang + speaker mid-session |
| `answer_enquiry` | **live** retrieval over **synthetic** business facts in `kb/` |
| `compose_email` | **live** — writes a real `.eml` to `drafts/`; **never sends** |
| `remember_fact` | **live** — appends to `kb/learned.md` and reloads retrieval |
| Console "Add knowledge" panel | **live** — writes to `kb/`, agent reloads on next question |
| Latency figures | **measured**, from LiveKit's own instrumentation |
| 20-trial barge-in result | **logic level** — real fence objects, simulated timeline |
| Live-session figures | **measured**, single session, small n |

Nothing in this repository is animated or scripted.

## Setup

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install "livekit-agents[rime,openai]~=1.6" python-dotenv
copy .env.example .env
```

`.env` needs `RIME_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`. Never commit it; `.gitignore` excludes it.

Run, in two terminals:

```
.venv\Scripts\python.exe agent.py dev
.venv\Scripts\python.exe server.py
```

Open the URL the server prints, click **Connect mic**. Use a headset — on laptop speakers the agent hears itself and self-interrupts.

Test protocol: **[TESTING.md](TESTING.md)**.

## Known limitations and failure behaviour

- **The live fence sample is n=1.** One logged live drop in 17 tool returns — the condition is rare, since most interruptions are handled by cancellation before a result reaches the fence. The 20-trial ablation proves the mechanism; the live drop proves it fires on the real audio path. n=1 is a demonstration, not a rate.
- **Time-to-silence is noisy**, n=5, raw values `[544, 1, 1563, 10446]` ms plus one further 1 ms reading. Median reported; treat as exploratory.
- **Latency is geography-bound.** Rime resolves to AWS us-west-2 (Oregon); from India there is a ~270 ms RTT floor and no published APAC endpoint.
- **Do not set `sample_rate` on `rime.TTS`.** Forcing 24000 Hz crashes `livekit_ffi.dll`'s soxr resampler (assertion `FFT_LEN == -1`). The plugin default is the tested path.
- **If Rime is unavailable the agent is silent** — by design, since a fallback provider would violate the requirement that Rime be the primary output.
- **The Spoken Ledger records but does not diff.** `truncated_chars_total` is always 0 because `intended` and `spoken` are passed the same string; the interrupted flag is real, the character-level truncation is not yet wired to playback position.
- Part data is synthetic. No real inventory system is contacted.

## Repository

```
agent.py      the voice agent: STT/LLM/TTS wiring, tools, event hooks
fence.py      TurnController, Fenced, SpokenLedger, EventLog
tools.py      live web search
server.py     LiveKit token minting, static serving, SSE event stream
web/          browser client + live metrics console
eval/
  run_bargein.py          20 trials + ablation (no microphone needed)
  score_run.py            scores a live audio session
  pronunciation_check.md  Rime normalize_text / check_dictionary evidence
  feasibility.py          SDK compatibility check
  runs/                   event logs and result JSON
  audio/                  sample Rime output
```

## Credits, licences and AI assistance

- Built on [LiveKit Agents](https://github.com/livekit/agents) (Apache-2.0).
- Speech synthesis by [Rime](https://rime.ai).
- Prior art and terminology from the papers listed in [RIME_EVIDENCE.md](RIME_EVIDENCE.md); those citations were located by search and used for protocol and vocabulary, not reproduced.
- **AI assistance:** this project was built with Claude Code. Architecture, scoping and code were produced in dialogue; the author reviewed, ran and is able to defend every component. The pronunciation map was written, tested against Rime's normalizer, found redundant, and removed — an example of the review process rather than acceptance of generated output.
