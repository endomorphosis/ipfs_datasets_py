"""Add concrete AST certificates to an unchanged V2 definition-use corpus.

The original source/review preparation keeps its own public validator. Each
native fragment keeps the standalone preservation owner's reification and
semantics. This adapter shares the original corpus Interpretation and targets
the original formula declarations directly. Preparation performs no native
execution and grants no source, legal, review, model or corpus authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "legal-corpus-v2-definition-use-preservation-preparation/v1"
PROFILE = "replayed-v2-corpus-four-fragment-concrete-preservation/v1"
INPUT_SCHEMA = "legal-corpus-v2-definition-use-preservation-inputs/v1"
REFERENCE_SCHEMA = "legal-corpus-v2-preservation-engineering-reference/v1"
PROJECT_ROOT = "LegalCorpusV2Preservation"
MAX_RECORD_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_FILES = 16
MAX_MODULES = 12
MAX_THEOREMS = 15
ROLES = ("donor", "consumer", "alias", "joint")
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+\Z")
_CORPUS_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2"
_REVIEW_FIELDS = frozenset({
    "subject", "registry", "policy", "reviews", "dependency_manifest",
    "component_raw", "expected_component_pin", "use_inputs",
    "expected_subject_sha256", "expected_registry_sha256",
    "expected_policy_sha256", "expected_reviews_sha256",
    "expected_manifest_sha256", "at_time_utc", "observed_artifact_sha256s",
    "observed_pins", "evidence_artifacts",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified",
        "source_to_model_equivalence_proved", "source_fidelity_proved",
        "applicability_verified", "context_closure_verified", "independently_reviewed",
        "human_identity_verified", "human_independence_verified", "meaning_admitted",
        "admitted", "formalized", "semantic_graph_admitted", "proof_authority",
        "proof_checked", "kernel_proofs_checked", "conditional_proofs_verified",
        "translation_preservation_proved", "cross_family_equivalence_verified",
        "general_emitter_preservation_proved", "json_bytes_parser_verified",
        "model_convergence_proved", "model_executed", "learned_translation",
        "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
        "Lean_admitted", "backend_executed", "lean_compilation_verified",
        "build_eligible", "native_build_profile_registered", "installed_toolchain_verified",
        "toolchain_probed", "native_ast_value_preservation_proved",
        "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
        "accepted_view_eligible", "combined_use_review_verified", "alias_assumption_proved",
        "legal_proof_cache_compatible", "proof_cache_admission_verified",
    ), False,
)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"),
    False,
)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "corpus preservation node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary corpus preservation JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "bounded corpus preservation text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid corpus preservation UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded corpus preservation integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite corpus preservation JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary corpus preservation input values required")
        _need(remaining >= 0, "complete corpus preservation input byte bound exceeded")

    visit(value, 0)
    return maximum - remaining


def _wire(value, maximum):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary corpus preservation JSON required") from error
    _need(len(raw) <= maximum, "complete corpus preservation JSON byte bound exceeded")
    return raw


def _parse(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum,
          "bounded original corpus preservation JSON bytes required")

    def pairs(items):
        value = {}
        for key, child in items:
            _need(key not in value, "duplicate corpus preservation JSON key")
            value[key] = child
        return value

    def constant(_):
        raise ValueError("nonfinite corpus preservation JSON constant refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite corpus preservation JSON required") from error
    _wire(value, maximum)
    return value


def _envelope(preparation, *, original=False):
    if original:
        cls = type(preparation)
        _need(cls.__module__ == _CORPUS_MODULE and cls.__name__ == "DefinitionUseCorpusPreparation",
              "original typed V2 corpus preparation required")
    else:
        _need(type(preparation) is DefinitionUsePreservationPreparation,
              "exact typed V2 corpus preservation preparation required")
    try:
        data = object.__getattribute__(preparation, "__dict__")
    except AttributeError as error:
        raise ValueError("closed immutable corpus preparation storage required") from error
    _need(type(data) is dict and set(data) == {"manifest_json", "files"},
          "closed original corpus preparation storage required")
    text, pairs = data["manifest_json"], data["files"]
    _need(type(text) is str and 0 < len(text) <= MAX_RECORD_BYTES,
          "bounded original corpus manifest text required")
    manifest = _parse(text.encode("utf-8"), MAX_RECORD_BYTES)
    _need(type(manifest) is dict, "original corpus manifest object required")
    _need(type(pairs) is tuple and len(pairs) == (9 if original else MAX_FILES),
          "complete exact corpus project file population required")
    names, files, total = [], [], 0
    for pair in pairs:
        _need(type(pair) is tuple and len(pair) == 2,
              "ordinary generated corpus preservation file pairs required")
        name, body = pair
        _need(type(name) is str and type(body) is str and len(name) <= 256
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name) is not None
              and all(part not in (".", "..") for part in name.split("/")),
              "closed two-level corpus preservation paths required")
        _need("\x00" not in body, "ordinary corpus preservation source text required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid corpus preservation source UTF8 required") from error
        _need(total <= (8 * MAX_RECORD_BYTES if original else MAX_PROJECT_BYTES),
              "complete corpus preservation project byte bound exceeded")
        names.append(name)
        files.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted corpus preservation files required")
    return {"manifest": manifest, "files": files}


def _preflight(corpus_preparation, assessment_raw, expected_corpus_preparation_sha256,
               expected_assessment_file_sha256, review_inputs, toolchain):
    _pin(expected_corpus_preparation_sha256, "complete original V2 corpus preparation")
    _pin(expected_assessment_file_sha256, "complete original V2 review assessment file")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "exact version-pinned corpus preservation Lean toolchain required")
    _need(type(assessment_raw) is bytes and 0 < len(assessment_raw) <= MAX_RECORD_BYTES,
          "bounded complete original V2 assessment bytes required")
    _need(_sha(assessment_raw) == expected_assessment_file_sha256,
          "original V2 assessment file pin differs")
    _parse(assessment_raw, MAX_RECORD_BYTES)
    envelope = _envelope(corpus_preparation, original=True)
    original_raw = _wire(envelope, 20 * MAX_RECORD_BYTES)
    _need(_sha(original_raw) == expected_corpus_preparation_sha256,
          "independent complete original V2 corpus preparation pin differs")
    _need(type(review_inputs) is dict and set(review_inputs) == _REVIEW_FIELDS,
          "closed complete original V2 review replay input object required")
    _bound_tree(review_inputs, MAX_INPUT_BYTES - len(original_raw) - len(assessment_raw), allow_bytes=True)
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "corpus preservation owner changed since import")
    return envelope


def _owners():
    from . import corpus_contracts, legal_corpus_definition_use_lake_v2
    from . import legal_corpus_definition_use_native_v2, legal_native_ast_preservation

    return (legal_corpus_definition_use_lake_v2,
            legal_corpus_definition_use_native_v2, legal_native_ast_preservation,
            corpus_contracts)


def _pins(owners, original, standalone):
    global _OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "corpus preservation owner changed since import")
    pins = dict(original["producer_pins"])
    pins.update(original["native_producer_pins"])
    # Retain the existing public corpus validator's own dependency inventory.
    pins.update(owners[1]._pins(owners[1]._owners(), original))
    for manifest in standalone:
        pins.update(manifest["producer_pins"])
        pins.update(manifest["native_producer_pins"])
    pins.update({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                 for module in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for path, expected in pins.items():
        _pin(expected, "corpus preservation producer")
        _need(_sha(Path(path).read_bytes()) == expected,
              "corpus preservation producer changed: " + path)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "corpus preservation operation owners changed since first use")
    return pins


@dataclass(frozen=True)
class DefinitionUsePreservationPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        _need(type(self.manifest_json) is str, "original corpus preservation manifest text required")
        value = _parse(self.manifest_json.encode("utf-8"), MAX_RECORD_BYTES)
        _need(type(value) is dict, "corpus preservation manifest object required")
        return value


def preparation_sha256(preparation):
    """Commit the complete canonical manifest and all sixteen generated files."""
    return _sha(_wire(_envelope(preparation), MAX_PREPARATION_BYTES))


def _original_state(manifest):
    return {
        "preparation_only": manifest["preparation_only"],
        "reported_flags": {key: value for key, value in manifest.items() if type(value) is bool},
        "review_evidence_status": manifest["review_evidence_status"],
        "review_blockers": manifest["review_blockers"],
        "review_prerequisites_satisfied_under_selected_trust": manifest[
            "review_prerequisites_satisfied_under_selected_trust"],
        "review_intake_binding": manifest["review_intake_binding"],
        "review_dependency_manifest": manifest["review_dependency_manifest"],
        "review_source_binding": manifest["review_source_binding"],
        "execution_handoff": manifest["execution_handoff"],
        "theorem_assumptions": manifest["theorem_assumptions"],
    }


def _certificate_body(preparation, fragment, original_module):
    """Transport the public standalone result; never implement another reifier."""
    manifest = preparation.to_dict()
    module = manifest["expected_modules"][2]
    source = dict(preparation.files)[module.replace(".", "/") + ".lean"]
    prefix = "import LegalNativeAstPreservation.Semantics\nnamespace " + module + "\n"
    suffix = "\nend " + module + "\n"
    _need(source.startswith(prefix) and source.endswith(suffix),
          "exact public standalone preservation instance wrapper required")
    body = source[len(prefix):-len(suffix)]
    native_body = fragment["lean_body"]
    _need(body.startswith(native_body + "\n"),
          "unchanged original native body prefix required before certificate transport")
    body = body[len(native_body):]
    target = "↔ formula_0 i t := by"
    _need(body.count(target) == 1, "one exact public standalone denotation theorem target required")
    return body.replace(target, "↔ " + original_module + ".formula_0 i t := by", 1)


def _file(module, imports, body):
    return ("".join("import " + name + "\n" for name in imports)
            + "namespace " + module + "\n" + body + "\nend " + module + "\n")


# Identical public replays inside one packet/index read share one preparation.
# The key covers the verified corpus pin and the full review tree, so a changed
# input, toolchain, or owner file misses and runs the corpus replay again.
_PREPARE_CACHE = {}
_PREPARE_CACHE_MAX = 4


def _tree_digest(value):
    digest = hashlib.sha256()

    def visit(item):
        kind = type(item)
        if kind is dict:
            digest.update(b"d")
            digest.update(str(len(item)).encode())
            for key in sorted(item):
                if type(key) is not str or visit(key) is False or visit(item[key]) is False:
                    return False
        elif kind is list or kind is tuple:
            digest.update(b"l" if kind is list else b"t")
            digest.update(str(len(item)).encode())
            for child in item:
                if visit(child) is False:
                    return False
        elif kind is str:
            raw = item.encode()
            digest.update(b"s")
            digest.update(str(len(raw)).encode())
            digest.update(raw)
        elif kind is bytes:
            digest.update(b"b")
            digest.update(str(len(item)).encode())
            digest.update(item)
        elif kind is bool:
            digest.update(b"t" if item else b"f")
        elif kind is int:
            digest.update(b"i")
            digest.update(str(item).encode())
        elif item is None:
            digest.update(b"n")
        elif kind is float:
            if not math.isfinite(item):
                return False
            digest.update(b"r")
            digest.update(repr(item).encode())
        else:
            return False
        return True

    if visit(value) is False:
        return None
    return digest.digest()


def _prepare_cache_key(expected_corpus_preparation_sha256, expected_assessment_file_sha256,
                       review_inputs, toolchain, owners):
    review = _tree_digest(review_inputs)
    if review is None:
        return None
    digest = hashlib.sha256()
    digest.update(expected_corpus_preparation_sha256.encode())
    digest.update(expected_assessment_file_sha256.encode())
    digest.update(toolchain.encode())
    digest.update(review)
    for module in owners:
        digest.update(Path(module.__file__).read_bytes())
    return digest.digest()


def _prepare_cache_get(key):
    cached = _PREPARE_CACHE.get(key)
    if cached is None:
        return None
    _PREPARE_CACHE.pop(key)
    _PREPARE_CACHE[key] = cached
    return cached


def _prepare_cache_put(key, preparation):
    _PREPARE_CACHE.pop(key, None)
    _PREPARE_CACHE[key] = preparation
    while len(_PREPARE_CACHE) > _PREPARE_CACHE_MAX:
        _PREPARE_CACHE.pop(next(iter(_PREPARE_CACHE)))


def prepare_definition_use_preservation_v2(corpus_preparation, assessment_raw, *,
        expected_corpus_preparation_sha256, expected_assessment_file_sha256,
        review_inputs, toolchain):
    """Replay the original corpus and add four directly targeted certificates."""
    original_envelope = _preflight(
        corpus_preparation, assessment_raw, expected_corpus_preparation_sha256,
        expected_assessment_file_sha256, review_inputs, toolchain)
    owners = _owners()
    cache_key = _prepare_cache_key(
        expected_corpus_preparation_sha256, expected_assessment_file_sha256,
        review_inputs, toolchain, owners)
    if cache_key is not None:
        cached = _prepare_cache_get(cache_key)
        if cached is not None:
            return cached
    _, corpus_native, standalone_owner, contracts = owners
    original = corpus_native.validate_definition_use_native_v2(
        corpus_preparation, assessment_raw,
        expected_preparation_sha256=expected_corpus_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    original_manifest = original.to_dict()
    _need(original_manifest["toolchain"] == toolchain,
          "original and preservation toolchains differ")
    rows = original_manifest["native_fragments"]
    _need(type(rows) is list and [row["role"] for row in rows] == list(ROLES),
          "exact original donor/consumer/alias/joint fragment population required")
    standalone = []
    for row in rows:
        raw = _wire(row["native"], MAX_RECORD_BYTES)
        prepared = standalone_owner.prepare_native_ast_preservation(
            raw, expected_fragment_file_sha256=_sha(raw), toolchain=toolchain)
        standalone_owner.validate_native_ast_preservation(
            prepared, raw, expected_preparation_sha256=standalone_owner.preparation_sha256(prepared),
            expected_fragment_file_sha256=_sha(raw), toolchain=toolchain)
        standalone.append((row, raw, prepared))
    producers = _pins(owners, original_manifest, [item[2].to_dict() for item in standalone])
    original_files = dict(original.files)
    files = dict(original_files)
    semantics_module = "LegalCorpusV2.PreservationSemantics"
    modules = list(original_manifest["expected_modules"]) + [semantics_module]
    imports = {name: list(values) for name, values in original_manifest["module_imports"].items()}
    imports[semantics_module] = ["LegalCorpusV2.Prelude"]
    semantics = standalone_owner.SEMANTICS
    files[semantics_module.replace(".", "/") + ".lean"] = _file(
        "LegalCorpusV2", imports[semantics_module], semantics)
    fragments, preservation_theorems = [], []
    for row, raw, prepared in standalone:
        native, source_module = row["native"], row["module"]
        own_manifest = prepared.to_dict()
        standalone_pin = standalone_owner.preparation_sha256(prepared)
        module = "LegalCorpusV2.Preservation" + row["role"].title() + _sha(_wire({
            "profile": PROFILE,
            "original_corpus_preparation_sha256": expected_corpus_preparation_sha256,
            "role": row["role"], "original_module": source_module,
            "standalone_preparation_sha256": standalone_pin,
        }, MAX_RECORD_BYTES))
        modules.append(module)
        imports[module] = [source_module, semantics_module]
        body = _certificate_body(prepared, native, source_module)
        path = module.replace(".", "/") + ".lean"
        files[path] = _file(module, imports[module], body)
        theorem_names = [module + "." + suffix for suffix in (
            "native_value_exact", "native_ast_closed", "denotation_matches_native")]
        preservation_theorems.extend(theorem_names)
        fragments.append({
            "role": row["role"], "original_module": source_module,
            "preservation_module": module, "theorems": theorem_names,
            "target_declaration": source_module + ".formula_0",
            "fragment_file_sha256": _sha(raw),
            "native_fragment_canonical_sha256": _sha(_wire(native, MAX_RECORD_BYTES)),
            "formula_sha256": _sha(native["formula"].encode()),
            "native_ast_sha256": _sha(_wire(native["native_ast"], MAX_RECORD_BYTES)),
            "lean_body_sha256": _sha(native["lean_body"].encode()),
            "original_module_source_sha256": _sha(original_files[source_module.replace(".", "/") + ".lean"].encode()),
            "preservation_module_source_sha256": _sha(files[path].encode()),
            "standalone_preparation_full_canonical_sha256": standalone_pin,
            "standalone_preparation_cid": own_manifest["record_cid"],
            "semantics_sha256": own_manifest["semantics_sha256"],
            "prelude_sha256": own_manifest["prelude_sha256"],
        })
    imports[PROJECT_ROOT] = ["LegalCorpusV2", *(row["preservation_module"] for row in fragments)]
    modules.append(PROJECT_ROOT)
    files[PROJECT_ROOT + ".lean"] = "".join("import " + name + "\n" for name in imports[PROJECT_ROOT])
    files["lakefile.toml"] = 'name = "legal_corpus_v2_definition_use_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCorpusV2", "LegalCorpusV2Preservation"]\n'
    original_state = _original_state(original_manifest)
    conditional_theorems = list(original_manifest["conditional_theorems"])
    theorems = conditional_theorems + preservation_theorems
    reference_key = {
        "scope": "exact_engineering_observation_only",
        "profile": PROFILE, "toolchain": toolchain,
        "original_corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
        "assessment_file_sha256": expected_assessment_file_sha256,
        "component_pin": original_manifest["review_intake_binding"]["component_pin"],
        "review_dependency_manifest_sha256": original_manifest["review_dependency_manifest"]["manifest_sha256"],
        "semantics_sha256": _sha(semantics.encode()),
        "preservation_fragments": fragments, "theorems": theorems,
        "producer_pins": producers,
    }
    reference = contracts.seal_record({
        "schema": REFERENCE_SCHEMA, "scope": "exact_engineering_observation_only",
        "reference_key_sha256": _sha(_wire(reference_key, MAX_RECORD_BYTES)),
        "key_material": reference_key,
        "cache_namespace": "legal_ir_concrete_native_engineering",
        "requires_successful_exact_native_receipt": True,
        "legal_proof_cache_compatible": False, "proof_cache_admission_verified": False,
        "proof_checked": False, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
    })
    files["preservation-inputs.json"] = _wire({
        "schema": INPUT_SCHEMA, "profile": PROFILE,
        "original_corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
        "original_corpus_preparation": {
            "manifest_json": original.manifest_json,
            "files": [list(pair) for pair in original.files],
        },
        "original_native_fragments": [row["native"] for row in rows],
        "assessment_file_sha256": expected_assessment_file_sha256,
        "reference_contract": reference,
    }, MAX_PROJECT_BYTES).decode() + "\n"
    _need(len(files) == MAX_FILES and len(modules) == len(set(modules)) == MAX_MODULES
          and len(theorems) == len(set(theorems)) == MAX_THEOREMS,
          "exact sixteen-file/twelve-module/fifteen-theorem preservation project required")
    positions = {name: index for index, name in enumerate(modules)}
    _need(all(positions[dependency] < positions[name] for name in modules for dependency in imports[name]),
          "closed acyclic corpus preservation module imports required")
    for module in modules:
        _need(re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$",
                         files[module.replace(".", "/") + ".lean"]) == imports[module],
              "exact corpus preservation source imports required")
    _need(all(files[name] == body for name, body in original.files if name != "lakefile.toml"),
          "original V2 corpus sources or bindings changed during preservation preparation")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain, "target": "legal",
        "original_corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
        "original_corpus_preparation_manifest_sha256": _sha(original.manifest_json.encode()),
        "original_corpus_preparation_cid": original_manifest["record_cid"],
        "assessment_file_sha256": expected_assessment_file_sha256,
        "review_intake_binding": original_manifest["review_intake_binding"],
        "review_dependency_manifest": original_manifest["review_dependency_manifest"],
        "original_preparation_state": original_state,
        "preservation_fragments": fragments,
        "semantics_module": semantics_module, "semantics_sha256": _sha(semantics.encode()),
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(body.encode()) for name, body in sorted(files.items())},
        "theorems": theorems, "conditional_theorems": conditional_theorems,
        "preservation_theorems": preservation_theorems,
        "theorem_assumptions": [*original_manifest["theorem_assumptions"],
            "All four certificates use the original LegalCorpusV2.Interpretation and target the original module formula_0 directly.",
            "Concrete AST value reconstruction, closedness and denotation do not establish statutory source meaning or the alias premise.",
            "Python JSON parsing, reification and cryptographic commitments remain outside the kernel theorem.",
            "All fifteen generated theorem obligations require separate native kernel execution.",
        ],
        "reference_contract": reference,
        "source_custody": {
            "scope": "complete current original V2 source/review preparation and four original native fragments replayed",
            "original_corpus_envelope_retained_in": "preservation-inputs.json/original_corpus_preparation",
            "original_lean_sources_unchanged": True,
            "original_bindings_unchanged": True,
            "original_review_state_unchanged": True,
            "nominal_interpretation_shared": True,
            "source_prose_to_ast_proved": False,
        },
        "trust_boundary": [
            "Existing original V2 public preparation/source/review validators retain their exact ownership and assumptions.",
            "The public standalone preservation owner supplies all syntax data and total denotation; no second reifier is implemented here.",
            "Certificate template transport changes only the denotation theorem target after removing the unchanged copied native declaration.",
            "The engineering reference contract is not LegalProofCache@1 and conveys no legal proof-cache authority.",
        ],
        "producer_pins": producers,
        "native_producer_pins": dict(original_manifest["native_producer_pins"]),
        "preparation_only": True, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    # Replay all original inputs again; immutable-looking Python objects can be
    # changed with object.__setattr__, so retain the original complete envelope.
    replayed = corpus_native.validate_definition_use_native_v2(
        corpus_preparation, assessment_raw,
        expected_preparation_sha256=expected_corpus_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    _need(_envelope(replayed, original=True) == original_envelope,
          "original corpus envelope changed during preservation preparation")
    for _, raw, prepared in standalone:
        standalone_owner.validate_native_ast_preservation(
            prepared, raw, expected_preparation_sha256=standalone_owner.preparation_sha256(prepared),
            expected_fragment_file_sha256=_sha(raw), toolchain=toolchain)
    _need(_pins(owners, original_manifest, [item[2].to_dict() for item in standalone]) == producers,
          "corpus preservation producers changed during preparation")
    preparation = DefinitionUsePreservationPreparation(
        _wire(manifest, MAX_RECORD_BYTES).decode(), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    if cache_key is not None:
        _prepare_cache_put(cache_key, preparation)
    return preparation


def validate_definition_use_preservation_v2(preparation, corpus_preparation, assessment_raw, *,
        expected_preparation_sha256, expected_corpus_preparation_sha256,
        expected_assessment_file_sha256, review_inputs, toolchain):
    """Check the independent full pin and regenerate the complete extension."""
    _pin(expected_preparation_sha256, "complete V2 corpus preservation preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete corpus preservation preparation pin differs")
    expected = prepare_definition_use_preservation_v2(
        corpus_preparation, assessment_raw,
        expected_corpus_preparation_sha256=expected_corpus_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    _need(expected == preparation,
          "corpus preservation preparation differs from complete authoritative regeneration")
    return expected
