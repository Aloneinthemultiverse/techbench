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

## Results

Four providers, nine items, one cold plus two warm runs each, paced identically.
**Zero failures for any provider.**

### Latency (time-to-first-byte, ms)

| Provider | cold | warm p50 | warm min | warm max |
|---|---|---|---|---|
| Cartesia | 314 | **256** | 186 | 489 |
| Deepgram | 646 | 427 | 403 | 523 |
| **Rime** | 574 | **433** | 372 | 564 |
| Inworld | 613 | 497 | 448 | 646 |

Cartesia is fastest by a clear margin. Rime and Deepgram are level. Inworld is
slowest.

### Identifier survival

Whether the digits of a part code can be recovered, in order, from an
independent transcription.

| Provider | `HP-4412` | `VX-207 / VX-270` | `HP-4413` | Score |
|---|---|---|---|---|
| Inworld | pass | pass | pass | **3/3** |
| Rime | fail* | pass | pass | 2/3 |
| Deepgram | pass | fail | pass | 2/3 |
| Cartesia | fail | fail | fail | **0/3** |

**Cartesia is the fastest system and the least usable one for this product.** It
read `HP-4412` as "four four hundred and twelve", dropped a digit from `VX-207`
("two seven"), and rendered `HP-4413` as "four thousand four". For a listener who
must write the code down, speed does not compensate.

**Inworld was perfect on identifiers and slowest overall.** A clean trade at
both ends of the table.

### * The Rime failure did not reproduce

The single Rime failure on `HP-4412` was re-tested five times in isolation
(`eval/verify_pronunciation.py`): **5/5 pass**, every transcription reading
"h p four four one two".

**This is a limitation of the benchmark, not a finding about Rime.** One item
per provider per run is too thin to support a per-item verdict, and this table
should be read as indicative of gross differences - Cartesia's 0/3 is a pattern,
a single flip is not.

The same check also tested a hand-written spoken-form map as an alternative. It
was **worse**: on `HP-4413` the mapped form lost a digit ("four four one") and
ran 76% longer. The map stays out of the product. An earlier draft of this
project was about to reinstate it on the strength of that one failed sample.

### What this changed in the product

Nothing. Rime remains the shipped voice: Cartesia's speed advantage is
unusable at 0/3 on identifiers, Inworld's accuracy costs 64 ms at p50 and it is
the slowest system, and Deepgram matches Rime on both axes while being the same
vendor as the recogniser used to score fidelity.

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
