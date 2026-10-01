"""Lazy public training API shared by all four domain IR libraries.

Native family reconstruction and 384D source decoding are distinct objectives.
Importing this module does not import Torch, load a checkpoint or start fitting.
"""


def native_family_ids(domain_id):
    from ....optimizers.logic_theorem_optimizer.domain_family_complete_training import native_family_ids as run
    return run(domain_id)


def train_native_families(domain_id, training_rows, validation_rows, **options):
    """Audit source/groups, then fit complete native-family structural targets."""
    from ....optimizers.logic_theorem_optimizer.domain_family_complete_training import train_domain_complete_family_autoencoder
    return train_domain_complete_family_autoencoder(domain_id, training_rows, validation_rows, **options)


def reconstruct_native_families(descriptor, rows):
    from ....optimizers.logic_theorem_optimizer.domain_family_complete_training import infer_domain_complete_family_autoencoder
    return infer_domain_complete_family_autoencoder(descriptor, rows)


def train_source_decoder_384(domain_id, training_rows, validation_rows, **options):
    """Fork a trained Legal 384D head for Intent, Security or UI/UX source IR.

    Inputs carry genuine embeddings and explicit typed targets. Legal's existing
    current_v2 joint trainer remains its source-decoder owner. Generated IR is
    always unqualified until independently checked for source fidelity/proofs.
    """
    from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import train
    return train(domain_id, training_rows, validation_rows, **options)


def _check_ui_target(target):
    """The envelope's free strings must also satisfy the semantic vocabulary."""
    from .ui_source_contract_384 import validate_training_target
    validate_training_target(target)


def _preflight_source_targets(domain_id, training_rows, validation_rows):
    if domain_id == "ui_ux_ir":
        for rows in (training_rows, validation_rows):
            for row in rows:
                _check_ui_target(row["target"])


def _check_source_report(report):
    """Preserve generated candidates while exposing semantic-model rejection."""
    if report.get("domain_id") != "ui_ux_ir":
        return report
    from copy import deepcopy
    report = deepcopy(report)
    for row in report["rows"]:
        target = row.get("candidate_ir")
        if target is None:
            continue
        try:
            _check_ui_target(target)
        except (ValueError, TypeError, KeyError) as error:
            row.update(native_component_validated=False,
                native_component_diagnostic=str(error)[:1024],
                status="fail_open_native_component_invalid", continue_planning=True)
        else:
            row.update(native_component_validated=True)
    return report


class _NativeCheckedSourceRuntime:
    """Add native component checks without changing source-pinned checkpoints."""
    def __init__(self, runtime):
        self.runtime = runtime

    def describe(self):
        return {**self.runtime.describe(), "ui_semantic_component_validation": True}

    def infer(self, rows, **options):
        return _check_source_report(self.runtime.infer(rows, **options))


def train_source_decoder_384_v2(domain_id, training_rows, validation_rows, **options):
    """Train the opt-in shared sequence decoder for all four IRs.

    Uses actual 384D embeddings and a trained Legal parent. Free-running tuning
    selects the checkpoint; generated candidates never grant proof authority.
    Existing Legal/published v1 default training and inference stay independent.
    """
    from .source_training_v2 import train
    _preflight_source_targets(domain_id, training_rows, validation_rows)
    return train(domain_id, training_rows, validation_rows, **options)


def load_source_decoder_384_v2(path, *, expected_sha256, expected_domain):
    """Load an exact local sequence checkpoint, with native component checks."""
    from .source_training_v2 import load_checkpoint
    return _NativeCheckedSourceRuntime(load_checkpoint(path,
        expected_sha256=expected_sha256, expected_domain=expected_domain))


def infer_source_decoder_384_v2(checkpoint, rows, **options):
    """Decode explicit source embeddings; inference rows cannot include targets."""
    from .source_training_v2 import Runtime
    return _NativeCheckedSourceRuntime(Runtime(checkpoint)).infer(rows, **options)


def train_structured_source_decoder_384(domain_id, training_rows, validation_rows, **options):
    """Fit scalar heads over the frozen trained Legal residual projection.

    Supports one fixed typed JSON tree and training scalar vocabulary, without
    whole-target retrieval. Tuning selects regularization. This is not a
    general source formalizer or a new encoder reconstruction objective.
    """
    from .structured_source_384 import train
    _preflight_source_targets(domain_id, training_rows, validation_rows)
    return train(domain_id, training_rows, validation_rows, **options)


