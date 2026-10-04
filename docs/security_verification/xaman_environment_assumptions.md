# Xaman Environment Assumptions

Task: `PORTAL-CXTP-061`

The Xaman corpus is a React Native wallet target. This probe records the build
and dependency assumptions that must hold before source facts can be promoted
into model facts.

Input manifest:

```text
security_ir_artifacts/corpora/xaman-app/source-manifest.json
```

Output report:

```text
security_ir_artifacts/corpora/xaman-app/environment-probe.json
```

## What The Probe Checks

- pinned Xaman commit `942f43876265a7af44f233288ad2b1d00841d5fa`
- `package.json`, `package-lock.json`, and TypeScript configs
- native Android and iOS source presence
- `Gemfile.lock` and `ios/Podfile.lock`
- Detox/e2e config and workflow presence
- local Node, npm, TypeScript, Z3, CVC5, Lean, and optional solver status from
  the solver dependency probe

The report is allowed to have optional solver warnings. It blocks only when
required build files, the pinned manifest, TypeScript, or the solver dependency
probe are missing or blocked.

## Command

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_xaman_environment.py \
  --corpus-manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json \
  --out security_ir_artifacts/corpora/xaman-app/environment-probe.json
```

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py -q
```
