# RIME_EVIDENCE

## Hard voice claim

> Stopping playback when a user interrupts is easy. Keeping application state
> consistent with what the user actually heard is not. When a user barges in and
> revises the request while a tool call is in flight, the superseded result must
> never be spoken and must never enter conversation history.

Path chosen from the brief: **Interruption and recovery**, with **conversation
continuity during tool work** as the condition under which it is tested.

## Acceptance test, defined before the demo

A run PASSES if, across 20 interrupted turns:

1. `stale results spoken` == 0
2. the revised request is answered (correction handling == 20/20)
3. the answer names only the revised entity (entity tracking == 20/20)
4. playback stops on barge-in, with time-to-silence reported

Failure is defined concretely: the agent speaks, or commits to history, any
result produced for a turn the user has already superseded.

## Mechanism under test

Turn fencing (`fence.py`). Every user turn increments a monotonic `turn_id`.
Every async tool result is tagged with the turn that requested it. Before any
result is spoken or committed:

```python
if result.turn_id != self._turn_id:
    return False          # superseded - dropped, never spoken
```

A new turn also cancels the previous turn's tasks; the fence catches results
that win the race against cancellation.

## Procedure

Barge-in injected 3.0 s after the agent begins speaking, matching the protocol
used by Instruct-FD; tool delay fixed at 3.0 s so the interruption lands while
work is in flight. Trials split evenly across four interruption types
(follow-up, negation, repetition request, topic switch) following the HumDial
Track II taxonomy. Metric names follow Full-Duplex-Bench v2 (correction
handling, entity tracking). The criterion - state correctness after
interruption rather than audio timing alone - follows EchoChain.

Reproduce:

    .venv\Scripts\python.exe eval/run_bargein.py

## Result 1 - logic level, with ablation

Same harness, same 20 trials, one variable changed: the fence.

| Condition           | Stale results spoken |
|---------------------|----------------------|
| Fencing enabled     | **0 / 20**           |
| Fencing disabled    | **20 / 20**          |

Correction handling 20/20. Entity tracking 20/20. Zero leaks in every
interruption type (5 trials each).

The ablation is the point: without the fence, *every* interrupted turn leaks a
superseded result. The mechanism is load-bearing, not decorative.

## Result 2 - live audio session

One live session, 536 logged events, 40 spoken utterances, 12 of them
interrupted. Latency figures are LiveKit's own instrumentation, not our timers.

| Metric                       | Median  | n  |
|------------------------------|---------|----|
| End-of-utterance delay       | 793 ms  | 50 |
| Transcription (ink-whisper)  | 396 ms  | 50 |
| LLM TTFT (gpt-4.1-mini)      | 908 ms  | 51 |
| **Rime TTFB (coda/lyra)**    | **357 ms** | 53 |
| Time to silence on barge-in  | 544 ms (median of 5) | 5 |

Barge-ins detected: 5. False interruptions correctly ignored: 2 - the agent
resumed rather than yielding to a backchannel.

Reproduce:

    .venv\Scripts\python.exe eval/score_run.py eval/runs/techbench.jsonl

## Result 3 - pronunciation, evidence-driven

Checked with Rime's own `normalize_text` and `check_dictionary` before writing
any fix (full transcript in `eval/pronunciation_check.md`).

- Part codes need no intervention: `HP-4412` normalizes to
  "H-P, four four one two". A hand-written spoken-form map was written, tested,
  found redundant, and **removed**.
- The real risk is domain vocabulary: `viton`, `ptfe`, `vx` are
  out-of-dictionary. In this product a mispronounced seal material means the
  technician fits the wrong part, so these are corrected via
  `tts_text_transforms`.

Pronunciation is a separate path in the brief. It is used here for product
correctness and is **not** a claimed result; no acceptance test is run for it.

## Limitations - stated, not hidden

1. **The 20-trial result is logic level, not acoustic.** It drives the real
   `TurnController`, `Fenced` and `SpokenLedger` objects that `agent.py` uses,
   on a simulated timeline. It proves the fencing invariant. It does not
   measure acoustic time-to-silence.
2. **The live session did not exercise the fence.** `fence_drop` count is 0 in
   `techbench.jsonl`: in that session the barge-ins landed before tool results
   returned, so cancellation handled them and nothing reached the fence. The
   fence is proven at logic level and by ablation, not yet by a logged live
   drop. This is the single weakest point in the evidence.
3. **Time-to-silence sample is small and noisy.** Raw values, disclosed:
   `[544, 1, 1563, 10446]` ms plus one further 1 ms reading. The 1 ms values
   are artifacts of an agent state transition with no audio in flight; the
   10.4 s outlier is real and unexplained. Median reported; n = 5 is
   exploratory, not a performance claim.
4. **Latency is geography-bound.** DNS resolves `users.rime.ai` and
   `users-ws.rime.ai` to AWS us-west-2 (Boardman, Oregon). From India this
   imposes a ~270 ms RTT floor; measured one-shot HTTP TTFB was ~915 ms warm,
   of which ~547 ms was TCP+TLS. The shipped path holds a persistent WebSocket,
   which is why in-session TTFB is 357 ms. No India or APAC endpoint is
   published.
5. **Single operator, single machine, single network.** No cross-device or
   cross-network replication.
6. **Citations are secondary.** The four papers above were located via search
   and used for protocol and terminology. Claims attributed to them should be
   read as "protocol adapted from", not as reproduction of their results.

## Rime configuration under test

    model      coda
    speaker    lyra
    language   eng
    endpoint   wss://users-ws.rime.ai   (streaming; AWS us-west-2)
    audio      PCM, 22050 Hz, mono
    transport  WebRTC via LiveKit Cloud, India South
    integration livekit-plugins-rime 1.8.0, direct plugin with own API key
    controls   speed_alpha=0.9

Rime is the only speech provider in the judged flow. There is no TTS fallback;
if Rime fails the agent has no voice, and the active provider is displayed in
the UI at all times.

## References

- EchoChain: A Full-Duplex Benchmark for State-Update Reasoning Under
  Interruptions - arXiv:2604.16456
- Instruct-FD: Can Your Full-Duplex Speech System Follow Turn-Taking
  Instructions? - arXiv:2607.20460
- Full-Duplex-Bench v2 - arXiv:2510.07838
- ICASSP 2026 HumDial Challenge - arXiv:2601.05564
- Thinking Machines, "Interaction Models" - used as architectural contrast and
  as a turn-taking latency reference (0.40 s)
