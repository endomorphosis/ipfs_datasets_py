# Experimental structured 384D checkpoint releases

These opt-in development profiles extend the existing public checkpoint catalog.
They use `structured-source-384-autoencoder/v1`, with a fixed typed JSON shape and
learned scalar classes. They are separate from the canonical v1 domain packages;
the default source formalizers and authority rules are unchanged.

The immutable Hub revisions, manifest hashes, and checkpoint hashes are recorded
in [the release descriptors](../implementation/reports/evidence/structured-ir-release-20261001/verified-descriptors.json).

| Domain/profile | Raw exact reconstruction | Style canary |
| --- | --- | --- |
| Intent/native-v3 |120/120|60/60|
| Security/native-v3 |120/120|39/60|
| UI/UX/native-v3 baseline |120/120|53/60|
| Legal/native-v3 |120/120|60/60|
| Security/styles-v4 diagnostic |490/504|69/112|

These are previously inspected authored compositions with known scalar vocabulary,
not new Terminal-Bench task scores. Canary variants share semantic groups with the
test split. UI retains its baseline after the augmented canary fell to 45/60; this
is an explicit post-evaluation choice. The regressing Security legacy-repair head
is excluded. The trained Legal parent and previous releases remain unchanged.

The Security profiles additionally support explicit guarded AST normalization.
Previously measured normalized diagnostics reconstructed and compiled 180/180 and
616/616 variants respectively. This is a hybrid input path over a narrow function
grammar; Lake compilation does not prove Python equivalence or security correctness.
The package validation summaries bind those results to the original report hashes.

## Download and consume an exact profile

Select a descriptor from the linked JSON file, download its exact immutable
revision, and copy the blob to a regular local file. The structured runtime checks
the digest and its implementation hashes; it intentionally rejects symlinks.

```python
import hashlib
import shutil
from pathlib import Path
from huggingface_hub import hf_hub_download
from ipfs_datasets_py.logic.formalization.autoencoder.structured_source_384 import load_checkpoint

# pin is one exact descriptor from verified-descriptors.json.
blob = hf_hub_download(pin["repository_id"],
    pin["release_prefix"] + "/checkpoint.json", revision=pin["revision"])
assert hashlib.sha256(Path(blob).read_bytes()).hexdigest() == pin["checkpoint_sha256"]
local = Path("checkpoints") / (pin["domain_id"] + "-" + pin["profile"] + ".json")
local.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(blob, local)
model = load_checkpoint(local, expected_sha256=pin["checkpoint_sha256"],
    expected_domain=pin["domain_id"])
# Actual 384D GTE-small embeddings are required; targets are never inference inputs.
report = model.infer([{"id": "sample", "source_text": source, "embedding": vector384}])
```

For Security source qualification, use
`source_program_runtime_384.load_source_program_decoder_384`; for explicitly
normalized inputs, use
`normalized_source_program_runtime_384.load_normalized_source_program_decoder_384`.
The accelerator supervisor consumes that file through its existing configuration:

```json
{
  "schema": "supervisor-security-source-program-384-config/v1",
  "checkpoint_path": "/absolute/path/to/downloaded-regular-file.json",
  "checkpoint_sha256": "<exact digest from descriptor>",
  "decoder": "structured",
  "input_view": "guarded_ast_normalized"
}
```

Pass it to `scripts/ops/agent_supervisor/prepare_task_context.py` using
`--security-source-program-config`. Omitting `input_view` retains the raw path.
All output remains advisory and fail-open; loading a checkpoint confers no proof,
admission, or execution authority. Use the reviewed local GTE snapshot and native
Lake configuration when exercising the full source-to-projection path.
