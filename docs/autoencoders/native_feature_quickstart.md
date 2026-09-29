# Native feature training, persistence, and inference quickstart

[Handbook](README.md) · [Modality API reference](modalities.md)

This example builds actual native UI models, prepares four separate logic
views, trains a small CPU structural autoencoder, stores a candidate in a local
DuckDB registry, closes and reopens that registry, resumes the exact numerical
parent, and reads latent features without training. It needs the existing
workspace Python environment with PyTorch and DuckDB installed. It downloads
no weights, invokes no external prover, and writes only to a fresh directory
under `/tmp`.

The documents below are small authored fixtures, not a representative UI
corpus or a held-out semantic test. Their vectors describe compiler-output
structure, not pretrained semantic text embeddings. All qualification,
admission, formalization, and promotion flags remain false. Review
[modalities and the API reference](modalities.md) before substituting real
inputs.

Save the following single Python block as `/tmp/native_feature_quickstart.py`.
Run it in a fresh process from the pinned dataset checkout with this command:
`cd /home/barberb/lift_coding/external/ipfs_datasets`, followed by
`PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/native_feature_quickstart.py`.
Using a fresh process matters because a bare package import can otherwise
resolve to the unrelated editable HACC install. The script checks its UI
adapter path, uses one CPU thread, and places process-local cache paths inside
its fresh output directory.

```python
import hashlib
import json
import os
from pathlib import Path
import tempfile

repository = Path.cwd().resolve()
assert (repository / "ipfs_datasets_py/logic/ui_ux_ir").is_dir(), "Run from the pinned dataset checkout"
output = Path(tempfile.mkdtemp(prefix="native-feature-quickstart-", dir="/tmp"))
os.environ.update({
    "CUDA_VISIBLE_DEVICES": "",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TORCH_HOME": str(output / "cache/torch"),
    "HF_HOME": str(output / "cache/huggingface"),
    "XDG_CACHE_HOME": str(output / "cache/xdg"),
})

import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.formalization.autoencoder import ui_targets
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import RoundTripDocument
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass, ProgramBindingTargetKind, RiskClass, UIActionBinding, UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.components import SemanticComponent, UIComponentGraph
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import CanonicalInteractionEvent, EventKind, EventProvenance
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

assert Path(ui_targets.__file__).resolve().is_relative_to(repository / "ipfs_datasets_py")


def document(index):
    return RoundTripDocument(
        document_id=f"ui:quickstart:{index}",
        component_graph=UIComponentGraph(
            components=(SemanticComponent(component_id="delete", role="button"),),
            entry_component_ids=("delete",),
        ),
        behavior_model=BehaviorModel(
            model_id="delete-workflow",
            states=(BehaviorState(state_id="pending"), BehaviorState(state_id="cancelled", terminal=True)),
            transitions=(BehaviorTransition(
                transition_id="timeout", source_state_ids=("pending",),
                target_state_id="cancelled", event_id="cancel", timeout_ms=1000 * index,
            ),),
            initial_state_ids=("pending",),
        ),
        action_bindings=(UIActionBinding(
            binding_id="binding:delete", action_id="delete",
            program_ref=UIProgramRef(
                target_kind=ProgramBindingTargetKind.MCP_IDL,
                mcp_idl_interface_cid="bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i",
                mcp_idl_method_name="delete",
            ),
            risk_class=RiskClass.HIGH, confirmation_class=ConfirmationClass.CONFIRM,
        ),),
        events=(CanonicalInteractionEvent(
            event_id="click:delete", kind=EventKind.ACTIVATE,
            target_component_id="delete", timestamp_ms=index,
            provenance=EventProvenance.HUMAN, capability_id="pointer_mouse", consent_ok=True,
        ),),
    )


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


training = [ui_targets.prepare_ui_targets(document(i)) for i in (1, 2)]
tuning = [ui_targets.prepare_ui_targets(document(i)) for i in (3, 4)]
assert all(target.to_dict()["ready_for_training"] for target in training + tuning)
projection_ids = (
    "ui_ux_ir:flogic", "ui_ux_ir:event_calculus", "ui_ux_ir:tdfol", "ui_ux_ir:dcec",
)
space = features.build_feature_space("ui_ux_ir", projection_ids, training)
contract = features.build_native_feature_contract(
    space, ir_schema="ui-ux-ir/v1", latent_width=4,
    adapter_sha256=hashlib.sha256(Path(ui_targets.__file__).read_bytes()).hexdigest(),
)
write_json(output / "targets.json", {
    "training": [target.to_dict() for target in training],
    "tuning": [target.to_dict() for target in tuning],
})
first = features.train_projection_features(
    contract, space, training, tuning, epochs=2, latent_width=4,
    learning_rate=0.02, max_seconds=30.0, seed=1729,
)
database = output / "control.duckdb"
artifacts = output / "artifacts"
with AutoencoderRegistry(database, artifacts) as registry:
    registered = features.register_feature_candidate(
        registry, contract, space, first, output / "candidate-001",
    )
write_json(output / "first-version.json", {"version_id": registered["version_id"]})

# Reopen the existing owner after the first one closes. Load the actual
# registered artifact, not an unrelated checkpoint with the same dimensions.
with AutoencoderRegistry(database, artifacts) as registry:
    parent_id = json.loads((output / "first-version.json").read_text())["version_id"]
    parent = registry.get_version(parent_id)
    registry.verify_artifact(parent["artifact"])
    saved = json.loads(registry.artifact_path(parent["artifact"]).read_text())
    loaded_contract = ModalityContract.from_dict(saved["contract"])
    loaded_space, loaded_state = saved["feature_space"], saved["state"]
    targets = json.loads((output / "targets.json").read_text())
    loaded_training = [DomainTargetEnvelope.from_dict(row) for row in targets["training"]]
    loaded_tuning = [DomainTargetEnvelope.from_dict(row) for row in targets["tuning"]]
    before_state_digest = features.digest(loaded_state)
    initial_read = features.infer_projection_features(
        loaded_contract, loaded_space, loaded_state, loaded_tuning,
    )
    assert initial_read["training_executed"] is False
    assert features.digest(loaded_state) == before_state_digest

    resumed = features.train_projection_features(
        loaded_contract, loaded_space, loaded_training, loaded_tuning,
        base_state=loaded_state, epochs=1, latent_width=4,
        learning_rate=0.02, max_seconds=30.0, seed=1729,
    )
    assert resumed["report"]["base_state_sha256"] == before_state_digest
    child = features.register_feature_candidate(
        registry, loaded_contract, loaded_space, resumed, output / "candidate-002",
        parent_version_id=parent_id,
    )
    assert registry.get_version(child["version_id"])["parent_version_id"] == parent_id
    assert features.digest(loaded_state) == before_state_digest
    final_read = features.infer_projection_features(
        loaded_contract, loaded_space, resumed["state"], loaded_tuning,
    )

assert final_read["training_executed"] is False
assert final_read["decoded_formulas_generated"] is False
assert all(final_read[name] is False for name in features.FALSE)
write_json(output / "inference.json", final_read)
write_json(output / "summary.json", {
    "output_directory": str(output), "variant_id": loaded_contract.variant_id,
    "parent_version_id": parent_id, "child_version_id": child["version_id"],
    "initial_objective": first["report"]["before"]["objective"],
    "selected_objective": resumed["report"]["after"]["objective"],
    "attempted_epochs": first["report"]["attempted_epochs"] + resumed["report"]["attempted_epochs"],
    "selected_total_epochs": resumed["state"]["completed_epochs"],
    "tuning_unknown_atoms": sum(row["unknown_atoms"] for row in final_read["coverage"]),
    "inference_trained": final_read["training_executed"],
    "decoded_formulas_generated": final_read["decoded_formulas_generated"],
    **features.FALSE,
})
print((output / "summary.json").read_text())
```

