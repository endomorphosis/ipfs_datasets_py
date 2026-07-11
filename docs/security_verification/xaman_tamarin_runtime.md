# Xaman Tamarin Runtime

Task: `PORTAL-CXTP-141`

This lane pins the user-local Maude runtime used by the pinned Tamarin release for Testnet protocol checking. It depends on `PORTAL-CXTP-092`; it only establishes that the checker runtime is usable. It is not a proof of the Xaman protocol model by itself.

## Runtime Decision

- Report: `security_ir_artifacts/environment/tamarin-runtime-report.json`
- Probe: `scripts/ops/security_verification/probe_tamarin_runtime.py`
- Status: `ready`
- Decision: `TAMARIN_MAUDE_RUNTIME_READY`
- Pinned checker: Tamarin 1.12.0
- Accepted rewriting runtime: Maude 3.5.1

Tamarin was invoked with `--with-maude=/home/barberb/.local/bin/maude`. Its own version check reported `Tamarin version 1.12.0`, `Maude version 3.5.1`, `3.5.1. OK.`, and `checking installation: OK`.

## Recorded Artifacts

- Tamarin wrapper: `/home/barberb/.local/bin/tamarin-prover`
- Tamarin wrapper digest: `sha256:03c4e139a1385be0f76904274e4c9d4809dc9fc0baa595eeaa46766c15a16dd9`
- Tamarin binary: `/home/barberb/.local/share/xaman-proof-solvers/opt/tamarin-prover`
- Tamarin binary digest: `sha256:9d3fcbaa65aeea244cff5b8074338d129427161cc8b02e5aee72d30ee072acc9`
- Tamarin archive: `/home/barberb/.local/share/xaman-proof-solvers/downloads/tamarin-prover-1.12.0-linux64-ubuntu.tar.gz`
- Tamarin archive digest: `sha256:201be06f469e47cff554df6ca93db8366fc2c69d70c61fcbd1370a1074b469c6`
- Maude wrapper: `/home/barberb/.local/bin/maude`
- Maude wrapper digest: `sha256:17f5d7abac2afb279aab9de23c343620dcbf4019614e808bc778e80217e44203`
- Maude binary: `/home/barberb/.local/share/xaman-proof-solvers/opt/maude-3.5.1/maude`
- Maude binary digest: `sha256:9dd4044e693944aae97ad72086bc70275fa34bf635f9b377a5b2100bf3ed8655`
- Maude archive: `/home/barberb/.local/share/xaman-proof-solvers/downloads/Maude-3.5.1-linux-x86_64.zip`
- Maude archive digest: `sha256:72ed1ca87e3b3d0dfc6ee1436baf154bf04c45ff97d521bec040c5e8dfc8f92c`
- Runtime report artifact CID: `sha256:86e69bf463a046dff323d00cccc770c5ce38f5180518cef437ef6514e3537f9d`

## Minimal Theory Check

The probe writes an ephemeral theory named `TamarinRuntimeSmoke` and runs:

```bash
/home/barberb/.local/bin/tamarin-prover \
  --with-maude=/home/barberb/.local/bin/maude \
  --prove runtime_smoke.spthy
```

The checked lemma is `runtime_smoke_exists`. The report records `runtime_smoke_exists (exists-trace): verified (2 steps)` and stores the theory source digest `sha256:10f7fa91601b252da82c3ab87cbd07bb080b8b9e3181bdd2892c09ac036031d8`.

## Rejected Evidence

Maude 3.2 is not accepted as protocol-proof evidence for this lane. The probe treats observed Maude version `3.2` as `MAUDE_3_2_NOT_ACCEPTED` even if a wrapper or warning text is present. Runtime evidence must come from the pinned Tamarin 1.12.0 binary accepting the selected Maude runtime and from a successful minimal theory run.

## Refresh Command

```bash
PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_tamarin_runtime.py \
  --out security_ir_artifacts/environment/tamarin-runtime-report.json

PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  -m pytest tests/logic/security_models/crypto_exchange/test_tamarin_runtime.py -q
```
