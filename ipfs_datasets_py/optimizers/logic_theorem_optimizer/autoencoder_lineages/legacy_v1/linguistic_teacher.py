"""Preserved vector teacher with separately screened compiler supervision.

The old sparse model and linguistic IR stay unchanged. Symbolic repairs are
explicitly produced by the pinned canonical compiler, never attributed to a
learned formula decoder. Candidate masks do not confer semantic qualification
or Lean admission. Unknown and unsupported sources retain diagnostic evidence.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import re
import threading
import time

from .linguistic import LinguisticAutoencoder

SCHEMA = "legacy-linguistic-teacher/v1"
POLICY = "single-direct-norm-compiler-supervision/v1"
FALSE = {"admitted": False, "formalized": False, "roundtrip_ok": False,
         "semantic_qualification": False, "formula_fidelity_verified": False,
         "independent_formula_generation": False, "lake_executed": False}
_MODAL = re.compile(r"\b(?:shall|must|may)\b", re.I)
_DIRECT = re.compile(r"(?P<actor>.+?)\s+(?P<modal>shall|must|may)\s+(?P<negative>not\s+)?(?P<body>.+)", re.I)
_NO_DUTY = re.compile(r"\b(?:not|never)\s+(?:be\s+)?(?:required|obliged|obligated|permitted|allowed)\b|\bnotwithstanding\b|\bno\s+(?:duty|obligation|requirement|authority)\b", re.I)
_DURATION = re.compile(r"\b(?:within|after|before|for(?:\s+at\s+least)?)\s+\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b", re.I)
_NUMBERS = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_PRODUCERS = (
    "ipfs_datasets_py.logic.autoformal",
    "ipfs_datasets_py.logic.autoformal.semantic_integrity",
    "ipfs_datasets_py.logic.legal_ir.canonical_compiler",
    "ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
    "ipfs_datasets_py.logic.legal_ir.canonical_contracts",
    "ipfs_datasets_py.logic.deontic.utils.deontic_parser",
    __name__,
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _surface(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _actor(value):
    return re.sub(r"^(?:the|a|an)\s+", "", _surface(value))


def _stat(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _source_reasons(text, corpus):
    from ipfs_datasets_py.logic.autoformal.semantic_integrity import unsupported_source_grammar
    reasons = unsupported_source_grammar(text)
    if corpus not in {"us_code", "authored_fixture"}:
        reasons.append("constitution_not_formalized" if corpus == "constitution" else "unverified_source_corpus")
    if _NO_DUTY.search(text):
        reasons.append("unsupported_negated_or_overriding_norm")
    if any(char in text for char in ('"', '“', '”', ';', '\n')):
        reasons.append("unsupported_quoted_or_multiclause_scope")
    if len(_MODAL.findall(text)) != 1:
        reasons.append("requires_one_direct_norm")
    direct = _DIRECT.fullmatch(text.strip().rstrip("."))
    if direct is None:
        reasons.append("unsupported_direct_norm_shape")
    else:
        if direct["modal"].lower() == "may" and direct["negative"]:
            reasons.append("ambiguous_may_not")
        if re.search(r"\bnot\s+only\b", text, re.I):
            reasons.append("unsupported_not_only_scope")
        if re.search(r"\b(?:and|or)\b", direct["body"], re.I):
            reasons.append("unsupported_coordinated_scope")
        if re.search(r"\b(?:only|without|provided|subject\s+to)\b", direct["body"], re.I):
            reasons.append("unsupported_restrictive_or_nested_scope")
        # The minimum-duration sidecar is explicitly represented. Other
        # object quantifiers need a scoped FOL target rather than a string atom.
        unscoped_body = re.sub(r"\bfor\s+at\s+least\s+\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b",
                              "", direct["body"], flags=re.I)
        if re.search(r"\b(?:at\s+least|at\s+most|exactly|every|each|all|any|some)\b", unscoped_body, re.I):
            reasons.append("unsupported_quantifier_scope")
        if re.search(r"\b(?:if|unless|except|when|provided|before|after|nothing)\b", direct["actor"], re.I):
            reasons.append("unsupported_leading_scope")
        if re.search(r"[.!?]\s+\S", text):
            reasons.append("unsupported_multiple_sentences")
        if direct["body"].lower().startswith(("be construed", "be deemed", "be considered", "be permitted", "be allowed", "be entitled")):
            reasons.append("unsupported_interpretive_norm")
    return list(dict.fromkeys(reasons)), direct


class LegacyLinguisticTeacher:
    """Read-only teacher observations around an explicitly selected 8D model.

    Pass a baseline or cached LinguisticAutoencoder. Train that model using its
    original API; this adapter never changes samples, weights or loss functions.
    Its bounded cache stores compiler targets, not model predictions or weights.
    """

    def __init__(self, model, *, max_target_entries=128, max_target_bytes=4 * 1024 * 1024):
        if not isinstance(model, LinguisticAutoencoder):
            raise TypeError("teacher requires the preserved 8D linguistic profile")
        if any(type(value) is not int or value < 0 for value in (max_target_entries, max_target_bytes)):
            raise ValueError("target cache bounds must be nonnegative integers")
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        self.tree_pin = require_workspace_logic_tree()
        self.model = model
        self.max_target_entries, self.max_target_bytes = max_target_entries, max_target_bytes
        self._targets, self._target_bytes = OrderedDict(), 0
        self._validated_samples = OrderedDict()
        self._lock = threading.RLock()
        self._paths = {name: Path(importlib.import_module(name).__file__).resolve() for name in _PRODUCERS}
        self.source_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in self._paths.items()}
        self._identities = {name: _stat(path) for name, path in self._paths.items()}
        self.producer_sha256 = _hash(_json(self.source_hashes))

    def _require_sources(self):
        if any(_stat(path) != self._identities[name] for name, path in self._paths.items()):
            self._targets.clear()
            self._target_bytes = 0
            self._validated_samples.clear()
            raise RuntimeError("teacher producer source changed; start a fresh process before resuming")

    def _validate_sample(self, sample):
        """Do not distill forged parser features merely sharing a source ID."""
        digest = _hash(_json(sample.to_dict()))
        if digest in self._validated_samples:
            self._validated_samples.move_to_end(digest)
            return digest
        rebuilt = self.model.build_sample(title=sample.title, section=sample.section,
                                          text=sample.text, citation=sample.citation)
        if rebuilt.to_dict() != sample.to_dict():
            raise ValueError("teacher input differs from the selected profile's source-derived sample")
        if self.max_target_entries:
            self._validated_samples[digest] = True
            while len(self._validated_samples) > self.max_target_entries:
                self._validated_samples.popitem(last=False)
        return digest

    def _prepare(self, sample, corpus):
        from ipfs_datasets_py.logic.autoformal import vocabulary_from_clause, _temporal_records
        from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
        from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest, OperationStatus
        from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule

        text = sample.text
        reasons, direct = _source_reasons(text, corpus)
        result = {"status": "not_run", "rules": [], "decompiled_texts": [], "temporal_records": [],
                  "timings": {}, "vocabulary": None, "cycle_equal": False,
                  "origin": "pinned_canonical_compiler", "vocabulary_source": "parser_string_atoms"}
        if reasons:
            return {"compiler": result, "reasons": reasons, "candidate": False}
        started = time.perf_counter()
        vocabulary = vocabulary_from_clause(text)
        result["timings"]["vocabulary_seconds"] = time.perf_counter() - started
        result["vocabulary"] = vocabulary
        if not vocabulary:
            return {"compiler": result, "reasons": ["no_parser_atoms"], "candidate": False}
        if not all(isinstance(atom, str) for atoms in vocabulary.values() for atom in atoms):
            raise ValueError("canonical compiler vocabulary must contain parser-supplied strings")
        compiler = TypedDeonticCanonicalCompiler()
        started = time.perf_counter()
        compiled = compiler.compile(CompilerRequest(text, sample.sample_id,
                                    CanonicalAtomVocabulary(**vocabulary), allow_explicit_partial=False))
        result["timings"]["compiler_seconds"] = time.perf_counter() - started
        result["status"] = compiled.status.value
        result["receipt"] = compiled.to_dict()
        if compiled.status is not OperationStatus.SUCCESS or compiled.canonical_ir is None or compiled.unsupported_semantics:
            return {"compiler": result, "reasons": ["canonical_compiler_abstained_or_partial"], "candidate": False}
        rules = [rule.to_dict() for rule in compiled.canonical_ir.rules]
        result["rules"] = rules
        result["decompiled_texts"] = [decompile_rule(rule) for rule in compiled.canonical_ir.rules]
        if len(rules) != 1:
            return {"compiler": result, "reasons": ["requires_one_compiled_rule"], "candidate": False}
        rule = rules[0]
        assert direct is not None
        expected_modality = "F" if direct["negative"] else "P" if direct["modal"].lower() == "may" else "O"
        if rule["modality"] != expected_modality:
            reasons.append("canonical_modality_disagrees_with_direct_norm")
        if _actor(direct["actor"]) != _actor(rule["actor"]):
            reasons.append("canonical_actor_not_preserved")
        if not _surface(direct["body"]).startswith(_surface(rule["action"]) + " "):
            reasons.append("canonical_action_not_preserved")
        if re.search(r"\b(?:unless|except)\b", text, re.I) and not rule["exceptions"]:
            reasons.append("exception_not_preserved")
        if re.search(r"\bif\b", text, re.I) and not rule["conditions"]:
            reasons.append("condition_not_preserved")
        semantic_surface = " ".join(str(value) for value in (
            rule["actor"], rule["action"], rule["object"], *rule["conditions"], *rule["exceptions"], *rule["temporal"]))
        source_numbers, target_numbers = set(_NUMBERS.findall(text)), set(_NUMBERS.findall(semantic_surface.replace("_", " ")))
        if source_numbers != target_numbers:
            reasons.append("numeric_semantics_not_preserved")
        started = time.perf_counter()
        temporal = _temporal_records(text)
        result["timings"]["temporal_seconds"] = time.perf_counter() - started
        result["temporal_records"] = temporal
        if temporal and not rule["temporal"]:
            reasons.append("temporal_semantics_not_explicit")
        if _DURATION.search(text) and not rule["temporal"]:
            reasons.append("temporal_semantics_not_explicit")
        if len(temporal) > 1:
            reasons.append("unsupported_multiple_temporal_scopes")
        for record in temporal:
            if record["temporal_kind"] not in {"within_duration", "minimum_duration", "after_duration", "before_duration", "duration"}:
                reasons.append("unsupported_temporal_kind")
        # This exact cycle is necessary target preservation, never a source-law proof.
        if not reasons:
            started = time.perf_counter()
            decompiled = result["decompiled_texts"][0]
            # Preserve the source parser's closed atom vocabulary across the
            # cycle. Regenerating it from sentence-capitalized rendering would
            # turn e.g. agency into Agency and measure a different IR identity.
            cycle = compiler.compile(CompilerRequest(decompiled, sample.sample_id + ":teacher-cycle",
                                     CanonicalAtomVocabulary(**vocabulary), allow_explicit_partial=False))
            result["cycle_equal"] = (cycle.status is OperationStatus.SUCCESS and not cycle.unsupported_semantics
                and cycle.canonical_ir is not None and cycle.canonical_ir.ir_cid == compiled.canonical_ir.ir_cid)
            result["cycle_status"] = cycle.status.value
            result["cycle_vocabulary_source"] = "same_original_parser_string_atoms"
            if not result["cycle_equal"]:
                reasons.append("canonical_cycle_not_preserved")
            result["timings"]["cycle_seconds"] = time.perf_counter() - started
        return {"compiler": result, "reasons": list(dict.fromkeys(reasons)), "candidate": not reasons}

    def _target(self, sample, corpus):
        key = (sample.sample_id, sample.text, sample.citation, sample.source, corpus)
        cached = self._targets.get(key)
        if cached is not None:
            self._targets.move_to_end(key)
            return deepcopy(cached[0]), True
        value = self._prepare(sample, corpus)
        size = len(_json(value).encode()) + sum(len(str(part).encode()) for part in key)
        if self.max_target_entries and size <= self.max_target_bytes:
            while self._targets and (len(self._targets) >= self.max_target_entries or self._target_bytes + size > self.max_target_bytes):
                _, (_, removed) = self._targets.popitem(last=False)
                self._target_bytes -= removed
            self._targets[key] = deepcopy(value), size
            self._target_bytes += size
        return value, False

    def observe(self, sample, *, corpus="unknown"):
        if corpus not in {"us_code", "authored_fixture", "constitution", "unknown"}:
            raise ValueError("unrecognized teacher corpus")
        if not isinstance(sample.text, str) or not 0 < len(sample.text) <= 8192:
            raise ValueError("teacher observations require a nonempty span of at most 8192 characters")
        started = time.perf_counter()
        with self._lock:
            self._require_sources()
            self.model._samples([sample])
            from ._snapshot.legal_modal_parser import LegalModalParser
            normalized = LegalModalParser().normalize_text(sample.text)
            if (sample.normalized_text != normalized or sample.modal_ir.normalized_text != normalized
                    or sample.modal_ir.document_id != sample.sample_id):
                raise ValueError("teacher model input IR must bind the same normalized source and sample identity")
            sample_digest = self._validate_sample(sample)
            historical = self.model.linguistic_observation(sample)
            encoded = self.model.encode(sample, use_sample_memory=False)
            vector = self.model.decode(encoded)
            prepared, cache_hit = self._target(sample, corpus)
            self._require_sources()
            canonical = prepared["compiler"]
            description = self.model.describe()
            old_formulas = historical["modal_ir"]["formulas"]
            operators = sorted({f["operator"]["symbol"] for f in old_formulas if f["operator"]["family"] == "deontic"})
            changes = []
            if len(canonical["rules"]) == 1:
                rule = canonical["rules"][0]
                if operators != [rule["modality"]]:
                    changes.append({"field": "deontic_operator", "historical": operators, "compiler": rule["modality"]})
                if rule["temporal"]:
                    changes.append({"field": "explicit_temporal", "compiler": rule["temporal"],
                                    "temporal_records": canonical["temporal_records"]})
            return {"schema": SCHEMA, "policy": POLICY, "sample_id": sample.sample_id,
                    "source_binding": {"sha256": _hash(sample.text), "corpus": corpus,
                                       "citation": sample.citation, "producer_sha256": self.producer_sha256,
                                       "sample_sha256": sample_digest},
                    "model_binding": {
                        "lineage_id": description["lineage_id"],
                        "training_profile": description.get("training_profile"),
                        "runtime_profile": description.get("runtime_profile"),
                        "linguistic_identity": description.get("linguistic_identity"),
                        "linguistic_identity_sha256": description.get("linguistic_identity_sha256"),
                        "initial_checkpoint_identity": description.get("checkpoint_identity"),
                        "current_weights_reverified": False,
                        "scope": "verified input/profile and initial checkpoint when loaded; not a new per-row weight attestation"},
                    "model_lineage": self.model.LINEAGE_ID,
                    "teacher_vector": vector, "vector_origin": "preserved_8d_target_aware_sparse_model",
                    "family_distribution": encoded.get("family_distribution", {}),
                    "semantic_embedding_verified": False, "sample_memory_used": False,
                    "historical_linguistic_ir": historical["modal_ir"],
                    "compiler": canonical,
                    "corrected_ir": {"rules": canonical["rules"]},
                    "corrected_ir_origin": "canonical_compiler_supervision_not_neural_generation",
                    "changes": changes, "reasons": prepared["reasons"],
                    "status": "compiler_supervised_candidate" if prepared["candidate"] else "feature_only",
                    "distillation_mask": {"feature_vector": True, "historical_formula": False,
                                          "compiler_supervised_formula": prepared["candidate"]},
                    "unqualified_families": sorted({f["operator"]["family"] for f in old_formulas}),
                    "target_cache_hit": cache_hit,
                    "target_cache": {"entries": len(self._targets), "retained_payload_bytes": self._target_bytes,
                                     "max_entries": self.max_target_entries, "max_payload_bytes": self.max_target_bytes},
                    "elapsed_seconds": time.perf_counter() - started,
                    "full_source_equivalence_proved": False, **FALSE}

    def distillation_row(self, sample, *, corpus="unknown"):
        observation = self.observe(sample, corpus=corpus)
        # Unsafe historical formulas remain in evidence, never the training target.
        return {"schema": SCHEMA + "/distillation", "sample_id": sample.sample_id,
                "source_text": sample.text, "source_binding": observation["source_binding"],
                "feature_target": observation["teacher_vector"],
                "formula_target": observation["corrected_ir"] if observation["distillation_mask"]["compiler_supervised_formula"] else None,
                "formula_target_origin": observation["corrected_ir_origin"],
                "distillation_mask": observation["distillation_mask"],
                "evidence": observation, **FALSE}


__all__ = ["LegacyLinguisticTeacher", "SCHEMA", "POLICY"]
