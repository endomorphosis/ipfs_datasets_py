# Leanstral Proof-Assistant Lane

Task: `PORTAL-CXTP-097`

This lane integrates Leanstral as advisory proof engineering assistance for the
Xaman Lean proof-consumer kernel. Leanstral may propose Lean 4 edits or proof
strategies, but it is not the proof authority.

## Source Facts

Mistral describes Leanstral as an open-source code agent designed for Lean 4 and
trained for proof engineering work. The original labs route is
`labs-leanstral-2603`. The current Leanstral 1.5 model card lists
`labs-leanstral-1-5`, a 256k context window, and zero-dollar labs pricing at
the time this lane was written.

Primary sources:

- https://mistral.ai/news/leanstral/
- https://docs.mistral.ai/models/model-cards/leanstral-1-5

## Configuration

The probe detects approved routes from these environment variables:

- `IPFS_DATASETS_PY_LEANSTRAL_MODEL`
- `IPFS_DATASETS_PY_OPENAI_MODEL`
- `IPFS_DATASETS_PY_OPENROUTER_MODEL`
- `IPFS_DATASETS_PY_LLM_MODEL`
- `IPFS_DATASETS_PY_HF_INFERENCE_MODEL`

Approved model routes:

- `labs-leanstral-1-5`
- `labs-leanstral-2603`

It also detects local weights through:

- `IPFS_DATASETS_PY_LEANSTRAL_WEIGHTS`

Provider/base-url hints are recorded from:

- `IPFS_DATASETS_PY_LLM_PROVIDER`
- `IPFS_DATASETS_PY_OPENAI_BASE_URL`
- `IPFS_DATASETS_PY_OPENROUTER_BASE_URL`
- `IPFS_DATASETS_PY_HF_INFERENCE_ENDPOINT`

## Fail-Closed Policy

The default mode is `probe-only-no-network`.

Status meanings:

- `ready-advisory`: an approved route or local weights are configured, the Lean
  lane is ready, and the proof kernel compile-check is available.
- `degraded`: no Leanstral route or local weights are configured.
- `blocked`: a configured Leanstral lane cannot be accepted because the Lean
  verifier is not ready, or an unapproved Leanstral-like route was configured.

Leanstral output is advisory only. Every suggested proof must pass:

```bash
lean security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean
```

The production evidence gate still applies. Leanstral cannot remove
`PORTAL-CXTP-077` through `PORTAL-CXTP-084` blockers and cannot replace named
production source, build, runtime, environment, or owner-signoff evidence.

## Command

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_leanstral_proof_assistant.py \
  --out security_ir_artifacts/environment/leanstral-proof-assistant-report.json
```

For deterministic CI checks that should not inherit operator model variables:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_leanstral_proof_assistant.py \
  --ignore-env \
  --out security_ir_artifacts/environment/leanstral-proof-assistant-report.json
```

## Report

The report schema is
`crypto-exchange-leanstral-proof-assistant-report/v1`.

It records:

- detected Leanstral route or local weights
- Lean/Lake verifier readiness from `lean-solver-lane-report.json`
- proof-kernel path and digest
- generated proof-attempt prompts
- explicit acceptance policy that rejects `axiom`, `admit`, `sorry`, or unsafe
  proof bypasses
- the fact that production evidence gates remain required

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_leanstral_proof_assistant_lane.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_leanstral_proof_assistant.py \
  --out security_ir_artifacts/environment/leanstral-proof-assistant-report.json
```
