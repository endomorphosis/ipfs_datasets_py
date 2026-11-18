# October 18 LegalIR planning evidence

This directory supports the [consolidated roadmap](../../legal_ir_uscode_roadmap_20261018.md). It is a planning snapshot, not a new training or corpus qualification.

- `public-metadata.json` retains public Hub revision/README observations and bounded Dataset Viewer schema observations. Viewer URLs are mutable; they do not independently bind the physical corpus to a Hub revision. Dataset row bodies are not exported.
- `inspect_public_metadata.py` reproduces that bounded read-only observation with Python's standard library. It refuses overwriting a prior output. HTTP failures remain explicit.
- `local-source-review.json` records inspected working-tree source hashes, linked local evidence hashes, repository heads and static document checks. These heads/hashes are not substituted for historical experiment runtimes.

From the repository root:

```sh
python docs/autoencoders/evidence/legal-ir-roadmap-20261018/inspect_public_metadata.py --output /tmp/legal-ir-public-metadata-new.json
```

Choose a new output filename for each observation. No dependencies, weights, full datasets, models, tests, solver runs or Lean builds are required by this inspection. Prior experiment results in the roadmap were read from retained records, not rerun. No upload, publication, resource-policy change or task-state promotion occurred.
