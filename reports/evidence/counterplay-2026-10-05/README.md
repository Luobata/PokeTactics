# Counterplay acceptance evidence — 2026-10-05

## Source and reproducibility

- Git head: `d3a26ce6dee44074d9087ea5cee6b2a35fd236a4` (production `sim/` changes were concurrently present but uncommitted).
- Rules fingerprint over `sim/*.py` plus `data/*.json`: `2a469a66cce17970c78393f495305f55cb52c6a92e2264a164e6861095ac5fbb`.
- Formal probe SHA-256 (v2): `6acff4d4ac637e1bf7a923e097036dfd08c092ae21d40cdcc1e2fd46eb106082`. This script produced the four formal/exploration JSON files and is archived verbatim as `counterplay_probe.formal-v2.py`.
- Current diagnostic probe SHA-256 (v3): `d69b5a44a178cc607ac33666ec1b496471c61d8faedafecb0462fb7c93faa477`. Its phase metadata now records the supplied phase argument, and the identity diagnostic was rerun on the same 100 seeds. It produced only `identity-replay-check.json`; the earlier formal JSON files were not rewritten or claimed to have run under it.
- Current exact script copy: `counterplay_probe.py` in this directory.
- Phase I ruleset: `tactics_v2`; Phase II ruleset: `tactics_v3`.
- Formal seeds: `2026100550000..2026100550099` (100 independent trials per arm/opponent; each trial also side-swapped only for verification).
- Every recorded run, including the new identity diagnostic, reports `source_stable_during_run: true`.

## Files

| File | Purpose | Games incl. swaps | Swap failures |
|---|---|---:|---:|
| `formation-explore.json` | 20-seed pre-selection ladder, all arms/opponents | 1,000 | 20 |
| `formation-recheck.json` | Deterministic replay of frozen active-guard arm on exploration seeds | 200 | 0 |
| `phase1-formal.json` | Held-out 100-seed current-mechanism ladder | 5,000 | 100 |
| `phase2-formal.json` | Held-out 100-seed healing-needle comparison | 1,800 | 0 |
| `identity-replay-check.json` | Correct equal-loadout replay/fair-coin diagnostic under current probe v3 | 200 | 0 hard replay mismatches |
| `counterplay_probe.formal-v2.py` | Exact script copy that produced the formal/exploration JSON files | n/a | n/a |
| `counterplay_probe.py` | Current v3 script copy that produced the identity diagnostic | n/a | n/a |
| `phase2-archive-seal-*` | Main-agent exploration scripts/readings, including failed 60/8 and 75/10 arms | n/a | n/a |

The 100 entries recorded as Phase I garden-versus-garden “swap failures” are preserved unchanged in the v2 JSON. They are diagnostic expectation failures, not evidence that team 1 won every game. The original outcomes were 55 team-0 wins and 45 team-1 wins; the replay produced the same team-index winner on every seed. The v2 probe incorrectly applied the distinct-team `1 - winner` rule to this exact identity fixture.

The current v3 diagnostic applies the correct rule. For exactly equal deployment inputs, a “swap” is an identity replay and must preserve team indexes, direct side fingerprints, duration, and the full event stream. It passed all four checks in 100/100 trials. The deployment fair coin selected team 0 first in 52 trials and team 1 first in 48 (exact two-sided binomial summary p=0.764353); a finite 55/45 winner split is not itself bias evidence. Distinct-team pairings continue to require winner inversion and rotated side fingerprints. The old formal JSON was not rerun under v3.

## Phase I formal readout (score = wins + 0.5 draws)

Frozen candidate versus original garden:

| Opponent | Original garden | Frozen candidate | Paired score delta | Candidate win 95% Wilson CI |
|---|---:|---:|---:|---:|
| Original dive | 0.20 | 0.83 | +0.63 | 0.7445–0.8911 |
| Mirrored dive | 0.12 | 0.23 | +0.11 | 0.1584–0.3215 |
| Garden | 0.55 | 0.00 | -0.55 | 0.0000–0.0370 |
| Disrupt | 0.92 | 0.32 | -0.60 | 0.2367–0.4166 |
| Battery | 1.00 | 0.71 | -0.29 | 0.6146–0.7899 |

Selecting the learned guard did not change any winner relative to the same build with guard learned but unselected. Guard triggered and produced an observed redirected primary packet in 18/100 trials against original dive; it did not trigger against mirrored dive, garden, disrupt, or battery. Therefore the original-dive gain is attributable to the frozen species/formation/resources rather than a measured guard win effect in this held-out set.

## Phase II formal readout

Disrupt kept its species, positions, teaching, and partner. Charizard's slot-2 `focus_lens` was either retained or replaced by `healing_needle`. The no-reduction arm kept the needle equipped and patched only `Battle._apply_healing_needle` to a no-op.

| Opponent | Old lens | Needle, no reduction | Full needle | Full minus no-reduction | Full-vs-noop win gains/losses | Exact McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| Garden | 0.08 | 0.11 | 0.34 | +0.23 | 26/3 | 0.000015 |
| Dive | 0.16 | 0.01 | 0.01 | 0.00 | 0/0 | 1.0 |
| Battery | 0.04 | 0.04 | 0.04 | 0.00 | 4/4 | 1.0 |

Mechanism accounting over 100 trials:

- Garden: full needle blocked in 99 trials, emitted 816 actual `healing_prevented` events, and removed 7,402 actual HP of healing. Mean disrupt survivors rose from 0.28 (no reduction) to 0.81. Win rate remained only 34%, so denial is useful but not sufficient to overturn the matchup.
- Dive: 80 blocks and 32 actual prevention events removed 576 HP, with no outcome change. Losing lens startup/data changed the score by -0.15 (1 gain, 16 losses, p=0.000275); this opportunity cost dominates.
- Battery: 33 blocks occurred, but no heal was actually available in the blocking window, so prevented healing and all outcome deltas were zero.

## Interpretation and limits

- Counter arms are not required to exceed 55%. The useful conclusion is directional and mechanism-backed: current healing denial strongly mitigates garden's sustain but remains below even; dive exposes the 40-start-energy opportunity cost; battery has no actual heal to deny in these trials.
- Fixed authored squads do not estimate acquisition frequency, bot crafting/equipping, full-run completion, or all-roster balance.
- The no-reduction arm is an intentional method patch, not a producible item.
- Wilson intervals above describe win proportion only. Paired deltas and exact McNemar tests are finite-sample summaries.

## Archived metadata correction

The archived formal v2 Phase II JSON has `phase: 1-current-mechanism` due to a constant metadata label in that script. Its `mode: phase2-formal-held-out`, `ruleset: tactics_v3`, item arms and this README identify the actual Phase II experiment. The original artifact remains unchanged. The current probe honors the explicit phase argument; only the identity diagnostic was rerun after this metadata fix, with zero hard replay mismatches.
