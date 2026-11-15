"""One bounded catalog-grammar selection over supplied finite scores.

The old selector's exact pinned numeric/container primitives are reused. Its
public old-profile selection function and every existing source remain intact.
Only the new public catalog prefix owner supplies grammar decisions. This
operation neither executes nor qualifies a model, checkpoint or source context.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat


SCHEMA = "legal-compact-catalog-token-selection/v1"
PROFILE = "object-relational-compact-catalog-selection/v1"
FORMAT = "one-step-allowed-logit-argmax/v1"
SELECTION_POLICY = "referenced_predicates_in_catalog_order/v1"
VOCABULARY_SIZE, MAX_SEQUENCE_TOKENS = 537, 512
MAX_SCORE_INTEGER = (1 << 53) - 1
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 1024 * 1024, 2 * 1024 * 1024
MAX_CONTEXT_BYTES, MAX_CODEC_BYTES, MAX_LOGITS_BYTES = 524288, 32768, 32768
MAX_SOURCE_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_ROOT = _SELF_PATH.parents[3]
_PRIMITIVE_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_selection_v1"
_CATALOG_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_tokens_v1"
_SOURCE_SPECS = (
    ("logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    ("logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py",
     "bc9e425707c98db3425b5dafb1ab75e5c70002cbf6c229ef1f815eb9bb4612af"),
    ("logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    ("logic/autoformal/legal_relational_norm_v1.py",
     "6af97bbe5bb729fc6218b77bc32551aaca5d2ed2ba89d61312937a3109032614"),
    ("logic/syntax_core/ast.py", "4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4"),
    ("logic/syntax_core/signatures.py", "49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf"),
    ("logic/TDFOL/tdfol_core.py", "67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7"),
)
_PREFIX_FIELDS = {"schema", "profile", "format", "selection_policy", "codec_sha256", "context_sha256",
    "context_raw_sha256", "catalog_context", "catalog_sha256", "owner_pins", "authority", "training_mask",
    "evaluation_gold_mask", "status", "reason", "offered_ids", "allowed_token_ids", "counts",
    "local_prefix_only", "global_completability_proven", "remaining_token_slots"}
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "permitted_inference_context_verified",
    "content_context_independence_verified", "checkpoint_compatibility_verified", "numerical_head_compatible",
    "batch_compatibility_verified", "model_executed", "training_executed", "backend_executed", "Lean_admitted",
    "proof_authority", "logits_origin_verified", "head_compatibility_qualified", "global_prefix_completability_proven"), False)
_LIMITATIONS = (
    "Scores are caller-supplied finite observations; no numerical head, checkpoint, encoder, training or score origin is authenticated.",
    "The exact public catalog prefix owner alone supplies grammar decisions; the pinned old selector supplies only bounded numeric/container primitives.",
    "Selection appends at most one allowed ID and never repairs, removes or replaces an offered ID, PAD or missing EOS.",
    "The full catalog remains committed including unused declarations; this prefix operation creates no completed catalog_prediction_id or typed prediction.",
    "Locally allowed IDs do not prove eventual completion, source meaning, independent catalog origin, permitted inference use or learned accuracy.",
    "Existing content-profile selectors, heads, checkpoints, generation and batch consumers remain distinct pinned source generations.",
    "Endpoint input and physical source fences cover the declared finite trusted closure, not a lock, hostile interpreter, third-party authenticity or operating-system sandbox.",
)


class CompactCatalogSelectionError(ValueError):
    """Closed input, fixed-source, prefix receipt or complete-output refusal."""


def _need(value, message):
    if not value:
        raise CompactCatalogSelectionError(message)


def _snapshot(path):
    _need(path.is_absolute() and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "direct canonical source parents required")
    witness = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
          "bounded single-link canonical source required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        _need(witness(opened) == witness(before), "canonical source changed before open")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _need(len(raw) == before.st_size and witness(before) == witness(after) == witness(path.lstat()),
          "canonical source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), witness(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SOURCE_BASELINE = None


def _source_snapshots():
    global _SOURCE_BASELINE
    result = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(result[str(_SELF_PATH)] == _SELF_SNAPSHOT, "catalog selector source changed since import")
    for relative, expected in _SOURCE_SPECS:
        path = _ROOT / relative
        result[str(path)] = _snapshot(path)
        _need(result[str(path)][0] == expected, "fixed catalog selection source generation differs")
    if _SOURCE_BASELINE is None:
        _SOURCE_BASELINE = dict(result)
    _need(result == _SOURCE_BASELINE, "catalog selection physical source identity changed")
    return result


def _finish(failure, check):
    try:
        check()
    except BaseException:
        if failure is None:
            raise
        failure.add_note("A closing catalog selection input/source custody check also failed.")


def _primitives():
    """Load only the exact original standard-library helper generation."""
    before = _source_snapshots()
    old = importlib.import_module(_PRIMITIVE_NAME)
    path = _ROOT / _SOURCE_SPECS[0][0]
    _need(type(old.__file__) is str and Path(old.__file__).absolute() == path
          and old._SELF_SHA == before[str(path)][0], "old selector origin/import anchor differs")
    _need(_source_snapshots() == before, "sources changed during primitive import")
    return old, None, before


def _owners(loaded):
    old, _, before = loaded
    _need(_source_snapshots() == before, "sources changed before catalog import")
    catalog = importlib.import_module(_CATALOG_NAME)
    path = _ROOT / _SOURCE_SPECS[1][0]
    _need(type(catalog.__file__) is str and Path(catalog.__file__).absolute() == path
          and catalog._SELF_SNAPSHOT == before[str(path)], "catalog prefix origin/import anchor differs")
    _need(catalog._SOURCE_SPECS == _SOURCE_SPECS[2:], "fixed catalog dependency closure differs")
    _need(_source_snapshots() == before, "sources changed during catalog import")
    return old, catalog, before


def _closing(loaded):
    old, catalog, snapshots = loaded
    _need(_source_snapshots() == snapshots, "catalog selector physical source custody changed")
    old_path = _ROOT / _SOURCE_SPECS[0][0]
    _need(type(old.__file__) is str and Path(old.__file__).absolute() == old_path
          and old._SELF_SHA == snapshots[str(old_path)][0], "old primitive import anchor changed")
    if catalog is not None:
        path = _ROOT / _SOURCE_SPECS[1][0]
        _need(type(catalog.__file__) is str and Path(catalog.__file__).absolute() == path
              and catalog._SELF_SNAPSHOT == snapshots[str(path)]
              and catalog._SOURCE_SPECS == _SOURCE_SPECS[2:], "catalog prefix import anchor changed")


def _prefix_report(offered, snapshot, loaded):
    old, catalog, snapshots = loaded
    report = old._detach(offered, MAX_REPORT_BYTES)
    _need(type(report) is dict and set(report) == _PREFIX_FIELDS
          and report["schema"] == "legal-compact-catalog-token-prefix/v1"
          and report["profile"] == "object-relational-compact-catalog-tokens/v1"
          and report["format"] == "fixed-json-lexical-compact-catalog/v1"
          and report["selection_policy"] == SELECTION_POLICY
          and report["codec_sha256"] == snapshot["expected_codec_sha256"]
          and report["context_raw_sha256"] == snapshot["expected_context_sha256"],
          "public catalog prefix identity or raw commitment differs")
    ids, allowed, status = report["offered_ids"], report["allowed_token_ids"], report["status"]
    _need(type(ids) is list and all(type(index) is int for index in ids)
          and ids == snapshot["prefix_ids"], "public catalog offered prefix differs")
    _need(type(allowed) is list and len(allowed) <= VOCABULARY_SIZE
          and all(type(index) is int and 0 <= index < VOCABULARY_SIZE for index in allowed)
          and allowed == sorted(set(allowed)), "public catalog allowed-ID inventory differs")
    _need(type(status) is str and status in ("empty", "prefix", "complete", "rejected", "budget_exhausted"),
          "public catalog prefix disposition differs")
    reasons = {"empty": {None}, "prefix": {None}, "complete": {None},
        "rejected": {"invalid_token_ids", "missing_bos", "interior_special_tokens", "invalid_compact_prefix"},
        "budget_exhausted": {"output_limit_without_eos", "no_admissible_next_token_within_total_limit"}}
    _need((report["reason"] is None or type(report["reason"]) is str)
          and report["reason"] in reasons[status]
          and ((bool(allowed) and status in ("empty", "prefix") and len(ids) < MAX_SEQUENCE_TOKENS)
               or (not allowed and status in ("complete", "rejected", "budget_exhausted"))),
          "public catalog prefix reason/selection disposition differs")
    _need(type(report["remaining_token_slots"]) is int
          and report["remaining_token_slots"] == MAX_SEQUENCE_TOKENS - len(ids),
          "public catalog remaining budget differs")
    counts = report["counts"]
    _need(type(counts) is dict and set(counts) == {"nodes", "quantifiers", "modal_nodes", "predicate_occurrences"}
          and all(type(value) is int and 0 <= value <= 512 for value in counts.values())
          and all(value <= counts["nodes"] for value in counts.values()), "public catalog prefix counts differ")
    _need((bool(ids) == (status != "empty"))
          and (status != "empty" or (allowed == [1] and not any(counts.values()))),
          "public empty-prefix observation differs")
    context = report["catalog_context"]
    _need(type(context) is dict and set(context) == {"schema", "selection_policy", "catalog"}
          and context["schema"] == "legal-relational-compact-catalog-context/v1"
          and context["selection_policy"] == SELECTION_POLICY, "public whole catalog wrapper differs")
    canonical = old._wire(context, MAX_CONTEXT_BYTES)
    _need(canonical == old._wire(json.loads(snapshot["context_raw"].decode("utf-8")), MAX_CONTEXT_BYTES)
          and report["context_sha256"] == hashlib.sha256(canonical).hexdigest()
          and report["catalog_sha256"] == hashlib.sha256(old._wire(context["catalog"], MAX_CONTEXT_BYTES)).hexdigest(),
          "public full catalog canonical commitment differs")
    _need(type(report["authority"]) is dict and set(report["authority"]) == set(catalog._AUTHORITY)
          and all(value is False for value in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
          and report["local_prefix_only"] is True and report["global_completability_proven"] is False,
          "public catalog authority/local-only boundary differs")
    expected_paths = {str(_ROOT / relative) for relative, _ in _SOURCE_SPECS[1:]}
    records = report["owner_pins"]
    _need(type(records) is list and len(records) == len(expected_paths), "complete catalog producer population required")
    seen = set()
    for record in records:
        _need(type(record) is dict and set(record) == {"path", "bytes", "sha256"}, "closed catalog producer record required")
        name = record["path"]
        _need(type(name) is str and name in expected_paths and name not in seen
              and record["sha256"] == snapshots[name][0] and type(record["bytes"]) is int
              and record["bytes"] == snapshots[name][1][3], "catalog producer commitment differs")
        seen.add(name)
    return report


def select_compact_catalog_token_v1(logits, prefix_ids, context_raw, *, expected_context_sha256,
                                    codec, expected_codec_sha256):
    """Retain a full score observation and append at most one catalog-allowed ID."""
    _need(type(expected_context_sha256) is str and _SHA.fullmatch(expected_context_sha256) is not None
          and type(context_raw) is bytes and 0 < len(context_raw) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(context_raw).hexdigest() == expected_context_sha256,
          "bounded independently pinned catalog context required")
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec, expected_codec_sha256=expected_codec_sha256)
    loaded = snapshot = token = None
    failure = None

    def fence():
        if loaded is None:
            _source_snapshots()
        else:
            _closing(loaded)
            if token is not None:
                old = loaded[0]
                _need(old._fingerprint(old._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
                      and old._fingerprint(snapshot) == token, "original or captured catalog selector inputs changed")

    try:
        loaded = _primitives()
        old = loaded[0]
        snapshot = old._preflight(original)
        token = old._fingerprint(snapshot)
        loaded = _owners(loaded)
        fence()
        catalog = loaded[1]
        _need(catalog.compact_catalog_token_codec_sha256(snapshot["codec"]) == snapshot["expected_codec_sha256"],
              "fixed public catalog codec commitment differs")
        fence()
        checked = catalog.compact_catalog_allowed_token_ids_v1(snapshot["prefix_ids"], snapshot["context_raw"],
            expected_context_sha256=snapshot["expected_context_sha256"],
            codec=snapshot["codec"], expected_codec_sha256=snapshot["expected_codec_sha256"])
        fence()
        prefix = _prefix_report(checked, snapshot, loaded)
        scores, allowed = snapshot["logits"], prefix["allowed_token_ids"]
        raw_id = old._argmax(scores, list(range(VOCABULARY_SIZE)))
        selected = old._argmax(scores, allowed) if allowed else None
        next_ids = list(snapshot["prefix_ids"])
        if selected is not None:
            next_ids.append(selected)
        result = {"schema": SCHEMA, "profile": PROFILE, "format": FORMAT, "selection_policy": SELECTION_POLICY,
            "status": "selected" if selected is not None else "no_selection",
            "reason": None if selected is not None else (prefix["reason"] or prefix["status"]),
            "prefix_status": prefix["status"], "logits": scores,
            "logits_sha256": hashlib.sha256(old._wire(scores, MAX_LOGITS_BYTES)).hexdigest(),
            "offered_prefix_ids": snapshot["prefix_ids"], "next_prefix_ids": next_ids,
            "prefix_report": prefix, "prefix_report_sha256": hashlib.sha256(old._wire(prefix, MAX_REPORT_BYTES)).hexdigest(),
            "raw_argmax_token_id": raw_id, "raw_argmax_score": scores[raw_id],
            "selected_token_id": selected, "selected_score": scores[selected] if selected is not None else None,
            "selection_performed": selected is not None,
            "selection_overrode_raw_argmax": selected is not None and selected != raw_id,
            "tokens_appended": int(selected is not None), "tie_breaker": "lowest_token_id",
            "codec_sha256": snapshot["expected_codec_sha256"], "context_raw_sha256": snapshot["expected_context_sha256"],
            "context_sha256": prefix["context_sha256"], "catalog_sha256": prefix["catalog_sha256"],
            "owner_pins": [{"path": name, "bytes": value[1][3], "sha256": value[0]}
                           for name, value in sorted(loaded[2].items())],
            "logits_origin_verified": False, "head_compatibility_qualified": False,
            "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "limitations": list(_LIMITATIONS)}
        return old._detach(result, MAX_REPORT_BYTES)
    except BaseException as error:
        failure = error
        raise
    finally:
        _finish(failure, fence)


__all__ = ["CompactCatalogSelectionError", "select_compact_catalog_token_v1"]
