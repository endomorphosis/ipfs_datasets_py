# Approved public-official USPTO evaluation corpus (PATLAW-139)

Rights-reviewed **approved public official** evaluation corpus for
`PATLAW-G151`. This tree owns **corpus metadata and human labels only**. It
does **not** ship bulk official PDF/HTML bytes in git.

## Layout

| Path | Role |
| --- | --- |
| `manifest.json` | Authoritative inventory: cases, artifacts, roles, splits, leakage and duplicate-family policy |
| `README.md` | This document |

## Artifact roles (fail-closed)

The manifest **distinguishes** three roles. Tests enforce the boundary.

| Role | Meaning | May be labeled official? |
| --- | --- | --- |
| `official_bytes` | Genuine public government / USPTO record, referenced by source URL and/or CID | **Yes** (`public_official` only) |
| `annotation` | Human-reviewed labels (layout, fields, instructions, citations, obligations, submission evidence, deadlines, expected uncertainty) | **No** |
| `synthetic_supplement` | Explicit synthetic layout/adversarial/negative-control material | **No** (never `official_bytes`, never official authority) |

Synthetic material must never be labeled official. Official material must never
be marked `synthetic_supplement`.

## Required fields on every artifact

Each artifact in `manifest.json` carries:

1. **Source URL and/or CID** (`source_url`, `source_cid`)
2. **Public status** (`public_status`: `public` or `approved_public`)
3. **Rights / privacy review** (`rights_privacy_review` with status, reviewer, timestamp, PII scan, redistribution policy)
4. **Acquisition date** (`acquisition_date`, ISO date)
5. **Label reviewer and version** (`label_reviewer`, `label_version`)
6. **Split assignment** (`split_assignment`: `train` \| `validation` \| `test` \| `held_out`)

Plus `family_id` for duplicate-family fencing and `classification` /
`privacy_class` under the public-only policy.

## Splits and leakage

| Partition | Use |
| --- | --- |
| `train`, `validation` | Development / tuning |
| `test`, `held_out` | Evaluation; `held_out` is never used for tuning |

**Leakage policy** (see `leakage_policy` in the manifest):

- Entire `family_id` stays in a single partition
- No shared `family_id`, official `source_url`, or `source_cid` across
  development vs evaluation
- Annotation label text is never admitted as `official_bytes`

**Duplicate-family policy**: unique `artifact_id`, unique official source URL/CID,
unique official `content_sha256`, and one case per `family_id`.

## Coverage

Cases cover correspondence and application types including:

- utility office action and amendment submission (references)
- filing receipt disambiguation
- official regulation (37 CFR) and statute (35 U.S.C.) authority
- agency guidance (MPEP) with non-controlling tier
- design forms/tables and plant deadline calendar (held-out)
- one **synthetic** layout canary that must never impersonate official bytes

## Privacy and redistribution

- Allowed classifications: `public_official`, `public_user`
- Allowed privacy classes: `approved_public_official`, `public_synthetic`
- Forbidden: confidential applications, privileged work product, export-review,
  credentials, or unknown (unknown quarantines; not admitted here)
- Official bulk bytes are **reference-only** (`bytes_policy`); acquire from the
  recorded source URL/CID with rights review before local use
- No private real applications or secrets in this tree

## Validation

```bash
python -m pytest tests/contract/processors/test_uspto_public_official_corpus.py -q
```

This contract is structural and offline. It does not call USPTO networks or
download official packages.

## Relation to synthetic gold (`tests/fixtures/uspto/gold/`)

The broader synthetic gold corpus (`GOLD_CORPUS_MANIFEST.json`, PATLAW-070) remains
separate. This subdirectory is the **approved public-official** evaluation
partition for metrics over rights-reviewed official references plus clearly
marked synthetic supplements.
