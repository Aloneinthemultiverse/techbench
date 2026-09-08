# Pronunciation check — evidence, not assumption

Method: Rime MCP (`mcp.rime.ai`) `normalize_text` and `check_dictionary`,
run against the exact strings this agent speaks. Model: coda. Speaker: lyra.

## normalize_text — part codes need no intervention

Input:  `HP-4412: torque 18 newton meters, viton seal, max 200 celsius.`
Output: `H-P, four four one two: torque eighteen newton meters, viton seal, max two hundred celsius.`

Finding: Rime's normalizer already expands the alphanumeric part code and the
numbers correctly. **A hand-written spoken-form map for part codes was removed
as redundant.**

## check_dictionary — the real risk is vocabulary, not codes

Input:  `viton ptfe nitrile torque newton celsius HP-4412 VX-207`
Output: 3 out-of-dictionary words — `viton`, `ptfe`, `vx`

Finding: seal materials, not part numbers, are the pronunciation risk. In this
domain a mispronounced seal material means the technician fits the wrong part,
so these are corrected via `tts_text_transforms`.

## Scope

Pronunciation is a separate hard-voice-problem path in the PS. It is used here
for product correctness and is **not** a claimed result: no acceptance test is
run for it. The claimed result is interruption/state consistency only.
