# TTS comparison — Rime against three alternatives

Run it yourself: `python eval/tts_benchmark.py` (writes `eval/bench/`).
Smoke test: `python eval/tts_benchmark.py --quick`.

## The use case being tested

Spoken output for a hands-busy technician assistant. The listener has both
hands inside a machine: they cannot look at a screen, cannot re-read, and often
need to **write down or act on an identifier** they only hear once.

That fixes what matters. A pleasant voice that says `HP-4412` as *"four
thousand four hundred and twelve"* is worse for this product than a plainer
voice that says *"four four one two"*, because the technician cannot transcribe
the first one without doing arithmetic. This benchmark is scoped to that use
case and does not generalise to audiobooks, characters, or long-form narration.

## Systems compared

| Provider | Model | Voice |
|---|---|---|
| **Rime** | `rime/coda` | provider default |
| Cartesia | `cartesia/sonic-3` | provider default |
| Deepgram | `deepgram/aura-2` | provider default |
| Inworld | `inworld/inworld-tts-1.5` | provider default |

**Voice selection:** each provider's own default. No voice was auditioned and
chosen to favour anyone, including Rime. Picking a favourable voice per provider
is the most common way a TTS comparison becomes an advertisement.

## Fairness controls

- **One network path.** Every provider is reached through the same LiveKit
  Inference gateway, from the same machine, same session. Comparing each
  vendor's own endpoint would confound provider latency with geography — and
  from India geography is the dominant term (~270 ms floor; see the README).
  The trade: these are gateway-mediated figures, not each vendor's best-case
  direct latency.
- **Same request cadence.** The gateway rate-limits under a tight loop, so all
  providers are paced identically (`BENCH_PACE_SECONDS`, default 2.5 s). No
  provider is measured under a burst another was not.
- **Cold and warm reported separately.** The first call per provider per item is
  cold; subsequent calls are warm. Mixing them hides connection-setup cost.
- **Identical corpus** for every provider, run in the same order.

## Corpus

Nine items: four identifier/number items, two out-of-dictionary domain words
(`viton`, `PTFE`), one mixed sentence, and **two general English sentences as a
control** — so a provider that is simply better at plain English is visible and
is not credited to domain handling. Full corpus is in `tts_benchmark.py`.

## Metrics — and what each one is not

### Latency (measured)

Time-to-first-byte and total synthesis time, in milliseconds, cold and warm
separately. **This is model latency plus gateway latency**, not model latency
alone; no provider is advantaged since the gateway is common.

### Text fidelity (measured)

An independent STT round-trip: synthesize, transcribe with `deepgram/nova-3`,
then ask **did the identifier survive?** — are the code's digits recoverable, in
order, from what was heard.

Word error rate was tried first and **abandoned**: it scored *"h p four four one
two"* as a failure against `HP-4412` purely on tokenisation, which measures the
comparison script rather than the TTS. Identifier survival is the property the
product actually needs. General sentences return `n/a` and do not count.

**Known bias, stated:** the recogniser is Deepgram's, and one of the systems
under test is Deepgram's TTS. Any same-vendor advantage would flatter Deepgram,
not Rime. A second recogniser would be the fix and has not been run.

### Reliability (measured)

Failures and retries per provider across the run.

### Listening quality (NOT scored here)

This needs human raters and blinded playback. The script emits blinded clips to
`eval/bench/blind/` with identities held only in `eval/bench/blind_manifest.json`,
so the test can be run properly by someone else. **No listening score is
reported, and none should be inferred from the latency or fidelity numbers.**

### Controllability (documented, not scored)

The providers expose different control surfaces — Rime offers `speed_alpha` and
a pronunciation dictionary; others expose different parameters. Collapsing that
into one number would misrepresent all of them. See each provider's docs.

## Preliminary observation

From a two-provider smoke run (Rime and Cartesia, two identifier items — **too
small to be a result**), one difference is worth recording because it is
qualitative rather than statistical:

| Provider | `HP-4412` rendered as | Identifier recoverable? |
|---|---|---|
| **Rime** | "h p four four one two" | **yes** |
| Cartesia | "h p four thousand four hundred and twelve" | no |

Cartesia read the code as a cardinal number. For this use case that is a
correctness failure, not a style difference. Rime was also slower on that same
smoke run (ttfb p50 1209 ms vs 876 ms), so this is a genuine trade-off rather
than a clean win, and it is exactly the sort of thing a single score would hide.

**This is an observation from n=2 items on two providers. It is not a finding.**
Run the full script for item-level results across all four providers.

## Outputs

```
eval/bench/results.json        item-level results, every run, including failures
eval/bench/clips/              every generated clip, named by provider and item
eval/bench/blind/              the same clips, anonymised for a listening test
eval/bench/blind_manifest.json the key to the blinded set
eval/tts_benchmark.py          the analysis code
```

## Limitations

- Small samples. Everything here is exploratory and labelled as such.
- Gateway-mediated latency, not direct-endpoint latency.
- One recogniser, from one of the vendors under test.
- Default voices only; a tuned voice per provider would change listening
  quality and possibly fidelity.
- Single machine, single network, single region, one day.
- No listening test has been conducted — only prepared.
- The point of this comparison is to characterise trade-offs for one narrow use
  case. It is not evidence that any provider is better in general, and it is not
  intended to show that Rime wins.
