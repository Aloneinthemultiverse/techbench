# Techbench — a voice agent that does not speak stale answers

A hands-busy field technician assistant. The technician's hands are inside a machine; the entire interface is speech. **Rime provides all spoken output.**

The hard voice problem it solves is not "can it be interrupted" — LiveKit gives that away for free. It is what happens to the work that was *already in flight* when the interruption arrived.

> **Claim.** Stopping playback is easy. Keeping application state consistent with what the user actually heard is not.

Full method, numbers and limitations: **[RIME_EVIDENCE.md](RIME_EVIDENCE.md)**.

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

## Results

| Condition | Stale results spoken |
|---|---|
| Fencing enabled | **0 / 20** |
| Fencing disabled | **20 / 20** |

Live session (536 events, 40 utterances, 12 interrupted):

| Metric | Median |
|---|---|
| End-of-utterance | 793 ms |
| Transcription (Whisper) | 396 ms |
| LLM TTFT | 908 ms |
| **Rime TTFB** | **357 ms** |
| Time to silence | 544 ms (n=5, noisy — see limitations) |

Barge-ins: 5. False interruptions correctly ignored: 2.

## Architecture

```
mic -> LiveKit (WebRTC, India South) -> ink-whisper (STT)
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

## Rime configuration

| Field | Value |
|---|---|
| Model | `coda` |
| Speaker | `lyra` |
| Language | `eng` |
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
| `cartesia/ink-whisper` | streaming speech-to-text | via LiveKit Inference |
| `openai/gpt-4.1-mini` | reasoning | via LiveKit Inference |
| DuckDuckGo HTML | live web search tool | no |

## What is live vs simulated

| Component | Status |
|---|---|
| Voice conversation, STT, LLM, Rime TTS | **live** |
| `search_web` | **live** — real network request, ~1.9 s |
| `lookup_part` | **synthetic** data, **injected** 3.0 s delay (the stress knob) |
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

- **The live session never exercised the fence** (`fence_drop` = 0). Barge-ins landed before results returned, so cancellation handled them. Proven by ablation and at logic level, not yet by a logged live drop.
- **Time-to-silence is noisy**, n=5, raw values `[544, 1, 1563, 10446]` ms plus one further 1 ms reading. Median reported; treat as exploratory.
- **Latency is geography-bound.** Rime resolves to AWS us-west-2 (Oregon); from India there is a ~270 ms RTT floor and no published APAC endpoint.
- **Do not set `sample_rate` on `rime.TTS`.** Forcing 24000 Hz crashes `livekit_ffi.dll`'s soxr resampler (assertion `FFT_LEN == -1`). The plugin default is the tested path.
- **If Rime is unavailable the agent is silent** — by design, since a fallback provider would violate the requirement that Rime be the primary output.
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
