# Plateau Holdout Wave (PLAT2)

**Status:** ready for supervisor handoff  
**Prefix:** `## PLAT2-`  
**Namespace:** `semantic-roundtrip-plateau-holdout-v1`

## Why

PLAT-000…091 improved the deterministic path on the **five sealed pilots**
(e2e 0.088 → 0.0) using residual → teacher → prover → agent supervisor →
remeasure. The same loop must now run on a **preregistered holdout** so we do
not overfit those five cases.

## Doctrine (unchanged)

```text
residual catalog → spaCy/AE/Leanstral teachers → Hammer/cvc5/Lean admit
  → PlateauCodexPacket → agent supervisor det. compiler edits → remeasure
```

Production remains **typed_deontic → IR → deterministic realizer** unless
holdout remeasure also passes CI high &lt; 0 and full gates.

## Tasks

| ID | Goal |
| --- | --- |
| PLAT2-000 | Seal plan (completed with this commit) |
| PLAT2-010 | Residual catalog supports holdout populations |
| PLAT2-020 | Freeze holdout fixtures |
| PLAT2-030 | Packets + materializer for holdout |
| PLAT2-040 | Prover-gated teachers |
| PLAT2-050 | Det. edit waves |
| PLAT2-060 | Holdout remeasure + promotion decision |

## Relation to PLAT pilots

Pilot evidence remains historical and sealed. Holdout must not regress pilot
mean e2e 0.0 when re-scored.
