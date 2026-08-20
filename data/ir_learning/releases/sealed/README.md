---
license: other
dataset_repo_id: Publicus/proof-grounded-ir-learning
release_id: sha256-b8b062360926fa1fb09c22f44740982f9401f435b524cc41db08e093a206c425
pretty_name: Proof-Grounded IR Learning Release
trust_remote_code: false
configs:
- config_name: source
  data_files:
  - split: train
    path: configs/source/train/source-*.json
- config_name: derived
  data_files:
  - split: train
    path: configs/derived/train/derived-*.json
- config_name: pairs_positive
  data_files:
  - split: train
    path: configs/pairs_positive/train/pairs_positive-*.json
- config_name: pairs_negative
  data_files:
  - split: train
    path: configs/pairs_negative/train/pairs_negative-*.json
- config_name: splits
  data_files:
  - split: train
    path: configs/splits/train/splits-*.json
- config_name: evaluations
  data_files:
  - split: train
    path: configs/evaluations/train/evaluations-*.json
- config_name: checkpoints
  data_files:
  - split: train
    path: configs/checkpoints/train/checkpoints-*.json
- config_name: proofs
  data_files:
  - split: train
    path: configs/proofs/train/proofs-*.json
---

# Proof-grounded IR release `sha256-b8b062360926fa1fb09c22f44740982f9401f435b524cc41db08e093a206c425`

Append-only qualified Hugging Face package.  Each P1 config is a
separately declared, schema-homogeneous Viewer configuration.
Heterogeneous auto-detected schemas are refused.

Publication is versioned and append-only.  Remote upload requires a
`hf-publication:Publicus/proof-grounded-ir-learning` lease, qualification, and human approval.

## Source versus derived counts

- source rows: `7173`
- derived rows: `38690`
- training admitted rows: `0`

Source and derived populations are distinct and never mixed in one
config.  Derivatives do not inflate source counts.

## P1 configs

- `source`: 1 rows
- `derived`: 1 rows
- `pairs_positive`: 1 rows
- `pairs_negative`: 1 rows
- `splits`: 1 rows
- `evaluations`: 1 rows
- `checkpoints`: 1 rows
- `proofs`: 1 rows

## Bound identities

- corpus root: `bafkreiha35x7mcukzzb5x67hmykwsny5wipf5jb4do5gpsl24mxvix55n4`
- split root: `sha256:047b263b85067aa3dad6760f623c2855fbaf776d565ec9c273c49425fcc14eb4`
- compiler: `COMPILER-CURRENT-1`
- decompiler: `DECOMPILER-CURRENT-1`
- loss: `IRLossConfiguration@1`
- evaluation root: `baguqeeraf3mevd4zrpkcy6hmsamfyszkq5zeisq2ipu6bvupquprtfqi53ta`
- proof root: `bafkreiedk7zooeftd4qnhysbuazs6ulntis3ixn5vye6q7bgtxgrdlrfna`
- P4 evidence CID: `bafkreia35e5pexkbnq7x2lqtoomcwx34hceroyzsltkb4rqirjjvlqkdle`

This card is generated offline.  Tokens and credentials never appear
in cards, manifests, or receipts.