def load_structured_source_decoder_384(path, *, expected_sha256, expected_domain):
    """Load an exact local structured checkpoint; never resolve mutable main."""
    from .structured_source_384 import load_checkpoint
    return _NativeCheckedSourceRuntime(load_checkpoint(path,
        expected_sha256=expected_sha256, expected_domain=expected_domain))


def infer_structured_source_decoder_384(checkpoint, rows, **options):
    """Generate fixed-schema candidates with explicit native component checks."""
    from .structured_source_384 import Runtime
    return _NativeCheckedSourceRuntime(Runtime(checkpoint)).infer(rows, **options)


def infer_source_texts_384(runtime, texts, *, snapshot_path=None, **options):
    """Verified local GTE-small → loaded decoder; no truncation or LLM calls."""
    from .source_embeddings_384 import embed_texts
    vectors = embed_texts(texts, snapshot_path=snapshot_path)
    rows = [{"id": "input-" + str(index), "source_text": text, "embedding": vector}
            for index, (text, vector) in enumerate(zip(texts, vectors))]
    report = _check_source_report(runtime.infer(rows, **options))
    return qualify_source_candidates_384(report,
        [{"id": row["id"], "source_text": row["source_text"]} for row in rows])


def train_grouped_source_decoder_384(domain_id, training_rows, validation_rows, **options):
    """Audit leakage groups and train without using grouping metadata as input."""
    from .grouped_source_training_384 import train_grouped_source_decoder_384 as train
    return train(domain_id, training_rows, validation_rows, **options)


def qualify_source_candidates_384(report, source_rows):
    """Attach source-bound native views for Security/UI; never rewrite outputs.

    Source rows have exactly id/source_text fields. Security qualifies only the
    supported annotated Python fragment. UI verifies native structure, not the
    source text's meaning. Unsupported and mismatched predictions remain fail-open.
    """
    if report.get("domain_id") not in ("security_ir", "ui_ux_ir"):
        return report
    from copy import deepcopy
    import hashlib
    if type(source_rows) is not list or not 1 <= len(source_rows) <= 4096 or any(
            type(row) is not dict or set(row) != {"id", "source_text"}
            or type(row["id"]) is not str or type(row["source_text"]) is not str for row in source_rows):
        raise ValueError("closed source qualification rows required")
    sources = {row["id"]: row["source_text"] for row in source_rows}
    if len(sources) != len(source_rows) or len(report["rows"]) != len(source_rows) or {
            row["id"] for row in report["rows"]} != set(sources):
        raise ValueError("source qualification identity mismatch")
    if report["domain_id"] == "security_ir":
        from .security.source_program_binding_384 import qualify_source_candidate
    else:
        from .ui_source_contract_384 import qualify_source_candidate
    result = deepcopy(report)
    denied = dict(proof_authority=False, execution_authority=False, completion_authority=False,
        source_semantics_verified=False, claim_proved=False,
        whole_program_semantics_verified=False, security_specification_inferred=False)
    result.update(denied)
    for row in result["rows"]:
        row.update(denied)
        text = sources[row["id"]]
        if row["source_sha256"] != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError("source qualification hash mismatch")
        if row.get("candidate_ir") is None:
            continue
        checked = qualify_source_candidate(text, row["candidate_ir"])
        row["source_contract"] = checked
        if checked["status"] not in ("qualified", "projected_candidate"):
            row.update(status="fail_open_source_contract_" + checked["status"], continue_planning=True)
    result["source_contracts_checked"] = True
    return result


__all__ = ["native_family_ids", "train_native_families", "reconstruct_native_families",
    "train_source_decoder_384", "train_source_decoder_384_v2", "load_source_decoder_384_v2",
    "infer_source_decoder_384_v2", "train_structured_source_decoder_384",
    "load_structured_source_decoder_384", "infer_structured_source_decoder_384", "infer_source_texts_384",
    "train_grouped_source_decoder_384", "qualify_source_candidates_384"]
