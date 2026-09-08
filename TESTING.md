# How to test

## 0. Once, before anything

Two terminals, both in this folder.

    Terminal A:  .venv\Scripts\python.exe agent.py dev
    Terminal B:  .venv\Scripts\python.exe server.py

Wait for Terminal A to print `registered worker`. Then open http://localhost:8080
and click **Connect mic**. The header pill must read `connected`.

Use a HEADSET. Laptop speakers feed the agent's own voice back into the mic and
every utterance looks like a barge-in.

---

## Test 1 — Does it talk at all?  (smoke)

Say:  "Hello."

PASS if you hear a spoken reply in Rime's voice.
Check the event log for: `tts_start`, then `agent_state state=listening`.

If nothing is heard, stop here and check Terminal A for errors.

---

## Test 2 — Continuity during tool work

Say:  "Look up HP-4412."

Expected, in order:
  1. You hear "Checking HP-4412 now." within ~1s      <- the continuity ack
  2. A 3 second gap (the injected tool delay)
  3. You hear the torque/seal/temperature answer

Event log should show: `tool_dispatch` -> (3s) -> `tool_return` -> `commit`.

PASS if the agent acknowledges BEFORE the delay, not after.
This is the "session stays responsive during lookups" requirement.

---

## Test 3 — THE CLAIM. Barge-in with revision

Say:  "Look up HP-4412."
Then, while it is still speaking or during the 3s gap, interrupt:
      "No, VX-207 instead."

Watch the metrics panel:
  stale results spoken   MUST STAY 0        <- the whole claim
  stale results fenced   should go to 1
  barge-ins              should go to 1
  time to silence        should show a number in ms

Event log should show:
  barge_in -> turn_start (superseded=N) -> tool_cancelled  and/or  fence_drop

PASS if:
  - audio stops promptly when you interrupt
  - the agent NEVER speaks the HP-4412 answer
  - the final answer is about VX-207 only

FAIL (and this is the bug the project exists to prevent) if the agent says
anything about HP-4412 after you switched.

---

## Test 4 — False interruption (backchannel)

While the agent is speaking, say a short "mhm" or "uh huh" and stop.

PASS if the agent CONTINUES speaking and the log shows `false_interruption`.
That is the semantic distinction between a real barge-in and a backchannel.

---

## Test 5 — The four interruption types  (HumDial Track II)

Repeat Test 3 five times for each of these interruptions, 20 runs total:

  follow_up           "wait, what's the seal material?"
  negation            "no, not that one"
  repetition_request  "say that again"
  topic_switch        "actually, VX-207"

After each run, note whether "stale results spoken" stayed at 0.

---

## Test 6 — Pronunciation

Say:  "Look up HP-4413."

Listen: does it say "H-P four four one three" (correct) or "hip 4413" (wrong)?
Listen: is "PTFE" spoken as letters, and "viton" intelligible?

Evidence for these fixes is already in eval/pronunciation_check.md.

---

## After the session: score it

    .venv\Scripts\python.exe eval/score_run.py eval/runs/<room>.jsonl

`<room>` will be `techbench` when driven from the web app.

Report from that output:
  time_to_silence_median_ms
  stale_results_dropped
  stale_results_spoken        <- must be 0
  interrupted_utterances
  truncated_chars_total

---

## Logic-level test (no microphone, reruns in 1 second)

    .venv\Scripts\python.exe eval/run_bargein.py

Already passing: 0/20 leaks with fencing, 20/20 leaks without.
This proves the mechanism. The audio tests above prove it survives real speech.

---

## If something breaks

  no audio            -> check Terminal A for a Rime auth error; verify RIME_API_KEY
  agent never joins   -> Terminal A must say `registered worker`; check LIVEKIT_URL
  everything is a     -> you are on laptop speakers. Use a headset.
    barge-in
  no events in the UI -> the agent writes eval/runs/<room>.jsonl only once a
                         session starts; connect the mic first
