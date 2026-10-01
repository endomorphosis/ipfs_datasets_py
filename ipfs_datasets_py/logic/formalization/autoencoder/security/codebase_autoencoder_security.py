"""Source-derived CVE observations paired with native advisory SecurityIR labels.

This projection learns classification candidates, never formulas, executable
policies or proofs. Target-derived graph summaries are deliberately excluded
from inputs. Canonical SourceRecord/CodeUnit/PolicyCandidate links are checked
by the native export loader before targets enter training.
"""
from __future__ import annotations

import math
from pathlib import Path

SCHEMA = "security-ir-candidate-projection@1"


def prepare_security_training(descriptor, initializer):
    from .security_cve_canonical_export import load_canonical_cve_training
    from .codebase_autoencoder import FEATURES, _sha
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as native
    if type(descriptor) is not dict or set(descriptor) != {"output", "manifest_sha256"}:
        raise ValueError("exact independently pinned canonical CVE export required")
    loaded = load_canonical_cve_training(Path(descriptor["output"]), expected_manifest_sha256=descriptor["manifest_sha256"])
    pairs = loaded["training_pairs"]
    if not 2 <= len(pairs) <= 8:
        raise ValueError("bounded paired canonical CVE training required")
    vocabulary = sorted({item for pair in pairs for item in pair["target"]["cwe_ids"]})
    if len(vocabulary) > 64 or any(type(v) is not str or not v or len(v) > 64 for v in vocabulary):
        raise ValueError("bounded canonical CWE target vocabulary required")
    labels = ["effect:audit", "classification_only", "polarity:vulnerable", "unknown_cwe"] + ["cwe:" + v for v in vocabulary]
    positions = {key: index for index, key in enumerate(initializer["keys"])}
    rows, targets = [], []
    for pair in pairs:
        inputs, target = pair["input"], pair["target"]
        if (inputs.get("tokenizer_sha256") != _sha(Path(native.__file__).read_bytes())
                or inputs.get("ast_feature_vocabulary") != list(FEATURES)
                or inputs.get("ast_projection_family") != "code_ast@1"
                or target.get("effect") != "audit" or target.get("classification_only") is not True
                or target.get("proof_authoritative") is not False or target.get("polarity") not in {"vulnerable", "fixed"}):
            raise ValueError("native source observation or advisory target differs")
        samples = inputs.get("ast_samples")
        if type(samples) is not list or len(samples) > 1024:
            raise ValueError("bounded canonical AST observation required")
        features = [0.0] * len(FEATURES)
        for sample in samples:
            values = sample.get("features")
            if (type(values) is not list or len(values) != len(FEATURES)
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values)):
                raise ValueError("finite exact source AST feature dimensions required")
            features = [a + b / len(samples) for a, b in zip(features, values)]
        tokens = inputs["lexical_token_counts"]
        matched = sum(count for key, count in tokens.items() if key in positions)
        indices = sorted({positions[key] for key in tokens if key in positions})
        rows.append({"row_id": pair["row_id"], "source_cid": pair["source_cid"],
            "body_sha256": pair["body_sha256"], "source_record_cid": pair["source_record_cid"],
            "candidate_cid": pair["candidate_cid"], "code_unit_cids": pair["code_unit_cids"],
            "ast_status": inputs.get("ast_status"), "ast_sample_count": len(samples),
            "features": features, "lexical_indices": indices,
            "lexical_coverage": {"selected_tokens": sum(tokens.values()), "in_vocabulary_tokens": matched,
                "oov_tokens": sum(tokens.values()) - matched, "unique_matched_keys": len(indices), "token_window": 40}})
        targets.append([1.0, 1.0, float(target["polarity"] == "vulnerable"), float(target["unknown_cwe"])]
                       + [float(v in target["cwe_ids"]) for v in vocabulary])
    if not any(row["lexical_indices"] for row in rows):
        raise ValueError("canonical CVE inputs have zero inherited lexical overlap")
    metadata = {"schema": SCHEMA, "projection_family": "security_ir_audit_cwe_polarity_candidates@1",
        "canonical_export": descriptor, "target_vocabulary": labels,
        "input_projection": "mean source-body function AST features and native lexical keys",
        "target_graph_features_used_as_inputs": False, "rows": rows, "targets": targets,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "proof_authority": False, "formalization_authority": False, "execution_authority": False,
        "output_role": "advisory_classification_candidates_only", "holdout_evaluated": False}
    return metadata


def security_candidate_inference(torch, parameters, metadata):
    from .codebase_autoencoder import _forward, _lexical_tensor
    rows = metadata["rows"]
    data = torch.tensor([r["features"] for r in rows], dtype=parameters[0].dtype)
    latent, _ = _forward(torch, data, parameters, _lexical_tensor(torch, rows, parameters))
    logits = latent @ parameters[5] + parameters[6]
    targets = torch.tensor(metadata["targets"], dtype=parameters[0].dtype)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, targets)
    if not torch.isfinite(loss):
        raise ValueError("nonfinite security candidate objective")
    return logits, loss


def security_candidate_report(torch, parameters, metadata):
    with torch.no_grad():
        logits, loss = security_candidate_inference(torch, parameters, metadata)
        scores = torch.sigmoid(logits).tolist()
    return {"schema": SCHEMA, "target_vocabulary": metadata["target_vocabulary"],
            "training_bce": float(loss), "candidate_scores": scores,
            "row_ids": [row["row_id"] for row in metadata["rows"]],
            "scores_are_calibrated_probabilities": False,
            "proof_authority": False, "formalization_authority": False, "execution_authority": False,
            "holdout_evaluated": False}


def task_security_candidate_nominations(torch, rows, parameters, metadata):
    """Apply the learned advisory head to exact current task function rows.

    Training bodies and task functions differ in granularity; scores are
    uncalibrated nominations, not assessments that a vulnerability exists.
    They cannot omit work, create a policy or satisfy a proof obligation.
    """
    from .codebase_autoencoder import _forward, _lexical_tensor
    with torch.no_grad():
        data = torch.tensor([row["features"] for row in rows], dtype=parameters[0].dtype)
        latent, _ = _forward(torch, data, parameters, _lexical_tensor(torch, rows, parameters))
        scores = torch.sigmoid(latent @ parameters[5] + parameters[6]).tolist()
    if not all(math.isfinite(value) for row in scores for value in row):
        raise ValueError("nonfinite task candidate nomination")
    return {"schema": SCHEMA, "target_vocabulary": metadata["target_vocabulary"],
        "canonical_export_manifest_sha256": metadata["canonical_export"]["manifest_sha256"],
        "rows": [{"row_id": row["row_id"], "scores": values} for row, values in zip(rows, scores)],
        "scope": "source_body_trained_head_applied_to_task_function_rows",
        "granularity_shift_validated": False, "scores_are_calibrated_probabilities": False,
        "authority": "unverified_candidate_only", "omission_authority": False,
        "proof_authority": False, "formalization_authority": False, "execution_authority": False,
        "holdout_evaluated": False}
