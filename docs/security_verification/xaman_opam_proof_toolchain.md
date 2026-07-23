# Xaman OPAM Proof Toolchain

Task: `PORTAL-CXTP-142`

This attestation records the user-local OPAM/Rocq and ProVerif toolchain used to unblock Testnet protocol-checking and independent-kernel coverage prerequisites. It depends on `PORTAL-CXTP-092`; it only proves the proof tools can run minimal checks. It is not a proof of the Xaman Testnet protocol model.

## Toolchain Decision

- Report: `security_ir_artifacts/environment/opam-proof-toolchain-report.json`
- Probe: `scripts/ops/security_verification/probe_opam_proof_toolchain.py`
- Status: `ready`
- Decision: `OPAM_PROOF_TOOLCHAIN_READY`
- OPAM root: `/home/barberb/.local/share/xaman-proof-solvers/opam-root`
- OPAM switch: `xaman-proof`
- OPAM executable: `/home/barberb/.local/bin/opam`
- OPAM version: `2.5.2`
- Report artifact CID: `sha256:55ba5921ce16627e0528cec032738985d943e188d57eb9a7d3ae558d29c2a602`

## Pinned Versions

- Rocq/Coq compatibility package: `9.1.1`
- `coq-core`: `9.1.1`
- `rocq-core`: `9.1.1`
- OCaml base compiler: `4.14.2`
- ProVerif: `2.05`
- ProVerif upstream archive digest: `sha256:4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4`

The switch package database records `coq 9.1.1`, `coq-core 9.1.1`, `rocq-core 9.1.1`, and `ocaml-base-compiler 4.14.2`. `coqc --version` and `coqtop --version` both report `The Rocq Prover, version 9.1.1` compiled with `OCaml 4.14.2`.

## Recorded Wrappers

- `coqc` wrapper: `/home/barberb/.local/bin/coqc`
- `coqc` wrapper digest: `sha256:b61226cedcef88da2861829e8e88e01d8810936d3b7860ec5595d410a033cd40`
- `coqc` target: `/home/barberb/.local/share/xaman-proof-solvers/opam-root/xaman-proof/bin/coqc`
- `coqc` target digest: `sha256:aefb746f3a70d0a71a9a669f84aee6204ada243045abfde655273a256da5397b`
- `coqtop` wrapper: `/home/barberb/.local/bin/coqtop`
- `coqtop` wrapper digest: `sha256:78f879d835f052c38eeb8fbce202e9f748d9f488d4508d9f3a958f11f10fa993`
- `coqtop` target: `/home/barberb/.local/share/xaman-proof-solvers/opam-root/xaman-proof/bin/coqtop`
- `coqtop` target digest: `sha256:8e59ede337d12b25ef64ea72069faf2d0985384bbaa51e572499a7d10553a819`
- `proverif` wrapper: `/home/barberb/.local/bin/proverif`
- `proverif` wrapper digest: `sha256:40a19827349da60fa1a44e8986058f1882b229c0f351dc4ab973981c3cf6e622`
- `proverif` target: `/home/barberb/.local/share/xaman-proof-solvers/src/proverif2.05/proverif`
- `proverif` target digest: `sha256:8daabb7016a7d72f402e7c641cf28910fb1ec887dc1487d3d3203a057aae077e`

## ProVerif Provenance

The ProVerif wrapper targets a pinned upstream `proverif2.05` source build. The archive at `/home/barberb/.local/share/xaman-proof-solvers/downloads/proverif2.05.tar.gz` has digest `sha256:4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4`, matching the OPAM index entry for `proverif.2.05` from `https://proverif.inria.fr/proverif2.05.tar.gz`.

The report keeps `PROVERIF_NOT_INSTALLED_AS_OPAM_PACKAGE` as a warning because the switch package database does not list `proverif 2.05`. It is not a blocker for this attestation because the wrapper is version-pinned, the source archive matches the OPAM index checksum, and the minimal ProVerif check passed.

## Minimal Checks

The Coq compiler check writes an ephemeral file with:

```coq
Theorem xaman_opam_coq_smoke : True.
Proof. exact I. Qed.
```

`/home/barberb/.local/bin/coqc` compiled it successfully. The source digest is `sha256:9eeea51bc98c0db7a83d8f304d3aacd079b8bc0787adfd4dd11d3f455b9ff59a`.

The Coq top-level check runs `Check True.` through `/home/barberb/.local/bin/coqtop -quiet` and receives `True : Prop`. The input digest is `sha256:9935b4acf301276db1c0a6a506da90797d7901137ca5bd0ad9257522e556900f`.

The ProVerif smoke model is:

```proverif
free c: channel.
free xaman_secret: bitstring [private].
query attacker(xaman_secret).
process 0
```

`/home/barberb/.local/bin/proverif` returned `RESULT not attacker(xaman_secret[]) is true`. The model digest is `sha256:902af34c51f7f85b98649804ddc656b7f59221a83e5c77987fab297d6d312e5a`.

## Release Interpretation

This lane removes the named OPAM proof-toolchain blocker for `coqc`, `coqtop`, and `proverif` execution. It does not replace model-specific Tamarin, ProVerif, Lean, Coq, SMT, or TLA results. If a future refresh records `blocked_toolchain`, Testnet protocol or independent-kernel coverage must remain blocked until the missing executable, pin, wrapper target, digest, or minimal check is repaired.

## Refresh Command

```bash
PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_opam_proof_toolchain.py \
  --out security_ir_artifacts/environment/opam-proof-toolchain-report.json

PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  -m pytest tests/logic/security_models/crypto_exchange/test_opam_proof_toolchain.py -q
```