The output directory retains `targets.json`, the registry database, verified
candidate artifacts, parent-version metadata, `inference.json`, and a short
summary. The registry checks that the resumed candidate names its actual
numerical parent. Both owner contexts are closed before the script exits.
No path in this example names a live campaign database. The MCP IDL CID is an
authored fixture reference; no live interface is fetched or method invoked.

Read `attempted_epochs` separately from `selected_total_epochs`. Candidate
selection may keep an earlier model if any selected projection regresses,
even when aggregate loss falls. The example does not assert a numeric success
threshold or a semantic pass. Inspect each candidate artifact's report for
per-projection reconstruction/cosine losses, vocabulary coverage, and the
selected-versus-rejected history.

The tuning source IDs are distinct, but these fixtures share most structure.
They are repeated tuning data, not independent semantic canaries. The changing
timeout also introduces unknown atoms against the frozen training vocabulary;
the backend reports those atoms rather than claiming to reconstruct them.
Keep the exact tuning envelope list and order, basis, contract, architecture,
and optimizer settings when resuming. Adding vocabulary columns requires an
explicit new variant or migration.

This is local persistence and numerical resume. The current backend is not
connected to the distributed legal runner, Quack remote dispatch, Arrow-backed
weight codec, sparse patch exchange, or Hugging Face. An adapter-module digest
does not replace a frozen manifest of its full compiler/runtime dependencies.
The target envelopes retain UI's shared adapter gap, unperformed family syntax
checks, and unevaluated modality/device layers. No inference promotion, Lake
admission, Constitution formalization, or other semantic qualification is
performed.
