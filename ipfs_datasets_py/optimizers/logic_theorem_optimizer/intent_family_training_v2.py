"""Source-bound Intent recipes for independent native family projection heads.

The input is an exact instruction and its native rich AST. These heads learn
typed projection feature reconstruction; they neither replace nor initialize
the separate paired-copy source decoder. Complete source/AST aliases are held
apart across fitting and selection, while atoms may recur in new compounds.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import re
import stat

from . import domain_family_training_v2 as common
from . import autoencoder_family_training_v2 as numerical
from . import autoencoder_family_training as codec
from . import autoencoder_paired_copy as copy_codec
from ...logic.formalization.autoencoder import family_training_v2 as native
from ...logic.intent_ir.formalize import rich_grammar as grammar

SCHEMA = "domain-native-family-training/prepared-v3"
DOMAINS = frozenset((*common.DOMAINS, "intent_ir"))
FALSE = dict(common.FALSE, source_text_decoded=False, source_training_executed=False,
             formulas_generated=False, test_used_for_fit_or_selection=False,
             lake_executed=False, roundtrip_ok=False)
_require, _raw, _sha = common._require, common._raw, common._sha
_BASE_MODULES = (common, numerical, codec, copy_codec, native, native.core, grammar)


def _identity(path):
    info = Path(path).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


_SOURCE_PATHS = {"intent_recipe": Path(__file__),
                 "shared_domain_facade": Path(__file__).with_name("domain_family_training_prepared.py"),
                 **{module.__name__: Path(module.__file__) for module in _BASE_MODULES}}
_IDENTITIES = {name: _identity(path) for name, path in _SOURCE_PATHS.items()}
_SOURCE_HASHES = {name: _sha(path.read_bytes()) for name, path in _SOURCE_PATHS.items()}


def _guard():
    _require({name: _identity(path) for name, path in _SOURCE_PATHS.items()} == _IDENTITIES,
             "Intent family producer changed since import")


_guard()


def _backend(name):
    _require(name in {"v2", "prepared"}, "explicit supported numerical_backend required")
    if name == "v2":
        return numerical, numerical.train_family_projection_autoencoder_v2, numerical.infer_family_projection_autoencoder_v2
    module = importlib.import_module(".autoencoder_family_training_prepared", package=__package__)
    return module, module.train_family_projection_autoencoder_prepared, module.infer_family_projection_autoencoder_prepared


def _pins(backend):
    _guard()
    module = _backend(backend)[0]
    return {**_SOURCE_HASHES, "selected_numerical_backend": _sha(Path(module.__file__).read_bytes())}


def _read_bytes(path):
    path = Path(path)
    _require(path.is_absolute() and path.resolve() == path, "canonical Intent artifact path required")
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_size <= common.MAX_BYTES, "bounded regular Intent artifact required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(common.MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    _require(len(raw) <= common.MAX_BYTES and identity(before) == identity(opened) == identity(after) == _identity(path),
             "Intent artifact changed during bounded read")
    return raw


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate Intent artifact JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite Intent artifact")))


def _inventory(bindings):
    fields = {"source_ids": "source_id", "groups": "group_id", "source_content_sha256": "source_content_sha256",
              "typed_source_digests": "typed_source_digest", "tokenized_sources": "tokenized_source_sha256",
              "complete_semantic_targets": "complete_semantic_sha256"}
    return {key: sorted({row[field] for row in bindings}) for key, field in fields.items()}


def prepare_intent_family_rows_v2(rows, *, role="training", requested_families=None):
    """Prepare actual Intent projections; readiness is never source truth or proof.

    ``inputs`` contains ``document`` (a rich AST) and exact ``source_text``;
    optional ``context`` and source-bound ``supplemental_inputs`` retain native
    owners. Split declarations are caller provenance, not inferred from text.
    """
    _guard()
    roles = {"training": {"train"}, "validation": {"validation", "valid", "tuning"},
             "inference": {"train", "validation", "valid", "tuning", "test", "canary", "inference"}}
    _require(role in roles and type(rows) in (tuple, list) and 1 <= len(rows) <= 384,
             "bounded nonempty Intent rows and explicit data role required")
    reports, bindings = [], []
    seen_ids, seen_content = set(), set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"source_id", "group_id", "split", "inputs"},
                 "closed Intent source/group/split/inputs row required")
        _require(all(type(row[key]) is str and 0 < len(row[key]) <= 512 for key in ("source_id", "group_id", "split")),
                 "bounded explicit Intent source/group/split identity required")
        _require(row["split"] in roles[role], "test/canary rows cannot enter Intent fitting or selection")
        _require(row["source_id"] not in seen_ids, "duplicate Intent source identity")
        inputs = row["inputs"]
        _require(type(inputs) is dict and {"document", "source_text"} <= set(inputs)
                 <= {"document", "source_text", "context", "supplemental_inputs"}, "Intent native input fields differ")
        text, document = inputs["source_text"], inputs["document"]
        _require(type(text) is str and text.strip() and len(text.encode()) <= 1048576,
                 "bounded exact Intent source text required")
        _require(type(document) is dict and "kind" in document, "rich native Intent AST required")
        ast = grammar.validate_ast(document)
        content = _sha(text.encode())
        _require(content not in seen_content, "duplicate exact Intent source content")
        # Native target preparation verifies complete source/AST agreement.
        report = native.prepare_family_training_targets_v2("intent_ir", requested_families=requested_families, **inputs)
        _require(any(item["ready_for_training"] for item in report["projections"]),
                 "each Intent source requires at least one ready actual native target")
        reports.append(report)
        bindings.append(dict(source_id=row["source_id"], group_id=row["group_id"], split=row["split"],
            source_content_sha256=content, typed_source_digest=report["source_digest"],
            tokenized_source_sha256=_sha(_raw(copy_codec.tokenize(grammar.model_input(text)))),
            complete_semantic_sha256=_sha(grammar.ast_to_sequence(ast).encode())))
        seen_ids.add(row["source_id"]); seen_content.add(content)
    _guard()
    return {"reports": reports, "bindings": bindings, "inventory": _inventory(bindings)}


def _read(descriptor):
    _guard()
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
             and descriptor["schema"] == SCHEMA and type(descriptor["sha256"]) is str
             and re.fullmatch(r"[a-f0-9]{64}", descriptor["sha256"]), "closed pinned Intent recipe descriptor required")
    raw = _read_bytes(descriptor["path"])
    _require(_sha(raw) == descriptor["sha256"], "Intent recipe drift")
    saved = _json(raw)
    _require(type(saved) is dict and saved.get("schema") == SCHEMA and saved.get("domain_id") in DOMAINS
             and all(saved.get(key) is False for key in FALSE), "Intent recipe schema or authority differs")
    _require(saved.get("producer") == _pins(saved.get("numerical_backend")), "Intent recipe producer differs")
    targets = _read_bytes(Path(descriptor["path"]).parent / "targets.json")
    _require(_sha(targets) == saved["targets_sha256"], "Intent target artifact drift")
    common._exclude(saved["training_history"], saved["validation_inventory"])
    _require(saved["status"] in {"complete", "partial"}, "invalid Intent recipe stage")
    _require((saved["status"] == "complete") == (saved["family_descriptor"] is not None and saved["family_error"] is None),
             "Intent completion receipt differs")
    if saved["family_descriptor"] is not None:
        checkpoint, _ = _backend(saved["numerical_backend"])[0]._read(saved["family_descriptor"])
        _require(checkpoint["space"]["domain_id"] == saved["domain_id"], "family checkpoint belongs to another domain")
    return saved


def _prepare_domain(domain_id, rows, *, role="training", requested_families=None):
    _require(domain_id in DOMAINS, "supported native IR domain required")
    if domain_id == "intent_ir":
        return prepare_intent_family_rows_v2(rows, role=role, requested_families=requested_families)
    return common.prepare_domain_family_rows_v2(domain_id, rows, role=role, requested_families=requested_families)


def _train_domain(domain_id, training_rows, validation_rows, *, output_dir,
        parent_descriptor=None, requested_families=None, numerical_backend="v2", **settings):
    """Continue a separate structural head with frozen selection and source pins."""
    _guard()
    _require(domain_id in DOMAINS, "supported native IR domain required")
    backend, train, _ = _backend(numerical_backend)
    _require(not set(settings) - common.SETTINGS, "unknown numerical family setting")
    output = Path(output_dir)
    _require(output.is_absolute() and output.resolve() == output and not output.exists(), "fresh canonical Intent output required")
    producer = _pins(numerical_backend)
    parent = _read(parent_descriptor) if parent_descriptor is not None else None
    families = list(requested_families) if requested_families is not None else None
    if parent is not None:
        _require(parent["domain_id"] == domain_id, "domain checkpoint identity differs")
        _require(parent["numerical_backend"] == numerical_backend, "Intent continuation numerical backend differs")
        _require(parent["requested_families"] == families, "Intent family selection changed on continuation")
        _require(parent["status"] == "complete", "completed Intent parent required for continuation")
        _require(not output.is_relative_to(Path(parent_descriptor["path"]).parent), "Intent continuation requires isolated output namespace")
    training = _prepare_domain(domain_id, training_rows, requested_families=requested_families)
    validation = _prepare_domain(domain_id, validation_rows, role="validation", requested_families=requested_families)
    history = training["inventory"]
    if parent is not None:
        _require(parent["validation_inventory"] == validation["inventory"], "original fixed Intent validation panel required")
        history = common._merge(history, parent["training_history"])
    common._exclude(history, validation["inventory"])
    _require(_pins(numerical_backend) == producer, "Intent producer changed during prevalidation")
    output.mkdir(parents=True)
    targets_sha = common._save(output / "targets.json", {"training": training["reports"], "validation": validation["reports"]})
    receipt = dict(schema=SCHEMA, domain_id=domain_id, numerical_backend=numerical_backend, producer=producer,
        status="partial", family_descriptor=None, family_error=None, family_training_report=None,
        parent_descriptor=deepcopy(parent_descriptor), requested_families=families, targets_sha256=targets_sha,
        training_history=history, validation_inventory=validation["inventory"],
        training_bindings=training["bindings"], validation_bindings=validation["bindings"],
        source_model_reinitialized=False, source_stage="not_requested",
        split_alias_policy=("full tokenized sources and complete canonical ASTs disjoint; shared compound atoms permitted"
            if domain_id == "intent_ir" else "unchanged domain-v2 source/group/content/typed-target exclusion"),
        objective_scope="typed native structural reconstruction; separate learned source decoder unchanged", **FALSE)
    path = output / "recipe.json"
    common._save(path, receipt)
    try:
        result = train(training["reports"], validation["reports"], output_dir=output / "family",
                       parent_descriptor=parent["family_descriptor"] if parent else None, **settings)
        _require(_pins(numerical_backend) == producer, "Intent producer changed during optimization")
        _require(result["report"]["training_executed"], "Intent family optimization completed no fitting work")
        receipt.update(status="complete", family_descriptor=result["descriptor"], family_training_report=result["report"])
    except Exception as error:
        receipt.update(family_error={"type": type(error).__name__, "message": str(error)[:2000]})
    digest = common._save(path, receipt, replace=True)
    return {"descriptor": {"schema": SCHEMA, "path": str(path), "sha256": digest}, "report": receipt}


def _infer_domain(descriptor, rows, *, expected_domain=None):
    saved = _read(descriptor)
    _require(expected_domain is None or saved["domain_id"] == expected_domain, "domain checkpoint identity differs")
    _require(saved["status"] == "complete", "complete Intent native family stage required for inference")
    prepared = _prepare_domain(saved["domain_id"], rows, role="inference", requested_families=saved["requested_families"])
    result = _backend(saved["numerical_backend"])[2](saved["family_descriptor"], prepared["reports"])
    _require(_pins(saved["numerical_backend"]) == saved["producer"], "Intent producer changed during inference")
    return dict(schema=SCHEMA, domain_id=saved["domain_id"], checkpoint=deepcopy(descriptor),
                input_bindings=prepared["bindings"], native_inference=result, training_steps=0, **FALSE)


def train_intent_family_autoencoder_v2(training_rows, validation_rows, **kwargs):
    """Train an Intent-only structural head; the source decoder stays separate."""
    return _train_domain("intent_ir", training_rows, validation_rows, **kwargs)


def infer_intent_family_autoencoder_v2(descriptor, rows):
    """Decode Intent structural features with zero training or source decoding."""
    return _infer_domain(descriptor, rows, expected_domain="intent_ir")


__all__ = ["prepare_intent_family_rows_v2", "train_intent_family_autoencoder_v2",
           "infer_intent_family_autoencoder_v2", "SCHEMA"]
