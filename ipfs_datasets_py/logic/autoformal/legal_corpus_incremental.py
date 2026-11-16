"""Verified legacy and parent Lean artifact reuse through the LegalIR compiler.

Every current interpretation is regenerated. Only compiler artifacts are reused;
review and legal authority never follow from a cache hit. Public import is inert.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import stat
import time
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

from . import corpus_contracts as contracts
from . import legal_corpus_shared_lake as shared

PARENT_CACHE_SCHEMA = "legal-corpus-parent-direct-lean-cache/v1"
PARENT_CONTRACT_SCHEMA = "legal-corpus-parent-direct-lean-execution-contract/v1"
PARENT_BUILD_SCHEMA = "legal-corpus-parent-incremental-native-build/v1"
PARENT_PROFILE = "verified-parent-source-bound-olean-per-module/v1"
_PARENT_MODULE = re.compile(r"LegalCorpusParent(?:\.(?:Prelude|(?:Definition|Alias|Joint)[0-9a-f]{64}))?\Z")
_PARENT_IMPORT = re.compile(r"^import (LegalCorpusParent(?:\.(?:Prelude|(?:Definition|Alias|Joint)[0-9a-f]{64}))?)$", re.M)
PARENT_FALSE_FLAGS = {key: value for key, value in shared.PARENT_FALSE_FLAGS.items()
    if key not in {"backend_executed", "lean_compilation_verified"}}
PROVENANCE_FIELDS = {"role", "identity", "source_binding_sha256", "native_sha256", "input_binding_sha256s"}
EVIDENCE_FIELDS = {"runtime", "command", "pid", "native_lifecycle", "source_readback_sha256",
    "import_readback_sha256", "stdout", "stderr"}

CACHE_SCHEMA = "legal-corpus-direct-lean-cache/v1"
CONTRACT_SCHEMA = "legal-corpus-direct-lean-execution-contract/v1"
BUILD_SCHEMA = "legal-corpus-incremental-native-build/v1"
PROFILE = "verified-legacy-olean-per-module/v1"
MAX_ARTIFACT_BYTES = 4 * 1024**2
MAX_ARTIFACT_POPULATION_BYTES = 32 * 1024**2
MAX_LIBRARY_FILES = 16384
MAX_LIBRARY_BYTES = 3 * 1024**3
MAX_CLOSURE_BYTES = 4 * 1024**2
MAX_OBSERVATION_BYTES = 8 * 1024**2
_MODULE = re.compile(r"LegalCorpus(?:\.[A-Za-z][A-Za-z0-9]*)?\Z")
_IMPORT = re.compile(r"^import (LegalCorpus(?:\.[A-Za-z][A-Za-z0-9]*)?)$", re.M)
FALSE_FLAGS = {key: value for key, value in shared.FALSE_FLAGS.items()
               if key not in {"backend_executed", "lean_compilation_verified"}}
CACHE_FIELDS = {"profile", "qualified", "execution_contract", "module_facts", "artifact_root_cid", *FALSE_FLAGS}
CONTRACT_FIELDS = {"profile", "toolchain", "binary_sha256", "toolchain_closure", "owner_pins", "platform", "argv_recipe", "environment"}
FACT_FIELDS = {"module", "source", "imports", "recipe", "output"}
OUTPUT_FIELDS = {"module", "recipe_cid", "source_sha256", "import_artifact_sha256", "artifact_sha256",
                 "artifact_bytes", "theorem_axiom_dependencies", "kernel_checked"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


_SELF_PIN = _sha(Path(__file__).read_bytes())


def _parent_native():
    from . import legal_corpus_definition_use_native_v2
    return legal_corpus_definition_use_native_v2


def _parent_flags():
    return {key: value for key, value in (PARENT_FALSE_FLAGS | _parent_native().PARENT_FALSE_FLAGS).items()
            if key not in {"backend_executed", "lean_compilation_verified"}}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _owners():
    from ..integration.reasoning import legal_ir_incremental_compiler as incremental
    from ..integration.reasoning import legal_ir_pass_manager as passes
    from . import legal_source_definition_norm_lake as native

    return incremental, passes, native


def _owner_pins(incremental, passes, *, parent=False, manifest=None, reviewed=False, instance_identity_profile=None, definition_application_profile=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    if _is_realization(reviewed):
        return _realization_owner_pins(incremental, passes, manifest, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
    if reviewed:
        return _reviewed_owner_pins(incremental, passes, manifest, **_reviewed_identity_keywords(instance_identity_profile))
    native = _owners()[2]
    if parent:
        from ..integration.reasoning import legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps
        owner = _parent_native()
        if _sha(Path(__file__).read_bytes()) != _SELF_PIN:
            _fail("incremental owner changed since import")
        # Finite direct implementation scope; this is not a Python environment attestation.
        return owner._pins(owner._owners(), manifest) | {
            str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
            for module in (incremental, passes, legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps)
        } | {str(Path(__file__).resolve()): _SELF_PIN}
    return shared._pins() | native.pins() | {
        str(path.resolve()): _sha(path.read_bytes())
        for path in (Path(__file__), Path(incremental.__file__), Path(passes.__file__))}


def _deadline(deadline, cancellation):
    if time.monotonic() >= deadline:
        _fail("complete incremental build deadline exceeded")
    if cancellation is not None:
        predicate = getattr(cancellation, "is_cancelled", None) or getattr(cancellation, "is_set", None)
        if predicate is None and callable(cancellation):
            predicate = cancellation
        if predicate is None:
            _fail("supported incremental cancellation interface required")
        if predicate():
            _fail("incremental build admission cancelled")


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _toolchain_closure(executable, deadline, cancellation):
    """Stream the complete selected installed library population, never tensors."""
    root = Path(executable).parent.parent / "lib" / "lean"
    shared.joint_owner._check_directories(root)
    endings = (".olean", ".olean.server", ".olean.private", ".ir.sig", ".ir", ".so")
    selected, entries = [], 0
    for path in root.rglob("*"):
        _deadline(deadline, cancellation)
        entries += 1
        if entries > 65536 or path.is_symlink():
            _fail("unsupported linked or oversized installed toolchain tree")
        if path.name.endswith(endings) or ".so." in path.name:
            selected.append(path)
            if len(selected) > MAX_LIBRARY_FILES:
                _fail("complete installed library file bound exceeded")
    raw, total = bytearray(), 0
    for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix()):
        _deadline(deadline, cancellation)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                _fail("ordinary installed compiler library files required")
            total += before.st_size
            if total > MAX_LIBRARY_BYTES:
                _fail("complete installed library byte bound exceeded")
            digest, count = hashlib.sha256(), 0
            while block := stream.read(1024**2):
                _deadline(deadline, cancellation)
                count += len(block)
                digest.update(block)
                if count > before.st_size:
                    _fail("installed compiler library changed while reading")
            after = os.fstat(stream.fileno())
        if count != before.st_size or _identity(before) != _identity(after) or _identity(before) != _identity(path.lstat()):
            _fail("installed compiler library identity changed while reading")
        row = {"path": path.relative_to(root).as_posix(), "bytes": count, "sha256": digest.hexdigest()}
        raw.extend(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
        if len(raw) > MAX_CLOSURE_BYTES:
            _fail("complete toolchain closure manifest bound exceeded")
    if not selected or not (root / "Init.olean").is_file():
        _fail("installed implicit Init closure required")
    summary = contracts.seal_record({"schema": "legal-corpus-installed-lean-library-closure/v1",
        "profile": "all-olean-parts-ir-and-shared-libraries/v1", "file_count": len(selected),
        "file_bytes": total, "manifest_bytes": len(raw), "manifest_sha256": _sha(raw)})
    return summary, bytes(raw)


def _parent_role(module):
    if not _PARENT_MODULE.fullmatch(module):
        _fail("bounded parent module identity required")
    if module == "LegalCorpusParent":
        return "root"
    suffix = module.split(".", 1)[1]
    return "prelude" if suffix == "Prelude" else next(
        role for role in ("definition", "alias", "joint") if suffix.startswith(role.title()))


def _parent_graph(facts):
    """Validate the exact generated parent DAG, independently of role ordering."""
    by_module = {row["module"]: row for row in facts}
    if not 1 <= len(facts) <= 34 or len(by_module) != len(facts):
        _fail("bounded distinct parent module population required")
    seen, depths = set(), {}
    for row in facts:
        module, imports = row["module"], row["imports"]
        role = _parent_role(module)
        if type(imports) is not list or len(set(imports)) != len(imports) or not set(imports) <= seen:
            _fail("topological complete parent import DAG required")
        roles = [_parent_role(item) for item in imports]
        expected = {"prelude": [], "definition": ["prelude"],
                    "alias": ["definition", "definition"],
                    "joint": ["definition", "definition", "alias"]}
        if role == "root":
            if imports != sorted(name for name in by_module if _parent_role(name) == "joint") or not imports:
                _fail("parent root must import every unique joint")
        elif roles != expected[role]:
            _fail("parent module role/import contract differs")
        if role == "joint" and by_module[imports[2]]["imports"] != imports[:2]:
            _fail("parent joint alias does not bind its exact endpoints")
        seen.add(module)
        depths[module] = max((depths[item] + 1 for item in imports), default=0)
        names = re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)
        wanted = (["consumer_predicate_iff_donor_body"] if role == "alias" else
                  ["joint_of_components", "joint_matches_original"] if role == "joint" else [])
        if names != wanted:
            _fail("parent theorem declarations differ from exact generated role")
    if set(by_module) != seen or "LegalCorpusParent" not in seen or "LegalCorpusParent.Prelude" not in seen:
        _fail("complete parent root and Prelude required")
    reachable, frontier = set(), ["LegalCorpusParent"]
    while frontier:
        module = frontier.pop()
        if module not in reachable:
            reachable.add(module)
            frontier.extend(by_module[module]["imports"])
    if reachable != seen:
        _fail("parent import population contains unreachable modules")
    return depths


def _parent_provenance(preparation):
    """Use retained, publicly replayed child records, never caller cache labels."""
    manifest, files = preparation.to_dict(), dict(preparation.files)
    result = {}
    for component in manifest["components"]:
        raw = files[component["manifest_file"]].encode()
        child = contracts.load_record_bytes(raw, expected_sha256=component["manifest_sha256"])
        binding_raw = files[component["input_bindings_file"]].encode()
        if _sha(binding_raw) != component["input_bindings_sha256"]:
            _fail("retained parent input binding differs")
        binding = contracts.load_record_bytes(binding_raw, expected_sha256=_sha(binding_raw))
        contracts.require_sha256(binding["original_input_commitment_sha256"], "complete original parent inputs")
        originals = {row["role"]: row for row in child["review_source_binding"]["original_definitions"]}
        for fragment in child["native_fragments"]:
            module, original_role = fragment["module"], fragment["role"]
            role = _parent_role(module)
            if original_role in ("donor", "consumer"):
                context = {key: value for key, value in originals[original_role].items() if key != "role"}
                identity, bindings = context["candidate_pin"]["candidate_cid"], []
            else:
                context = ({key: child["review_source_binding"][key]
                            for key in ("binding_record", "alias_record", "scope_binding")} if role == "alias"
                           else child["review_intake_binding"]["component_pin"])
                identity = (child["review_source_binding"]["binding_record"]["record_cid"] if role == "alias"
                            else child["review_intake_binding"]["component_pin"]["component_cid"])
                # This retained binding commits full original registry/query/lookup inputs,
                # including empty, unavailable and competing queried partitions.
                bindings = [_sha(binding_raw)]
            if module != "LegalCorpusParent." + role.title() + _sha(identity.encode()):
                _fail("parent semantic identity differs from its content-derived module")
            current = {"role": role, "identity": identity,
                "source_binding_sha256": _sha(canonical_dag_json_bytes(context)),
                "native_sha256": _sha(canonical_dag_json_bytes(fragment["native"])),
                "input_binding_sha256s": bindings}
            if module in result:
                previous = result[module]
                if any(previous[key] != current[key] for key in PROVENANCE_FIELDS - {"input_binding_sha256s"}):
                    _fail("shared parent semantic provenance differs")
                current["input_binding_sha256s"] = sorted(set(previous["input_binding_sha256s"] + bindings))
            result[module] = current
    for module, role in (("LegalCorpusParent.Prelude", "prelude"), ("LegalCorpusParent", "root")):
        source = files[module.replace(".", "/") + ".lean"]
        digest = _sha(source.encode())
        result[module] = {"role": role, "identity": module, "source_binding_sha256": digest,
                          "native_sha256": digest, "input_binding_sha256s": []}
    if set(result) != set(manifest["expected_modules"]):
        _fail("parent semantic provenance population differs")
    return result


def _parent_recipe_provenance(module, value):
    contracts.require_keys(value, PROVENANCE_FIELDS, "parent recipe provenance")
    role = _parent_role(module)
    if value["role"] != role:
        _fail("parent provenance role differs")
    for key in ("source_binding_sha256", "native_sha256"):
        contracts.require_sha256(value[key], "parent provenance " + key)
    bindings = value["input_binding_sha256s"]
    if (type(bindings) is not list or len(bindings) > 8 or bindings != sorted(set(bindings))
            or (role in ("alias", "joint")) != bool(bindings)):
        _fail("exact scoped parent input-binding population required")
    for digest in bindings:
        contracts.require_sha256(digest, "retained original parent input binding")
    if role in ("prelude", "root"):
        if value["identity"] != module:
            _fail("parent fixed module identity differs")
    else:
        contracts.require_cid(value["identity"], "parent recipe source identity")
        if module != "LegalCorpusParent." + role.title() + _sha(value["identity"].encode()):
            _fail("parent recipe module identity differs")
    return value


def _recipe(module, source, imports, contract, *, provenance=None, reviewed_provenance=None, instance_identity_profile=None, definition_application_profile=None,
        realization_provenance=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (realization_provenance is not None):
        _fail("whole-norm definition application requires the explicit realization domain")
    result = {"module": module, "source_sha256": _sha(source.encode("utf-8")),
              "imports": imports, "contract_cid": contract["record_cid"]}
    if provenance is not None:
        result["provenance"] = _parent_recipe_provenance(module, provenance)
    if realization_provenance is not None:
        if provenance is not None or reviewed_provenance is not None:
            _fail("realization recipe cannot alias a prior provenance domain")
        result["realization_provenance"] = _realization_recipe_provenance(module, realization_provenance, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile),
            **_realization_contract_keywords(contract, definition_application_profile))
    if reviewed_provenance is not None:
        result["reviewed_provenance"] = _reviewed_recipe_provenance(module, reviewed_provenance, **_reviewed_identity_keywords(instance_identity_profile))
    return result


def _facts(preparation, contract, *, parent=False, reviewed=False, graph=None, instance_identity_profile=None, definition_application_profile=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    if _is_realization(reviewed):
        return _realization_facts(preparation, contract, graph, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
    if reviewed:
        return _reviewed_facts(preparation, contract, graph, **_reviewed_identity_keywords(instance_identity_profile))
    manifest, files = preparation.to_dict(), dict(preparation.files)
    provenance = _parent_provenance(preparation) if parent else {}
    facts = []
    for module in manifest["expected_modules"]:
        if not (_PARENT_MODULE if parent else _MODULE).fullmatch(module):
            _fail("bounded generated module identity required")
        source = files[module.replace(".", "/") + ".lean"]
        imports = (_PARENT_IMPORT if parent else _IMPORT).findall(source)
        if parent and imports != manifest["module_imports"][module]:
            _fail("parent exact source imports differ from replayed manifest")
        if re.search(r"^\s*module(?:\s|$)", source, re.M):
            _fail("module-system artifacts require a different cache profile")
        facts.append({"module": module, "source": source, "imports": imports,
                      "recipe": _recipe(module, source, imports, contract,
                          provenance=provenance.get(module), **_realization_application_keywords(definition_application_profile)), "output": None})
    known = {row["module"] for row in facts}
    if len(known) != len(facts) or any(item not in known for row in facts for item in row["imports"]):
        _fail("complete closed generated module population required")
    if parent:
        _parent_graph(facts)
    return facts


def _parent_contract(contract, *, reviewed=False, instance_identity_profile=None, definition_application_profile=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    if (contract["profile"] != ((_realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if _is_realization(reviewed) else _reviewed_profile(instance_identity_profile)) if reviewed else PARENT_PROFILE) or type(contract["toolchain"]) is not str
            or not re.fullmatch(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+", contract["toolchain"])
            or contract["environment"] != {"LEAN_PATH": "compiled", "LEAN_NUM_THREADS": "1"}
            or contract["argv_recipe"] != ["installed-sibling-lean", "-o", "compiled/<module>.olean", "<module>.lean"]):
        _fail("closed parent native execution contract differs")
    if definition_application_profile is not None:
        _realization_contract_binding(contract, **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
    binaries = contract["binary_sha256"]
    if type(binaries) is not dict or len(binaries) != 2:
        _fail("exact installed parent native compiler pair required")
    for name, digest in binaries.items():
        contracts.require_text(name, "installed binary path", max_bytes=4096)
        if not Path(name).is_absolute():
            _fail("absolute installed native compiler paths required")
        contracts.require_sha256(digest, "installed native compiler SHA256")
    lean = [name for name in binaries if Path(name).name == "lean"]
    if len(lean) != 1 or len({str(Path(name).parent) for name in binaries}) != 1:
        _fail("installed sibling parent Lean binary required")
    pins = contract["owner_pins"]
    if type(pins) is not dict or not 1 <= len(pins) <= 512:
        _fail("bounded finite parent implementation pins required")
    for name, digest in pins.items():
        contracts.require_text(name, "parent owner path", max_bytes=4096)
        if not Path(name).is_absolute():
            _fail("absolute parent implementation owner paths required")
        contracts.require_sha256(digest, "parent implementation owner SHA256")
    return lean[0]


def _parent_execution_evidence(evidence, row, facts, process, contract, *, reviewed=False, instance_identity_profile=None, definition_application_profile=None):
    """Validate historical sampled ownership internally; fresh scope uses its owner."""
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    contracts.require_keys(evidence, EVIDENCE_FIELDS, "parent native execution evidence")
    module, source = row["module"], row["source"]
    pid, lifecycle = evidence["pid"], evidence["native_lifecycle"]
    lifecycle_fields = {"schema", "parent", "leader", "observed_descendants", "leader_reaped",
        "descendant_tracking_complete", "group_scan_complete", "remaining_group_members",
        "remaining_tracked_descendants", "readers", "stdin_writer", "workspace", "observation_errors",
        "ownership_is_sampled", "kernel_containment_attested", "cleanup_confirmed"}
    contracts.require_keys(lifecycle, lifecycle_fields, "sampled native lifecycle")
    identity_fields = {"pid", "birth_ticks", "parent_pid", "process_group_id", "session_id"}
    leader = contracts.require_keys(lifecycle["leader"], identity_fields, "native leader identity")
    parent = contracts.require_keys(lifecycle["parent"], {"pid", "birth_ticks"}, "native parent identity")
    if (type(pid) is not int or pid <= 0 or leader["pid"] != pid or leader["parent_pid"] != parent["pid"]
            or leader["session_id"] != pid or leader["process_group_id"] != pid
            or any(type(value) is not int or value <= 0 for value in (*leader.values(), *parent.values()))):
        _fail("parent native identity evidence differs")
    descendants = lifecycle["observed_descendants"]
    if type(descendants) is not list or len(descendants) > 4096:
        _fail("bounded sampled descendant population required")
    for identity in descendants:
        contracts.require_keys(identity, identity_fields, "sampled descendant identity")
        if (any(type(value) is not int or value <= 0 for value in identity.values())
                or identity["session_id"] != pid or identity["process_group_id"] != pid):
            _fail("sampled descendant scope differs")
    for key in ("leader_reaped", "descendant_tracking_complete", "group_scan_complete",
                "ownership_is_sampled", "cleanup_confirmed"):
        if lifecycle[key] is not True:
            _fail("native ownership cleanup is incomplete")
    if (lifecycle["schema"] != "native-owned-tool-lifecycle@1" or lifecycle["kernel_containment_attested"] is not False
            or any(lifecycle[key] != [] for key in ("remaining_group_members", "remaining_tracked_descendants", "observation_errors"))):
        _fail("native sampled cleanup contract differs")
    for key in ("readers", "stdin_writer"):
        item = contracts.require_keys(lifecycle[key], {"started", "joined"}, "native I/O cleanup")
        if (type(item["started"]) is not int or type(item["joined"]) is not int
                or item["started"] != item["joined"] or not 0 <= item["started"] <= (2 if key == "readers" else 1)):
            _fail("native reader/writer custody is unresolved")
    workspace = contracts.require_keys(lifecycle["workspace"], {"device", "inode", "removed"}, "native workspace")
    if (workspace["removed"] is not True or type(workspace["device"]) is not int or workspace["device"] < 0
            or type(workspace["inode"]) is not int or workspace["inode"] <= 0):
        _fail("native workspace custody is unresolved")
    command = evidence["command"]
    wanted = ["-o", "compiled/" + module.replace(".", "/") + ".olean", module.replace(".", "/") + ".lean"]
    if (evidence["runtime"] != process.ToolRuntime.NATIVE.value or type(command) is not list
            or len(command) != 4 or command[1:] != wanted or command[0] != _parent_contract(contract, reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
            or evidence["source_readback_sha256"] != _sha(source.encode())):
        _fail("native executed source/command evidence differs")
    needed, frontier = set(), list(row["imports"])
    while frontier:
        name = frontier.pop()
        if name not in needed:
            needed.add(name)
            frontier.extend(facts[name]["imports"])
    if evidence["import_readback_sha256"] != {name: facts[name]["output"]["artifact_sha256"] for name in sorted(needed)}:
        _fail("native executed import artifact evidence differs")
    stdout = contracts.require_text(evidence["stdout"], "native stdout", allow_empty=True, max_bytes=65536)
    stderr = contracts.require_text(evidence["stderr"], "native stderr", allow_empty=True, max_bytes=65536)
    expected = [module + "." + name for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", source, re.M)]
    if expected:
        axioms, errors, passed = _parent_native()._axiom_observations(stdout, stderr,
            {"conditional_theorems": expected}, maximum_theorems=(shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS if _is_realization(reviewed)
                else 5 if reviewed else 3))
        if not passed or errors or axioms != {name: [] for name in expected}:
            _fail("strict parent conditional axiom observations differ")
    elif re.search(r"\b(?:axiom|axioms|sorry|sorryAx)\b", stdout + stderr):
        _fail("unexpected parent axiom observation without theorem declarations")
    return evidence


def _artifact_root(facts):
    return cid_for_dag_json({row["module"]: row["output"]["artifact_sha256"] for row in facts})


def _previous(raw, expected_sha256, artifacts, *, parent=False, reviewed=False, instance_identity_profile=None, definition_application_profile=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    if raw is None:
        if expected_sha256 is not None or artifacts is not None:
            _fail("previous cache, independent pin and complete artifacts must be supplied together")
        return None
    value = contracts.load_record_bytes(raw, expected_sha256=expected_sha256)
    flags = _reviewed_flags() if reviewed else _parent_flags() if parent else FALSE_FLAGS
    fields = {"profile", "qualified", "execution_contract", "module_facts", "artifact_root_cid", *flags}
    value = contracts.validate_record(value, schema=_reviewed_domain_value(reviewed, "cache") if reviewed else PARENT_CACHE_SCHEMA if parent else CACHE_SCHEMA, fields=fields)
    if (value["profile"] != ((_realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if _is_realization(reviewed) else _reviewed_profile(instance_identity_profile)) if reviewed else PARENT_PROFILE if parent else PROFILE) or value["qualified"] is not True
            or any(value[key] is not False for key in flags)):
        _fail("independently pinned qualified technical cache required")
    contract = contracts.validate_record(value["execution_contract"], schema=_reviewed_domain_value(reviewed, "contract") if reviewed else PARENT_CONTRACT_SCHEMA if parent else CONTRACT_SCHEMA, fields=_realization_contract_fields(definition_application_profile))
    if contract["profile"] != ((_realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if _is_realization(reviewed) else _reviewed_profile(instance_identity_profile)) if reviewed else PARENT_PROFILE if parent else PROFILE):
        _fail("prior execution contract profile differs")
    if parent or reviewed:
        _parent_contract(contract, reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    facts = value["module_facts"]
    if type(facts) is not list or not 1 <= len(facts) <= (shared.MAX_REVIEWED_PRESERVATION_MODULES if reviewed else 34 if parent else 130) or type(artifacts) is not dict or ((parent or reviewed) and len(artifacts) != len(facts)):
        _fail("bounded complete prior module/artifact population required")
    by_module = {row.get("module"): row for row in facts if type(row) is dict}
    if len(by_module) != len(facts) or set(by_module) != set(artifacts):
        _fail("prior artifact population differs or repeats a module")
    total = 0
    prior_bound = (min(MAX_ARTIFACT_POPULATION_BYTES,
        shared.joint_owner.MAX_PROJECT_BYTES + contracts.MAX_RECORD_BYTES) if parent or reviewed else MAX_ARTIFACT_POPULATION_BYTES)
    for row in facts:
        contracts.require_keys(row, FACT_FIELDS, "prior module fact")
        module = contracts.require_text(row["module"], "prior module")
        if not (_reviewed_domain_value(reviewed, "module") if reviewed else _PARENT_MODULE if parent else _MODULE).fullmatch(module):
            _fail("unsupported prior module identity")
        source = contracts.require_text(row["source"], "prior generated source", max_bytes=contracts.MAX_RECORD_BYTES)
        imports = (_reviewed_domain_value(reviewed, "import") if reviewed else _PARENT_IMPORT if parent else _IMPORT).findall(source)
        if row["imports"] != imports or any(item not in by_module for item in imports):
            _fail("prior import population differs")
        provenance = row["recipe"].get("provenance") if parent and type(row["recipe"]) is dict else None
        if parent and provenance is None:
            _fail("complete parent semantic recipe required")
        if type(row["recipe"]) is not dict:
            _fail("closed prior recipe required")
        realization = _is_realization(reviewed)
        recipe = _recipe(module, source, imports, contract, provenance=provenance,
            reviewed_provenance=row["recipe"].get("reviewed_provenance") if reviewed and not realization else None,
            realization_provenance=row["recipe"].get("realization_provenance") if realization else None,
            instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
        if reviewed and ("realization_provenance" if realization else "reviewed_provenance") not in recipe:
            _fail("complete reviewed unit/dependency provenance required")
        if row["recipe"] != recipe:
            _fail("prior recipe differs from its exact source and contract")
        output = contracts.require_keys(row["output"], OUTPUT_FIELDS | ({"execution_evidence"} if parent or reviewed else set()), "prior native output")
        artifact = artifacts[module]
        if type(artifact) is not bytes or not 1 <= len(artifact) <= MAX_ARTIFACT_BYTES:
            _fail("bounded complete prior compiler artifact bytes required")
        total += len(artifact)
        if total > prior_bound:
            _fail("prior artifact aggregate byte bound exceeded")
        expected_imports = {item: by_module[item]["output"]["artifact_sha256"] for item in imports}
        if (output["module"] != module or output["recipe_cid"] != cid_for_dag_json(recipe)
                or output["source_sha256"] != recipe["source_sha256"]
                or output["import_artifact_sha256"] != expected_imports
                or output["artifact_sha256"] != _sha(artifact) or output["artifact_bytes"] != len(artifact)
                or output["kernel_checked"] is not True):
            _fail("prior module output differs from independently pinned artifacts/recipe")
        theorems = re.findall(r"^theorem ([A-Za-z0-9_]+)", source, re.M)
        if output["theorem_axiom_dependencies"] != {module + "." + name: [] for name in theorems}:
            _fail("prior theorem evidence differs from exact generated declarations")
    if parent or reviewed:
        _reviewed_graph_for(facts, reviewed, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile), **_realization_contract_keywords(contract, definition_application_profile)) if reviewed else _parent_graph(facts)
        process = _parent_native()._owners()[3]
        for row in facts:
            _parent_execution_evidence(row["output"]["execution_evidence"], row, by_module, process, contract,
                reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    if value["artifact_root_cid"] != _artifact_root(facts):
        _fail("prior artifact root differs")
    return value


def _key(module):
    return "m" + _sha(module.encode())


def _compiler(facts, functions, incremental, passes, *, parent=False, reviewed=False, instance_identity_profile=None, definition_application_profile=None, execution_contract=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    depths = _reviewed_graph_for(facts, reviewed, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile), **_realization_contract_keywords(execution_contract, definition_application_profile)) if reviewed else _parent_graph(facts) if parent else {}
    def order(module):
        if parent or reviewed:
            return depths[module]
        if module == "LegalCorpus.Prelude":
            return 0
        if module.startswith("LegalCorpus.Definition"):
            return 1
        if module.startswith("LegalCorpus.Norm"):
            return 2
        if module == "LegalCorpus":
            return 3
        _fail("unsupported generated module role")

    specs = [passes.LegalIRPassSpec(pass_id=_key(row["module"]), title=row["module"],
        kind=passes.LegalIRPassKind.COMPILER, order=order(row["module"]),
        declared_inputs=("requests." + _key(row["module"]),),
        declared_outputs=("compiled." + _key(row["module"]),),
        depends_on=tuple(_key(item) for item in row["imports"]),
        metadata={"native_recipe": row["recipe"]}) for row in facts]
    return incremental.LegalIRIncrementalCompiler(specs, functions, max_workers=1, resource_limits={"cpu": 1})


def _state(facts):
    return {"requests": {_key(row["module"]): row["recipe"] for row in facts}}


def _run(compiler, facts, previous=None):
    return compiler.compile(_state(facts), previous=previous, sources={}, citations={}, symbols={}, temporal={})


def _build_incremental_corpus(preparation, *, candidate_inputs=None, component_inputs=None,
        expected_preparation_sha256=None, parent=False, reviewed_inputs=None, reviewed_domain=None,
        operation_timeout_seconds=3600, expected_population, toolchain,
        lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, cancellation=None):
    """Compile/reuse exact modules under the caller's shared validation lease."""
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        _fail("bounded complete incremental build timeout required")
    if (type(operation_timeout_seconds) not in (int, float) or not math.isfinite(operation_timeout_seconds)
            or not 0 < operation_timeout_seconds <= 3600):
        _fail("finite whole-operation cooperative deadline required")
    reviewed = reviewed_inputs is not None
    instance_identity_profile = reviewed_inputs.get("instance_identity_profile") if reviewed else None
    definition_application_profile = reviewed_inputs.get("definition_application_profile") if reviewed else None
    if reviewed_domain is not None:
        if not reviewed or not _is_realization(reviewed_domain):
            _fail("explicit supported reviewed incremental domain and complete inputs required")
        reviewed = reviewed_domain
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not _is_realization(reviewed):
        _fail("whole-norm definition application requires the explicit realization domain")
    if reviewed and parent:
        _fail("reviewed mixed and parent profiles are distinct")
    strict = bool(parent or reviewed)
    if reviewed:
        if _is_realization(reviewed):
            _realization_policy(**_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
        else:
            _reviewed_policy(**_reviewed_identity_keywords(instance_identity_profile))
    realization_fence = (_realization_guard(preparation, reviewed_inputs, expected_preparation_sha256, toolchain)
        if _is_realization(reviewed) else None)
    cache_schema = _reviewed_domain_value(reviewed, "cache") if reviewed else PARENT_CACHE_SCHEMA if parent else CACHE_SCHEMA
    contract_schema = _reviewed_domain_value(reviewed, "contract") if reviewed else PARENT_CONTRACT_SCHEMA if parent else CONTRACT_SCHEMA
    build_schema = _reviewed_domain_value(reviewed, "build") if reviewed else PARENT_BUILD_SCHEMA if parent else BUILD_SCHEMA
    profile = (_realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if _is_realization(reviewed) else _reviewed_profile(instance_identity_profile)) if reviewed else PARENT_PROFILE if parent else PROFILE
    flags = _reviewed_flags() if reviewed else None
    started, deadline = time.monotonic(), time.monotonic() + timeout_seconds
    operation_deadline = started + operation_timeout_seconds if strict else deadline
    if strict:
        deadline = operation_deadline
    _deadline(deadline, cancellation)
    output = shared.joint_owner._path(output_directory)
    shared.joint_owner._check_directories(output.parent, allow_missing=True)
    if output.exists() or output.is_symlink():
        _fail("fresh incremental output directory required")
    prior = _previous(previous_cache_raw, expected_previous_cache_sha256, previous_artifacts, parent=parent, reviewed=reviewed,
        instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if strict else None
    def replay(offered):
        _deadline(operation_deadline, cancellation)
        if reviewed:
            if (reviewed_inputs.get("instance_identity_profile") != instance_identity_profile
                    or reviewed_inputs.get("definition_application_profile") != definition_application_profile):
                _fail("explicit reviewed instance identity selection changed during replay")
            result = (_realization_replay(offered, reviewed_inputs, expected_preparation_sha256, toolchain)
                if _is_realization(reviewed) else _reviewed_replay(offered, reviewed_inputs, expected_preparation_sha256, toolchain))
        elif parent:
            result = _parent_native().validate_parent_shared_definition_use_native_v1(offered,
                component_inputs=component_inputs, expected_population=expected_population,
                expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain)
        else:
            result = shared.validate_shared_definition_corpus(offered, candidate_inputs=candidate_inputs,
                expected_population=expected_population, toolchain=toolchain)
        _deadline(operation_deadline, cancellation)
        return result
    checked = replay(preparation)
    if reviewed:
        if type(checked) is not shared.ReviewedPreservationCorpusPreparation:
            _fail("exact reviewed mixed preservation preparation type required")
        checked = shared.ReviewedPreservationCorpusPreparation(checked.manifest_json, tuple(checked.files))
        if shared.reviewed_preservation_corpus_sha256(checked) != expected_preparation_sha256:
            _fail("reviewed mixed snapshot differs from independently pinned preparation")
        reviewed_execution = (_realization_execution_snapshot(reviewed_inputs)
            if _is_realization(reviewed) else _reviewed_execution_snapshot(reviewed_inputs))
        if (reviewed_execution.get("instance_identity_profile") != instance_identity_profile
                or reviewed_execution.get("definition_application_profile") != definition_application_profile):
            _fail("opening reviewed identity snapshot differs from explicit caller selection")
        if realization_fence is not None:
            realization_fence()
        _deadline(operation_deadline, cancellation)
        deadline = min(operation_deadline, time.monotonic() + timeout_seconds)
    elif parent:
        if type(checked) is not shared.ParentSharedCorpusPreparation:
            _fail("exact validated parent shared preparation type required")
        checked = shared.ParentSharedCorpusPreparation(checked.manifest_json,
            tuple((name, body) for name, body in checked.files))
        if (_parent_native().parent_shared_preparation_sha256(checked) != expected_preparation_sha256
                or _parent_native().parent_shared_preparation_sha256(preparation) != expected_preparation_sha256):
            _fail("validated parent snapshot differs from independently pinned preparation")
        deadline = min(operation_deadline, time.monotonic() + timeout_seconds)
    else:
        prior = _previous(previous_cache_raw, expected_previous_cache_sha256, previous_artifacts, **_realization_application_keywords(definition_application_profile))
    incremental, passes, native = _owners()
    owner_pins = _owner_pins(incremental, passes, parent=parent, reviewed=reviewed, manifest=checked.to_dict(),
                instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if strict else _owner_pins(incremental, passes, **_realization_application_keywords(definition_application_profile))
    _deadline(deadline, cancellation)
    # The two installed-toolchain version probes each have a five-second cap.
    if deadline - time.monotonic() < 10:
        _fail("insufficient complete build deadline for bounded version probes")
    executable, binaries, probes = native.shared._installed_toolchain(lake_executable, toolchain)
    _deadline(deadline, cancellation)
    lean = Path(executable).parent / "lean"
    closure, closure_raw = _toolchain_closure(executable, deadline, cancellation)
    contract_payload = {"schema": contract_schema, "profile": profile, "toolchain": toolchain,
        "binary_sha256": binaries, "toolchain_closure": closure, "owner_pins": owner_pins,
        "platform": {"system": platform.system(), "machine": platform.machine(), "libc": list(platform.libc_ver())},
        "argv_recipe": ["installed-sibling-lean", "-o", "compiled/<module>.olean", "<module>.lean"],
        "environment": {"LEAN_PATH": "compiled", "LEAN_NUM_THREADS": "1"}}
    if definition_application_profile is not None:
        contract_payload["realization_binding"] = contracts.seal_record({
            "schema": "legal-corpus-reviewed-definition-application-binding/v1",
            "binding": _realization_preparation_binding(checked,
                **_reviewed_identity_keywords(instance_identity_profile),
                **_realization_application_keywords(definition_application_profile))})
    contract = contracts.seal_record(contract_payload)
    contract_fence = (_realization_contract_guard(contract,
        **_reviewed_identity_keywords(instance_identity_profile),
        **_realization_application_keywords(definition_application_profile))
        if definition_application_profile is not None else None)
    prior_contract_fence = (_realization_contract_guard(prior["execution_contract"],
        **_reviewed_identity_keywords(instance_identity_profile),
        **_realization_application_keywords(definition_application_profile))
        if definition_application_profile is not None and prior is not None else None)
    facts = _facts(checked, contract, parent=parent, reviewed=reviewed,
        graph=reviewed_execution["graph"] if reviewed else None, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    if contract_fence is not None:
        contract_fence()
    by_module = {row["module"]: row for row in facts}
    artifacts = {} if prior is None else {name: raw for name, raw in previous_artifacts.items() if name in by_module}
    old_snapshot = None
    if prior is not None:
        old_facts = prior["module_facts"]
        functions = {_key(row["module"]): (lambda _state, row=row: {"compiled": {_key(row["module"]): row["output"]}})
                     for row in old_facts}
        old_result = _run(_compiler(old_facts, functions, incremental, passes, parent=parent, reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile),
            **_realization_contract_keywords(prior["execution_contract"], definition_application_profile)), old_facts)
        if prior_contract_fence is not None:
            prior_contract_fence()
        if not old_result.successful:
            _fail("prior module dependency graph failed independent reconstruction")
        old_snapshot = old_result.snapshot
    observations, fresh, cleanup_latch = [], [], []

    def function(row):
        def compile_module(state):
            if cleanup_latch:
                raise cleanup_latch[0]
            if strict:
                _deadline(operation_deadline, cancellation)
            module, recipe = row["module"], row["recipe"]
            dependencies = {item: state.get("compiled", {}).get(_key(item)) for item in row["imports"]}
            import_shas = {item: item_output["artifact_sha256"] for item, item_output in dependencies.items()
                           if item_output is not None and item_output["kernel_checked"]}
            result_output = {"module": module, "recipe_cid": cid_for_dag_json(recipe),
                "source_sha256": recipe["source_sha256"], "import_artifact_sha256": import_shas,
                "artifact_sha256": None, "artifact_bytes": 0, "theorem_axiom_dependencies": {}, "kernel_checked": False}
            if len(import_shas) != len(dependencies):
                _fail("current dependency lacks a checked compiler artifact")
            _deadline(deadline, cancellation)
            needed, frontier = set(), list(row["imports"])
            while frontier:
                item = frontier.pop()
                if item not in needed:
                    needed.add(item)
                    frontier.extend(by_module[item]["imports"])
            inputs = {module.replace(".", "/") + ".lean": row["source"], "compiled/.keep": b""}
            for item in sorted(needed):
                item_output = state["compiled"][_key(item)]
                if item not in artifacts or _sha(artifacts[item]) != item_output["artifact_sha256"]:
                    _fail("dependency artifact differs before native import")
                inputs["compiled/" + item.replace(".", "/") + ".olean"] = artifacts[item]
            path = "compiled/" + module.replace(".", "/") + ".olean"
            # The root has no imports only in a one-module profile; create its
            # relative output parent without trusting any external filesystem.
            inputs["compiled/" + (_reviewed_domain_value(reviewed, "root") if reviewed else "LegalCorpusParent" if parent else "LegalCorpus") + "/.keep"] = b""
            command = (str(lean), "-o", path, module.replace(".", "/") + ".lean")
            captured_inputs = {name: (raw.encode() if type(raw) is str else raw)
                               for name, raw in inputs.items() if not name.endswith("/.keep")}
            try:
                result = native.process.BoundedToolRunner().run(native.process.ToolRunRequest(
                    argv=command, input_files=inputs,
                    output_paths=tuple([path, *sorted(captured_inputs)]) if strict else (path,),
                    environment=contract["environment"], owned_process_observation=strict,
                    limits=native.process.ToolRunLimits(timeout_seconds=max(0.001, deadline - time.monotonic()),
                        cpu_seconds=max(0.001, deadline - time.monotonic()), resident_memory_bytes=2 * 1024**3,
                        max_output_bytes=MAX_ARTIFACT_BYTES, max_input_bytes=40 * 1024**2, max_workspace_bytes=128 * 1024**2,
                        max_output_files=len(captured_inputs) + 1 if strict else 1)),
                    **({"cancellation": cancellation} if cancellation is not None else {}))
            except native.process.OwnedToolCleanupError as error:
                if strict and not cleanup_latch:
                    cleanup_latch.append(error)
                raise
            fresh.append(module)
            observations.append({"module": module, **result.to_dict(),
                "output_files": {name: {"bytes": len(raw), "sha256": _sha(raw)} for name, raw in result.output_files.items()}})
            raw = result.output_files.get(path)
            expected_theorems = [module + "." + name for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)]
            axioms = {name: [] for name in expected_theorems if "'" + name + "' does not depend on any axioms" in result.stdout}
            passed = bool(result.ok and result.pid is not None and tuple(result.command) == command
                and set(result.output_files) == ({path, *captured_inputs} if strict else {path}) and type(raw) is bytes and 1 <= len(raw) <= MAX_ARTIFACT_BYTES
                and result.workspace_cleaned and not result.error and not result.output_truncated
                and not result.workspace_limit_exceeded and len(axioms) == len(expected_theorems)
                and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
            if strict:
                lifecycle = result.native_lifecycle
                passed = bool(passed and result.runtime is native.process.ToolRuntime.NATIVE
                    and type(lifecycle) is native.process.NativeToolLifecycleObservation
                    and lifecycle.cleanup_confirmed
                    and _parent_native()._observed_process_scope(lifecycle, result.pid, native.process)
                    and all(result.output_files.get(name) == value for name, value in captured_inputs.items()))
                if passed:
                    evidence = {"runtime": result.runtime.value, "command": list(result.command), "pid": result.pid,
                        "native_lifecycle": lifecycle.to_dict(), "source_readback_sha256": _sha(row["source"].encode()),
                        "import_readback_sha256": {name: _sha(artifacts[name]) for name in sorted(needed)},
                        "stdout": result.stdout, "stderr": result.stderr}
                    executed_facts = {name: {**fact, "output": state.get("compiled", {}).get(_key(name))}
                                      for name, fact in by_module.items()}
                    _parent_execution_evidence(evidence, row, executed_facts, native.process, contract,
                        reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))
                    result_output["execution_evidence"] = evidence
            if passed:
                artifacts[module] = raw
                result_output.update(artifact_sha256=_sha(raw), artifact_bytes=len(raw),
                                     theorem_axiom_dependencies=axioms, kernel_checked=True)
            else:
                artifacts.pop(module, None)
                _fail("native module compilation failed: " + module)
            return {"compiled": {_key(module): result_output}}
        return compile_module

    functions = {_key(row["module"]): function(row) for row in facts}
    try:
        if contract_fence is not None:
            contract_fence()
        result = _run(_compiler(facts, functions, incremental, passes, parent=parent, reviewed=reviewed, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile),
            **_realization_contract_keywords(contract, definition_application_profile)), facts, old_snapshot)
        if contract_fence is not None:
            contract_fence()
    finally:
        # Framework callbacks are diagnosticized; custody must retain the exact owner.
        if cleanup_latch:
            raise cleanup_latch[0]
    for row in facts:
        row["output"] = result.output_state.get("compiled", {}).get(_key(row["module"]))
    post_error = None
    try:
        _deadline(deadline, cancellation)
        replay_started = time.monotonic()
        after_preparation = replay(preparation if strict else checked)
        if reviewed:
            if (type(after_preparation) is not shared.ReviewedPreservationCorpusPreparation
                    or after_preparation != checked
                    or shared.reviewed_preservation_corpus_sha256(after_preparation) != expected_preparation_sha256):
                _fail("closing reviewed replay differs from frozen executed preparation")
            deadline = min(operation_deadline, deadline + time.monotonic() - replay_started)
        elif parent:
            if (type(after_preparation) is not shared.ParentSharedCorpusPreparation
                    or after_preparation.manifest_json != checked.manifest_json
                    or after_preparation.files != checked.files
                    or _parent_native().parent_shared_preparation_sha256(after_preparation) != expected_preparation_sha256):
                _fail("closing parent replay differs from frozen executed preparation")
            deadline = min(operation_deadline, deadline + time.monotonic() - replay_started)
        after_closure, after_raw = _toolchain_closure(executable, deadline, cancellation)
        if closure != after_closure or closure_raw != after_raw or (_owner_pins(incremental, passes, parent=parent, reviewed=reviewed, manifest=checked.to_dict(),
                instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile)) if strict else _owner_pins(incremental, passes, **_realization_application_keywords(definition_application_profile))) != owner_pins:
            _fail("compiler closure or owner changed during native compilation")
        if any(_sha(Path(name).read_bytes()) != digest for name, digest in binaries.items()):
            _fail("native compiler executable changed during compilation")
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    qualified = bool(result.successful and post_error is None and all(
        row["output"] is not None and row["output"]["kernel_checked"] is True
        and row["output"]["recipe_cid"] == cid_for_dag_json(row["recipe"])
        and row["output"]["source_sha256"] == row["recipe"]["source_sha256"]
        and row["output"]["import_artifact_sha256"] == {
            item: _sha(artifacts[item]) for item in row["imports"] if item in artifacts}
        and len(row["output"]["import_artifact_sha256"]) == len(row["imports"])
        and row["output"]["theorem_axiom_dependencies"] == {
            row["module"] + "." + name: []
            for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)}
        and row["module"] in artifacts and _sha(artifacts[row["module"]]) == row["output"]["artifact_sha256"]
        for row in facts))
    retained = {row["module"]: artifacts[row["module"]] for row in facts if row["module"] in artifacts
                and row["output"] is not None and row["output"]["kernel_checked"]}
    retained_bound = (min(MAX_ARTIFACT_POPULATION_BYTES,
        shared.joint_owner.MAX_PROJECT_BYTES + contracts.MAX_RECORD_BYTES) if strict else MAX_ARTIFACT_POPULATION_BYTES)
    if sum(map(len, retained.values())) > retained_bound:
        _fail("complete compiled artifact population exceeds exact transport byte bound" if strict
              else "complete compiled artifact population exceeds byte bound")
    if contract_fence is not None:
        contract_fence()
        if prior_contract_fence is not None:
            prior_contract_fence()
    artifact_root = cid_for_dag_json({name: _sha(raw) for name, raw in sorted(retained.items())})
    cache = contracts.seal_record({"schema": cache_schema, "profile": profile, "qualified": qualified,
        "execution_contract": contract, "module_facts": facts, "artifact_root_cid": artifact_root, **(flags if reviewed else _parent_flags() if parent else FALSE_FLAGS)})
    cache_raw = canonical_dag_json_bytes(cache)
    if contract_fence is not None:
        contract_fence(cache["execution_contract"])
    reused = [row["module"] for row in facts if row["module"] not in fresh and row["output"] is not None
              and row["output"]["kernel_checked"]]
    observation_raw = b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                               for row in observations)
    if len(observation_raw) > MAX_OBSERVATION_BYTES:
        _fail("complete native execution observation byte bound exceeded")
    receipt = contracts.seal_record({"schema": build_schema, "profile": profile,
        "preparation_cid": checked.to_dict()["record_cid"], "execution_contract_cid": contract["record_cid"],
        "cache_identity": {"record_cid": cache["record_cid"], "sha256": _sha(cache_raw), "bytes": len(cache_raw)},
        "previous_cache_cid": None if prior is None else prior["record_cid"],
        "compiled_modules": fresh, "reused_modules": reused, "expected_modules": [row["module"] for row in facts],
        "fresh_theorems": [name for row in facts if row["module"] in fresh and row["output"] is not None
                           for name in row["output"]["theorem_axiom_dependencies"]],
        "reused_theorems": [name for row in facts if row["module"] in reused for name in row["output"]["theorem_axiom_dependencies"]],
        "artifact_files": {name: "compiled/" + name.replace(".", "/") + ".olean" for name in retained},
        "artifact_sha256": {name: _sha(raw) for name, raw in retained.items()}, "artifact_root_cid": artifact_root,
        "toolchain_closure": closure, "version_probes": probes, "post_run_validation_error": post_error,
        "execution_observations": {"path": "module-executions.jsonl", "bytes": len(observation_raw),
                                   "sha256": _sha(observation_raw)},
        "toolchain_probes_executed": True, "module_compile_invocations": len(observations),
        "framework_successful": result.successful, "framework_diagnostics": [item.to_dict() for item in result.diagnostics],
        "framework_metrics": result.metrics.to_dict(), "observed_wall_seconds": time.monotonic() - started,
        "build_passed": qualified, "lean_compilation_verified": qualified, "backend_executed": bool(observations),
        "composition_obligations_checked": qualified, **(flags if reviewed else _parent_flags() if parent else FALSE_FLAGS)})
    if parent:
        manifest = checked.to_dict()
        receipt = contracts.seal_record({**{key: value for key, value in receipt.items()
            if key not in {"record_cid", "cid_scope"}},
            "expected_preparation_sha256": expected_preparation_sha256,
            "population": manifest["population"], "components": manifest["components"],
            "module_contributors": {row["module"]: row["contributors"] for row in manifest["module_bindings"]},
            "theorem_contributors": [{"ordinal": row["ordinal"], "component_cid": row["component_cid"],
                "conditional_theorems": row["conditional_theorems"]} for row in manifest["components"]],
            "input_commitment_sha256": manifest["input_commitment_sha256"],
            "theorem_assumptions": manifest["theorem_assumptions"],
            "compiler_timeout_seconds": timeout_seconds, "operation_timeout_seconds": operation_timeout_seconds,
            "deadline_profile": "cooperative-whole-operation; cumulative-compiler-budget-excludes-source-review-replays",
            "source_replay_preempted": False, "fresh_proof_for_reused_modules": False,
            "implementation_pin_scope": "native-producer-closure-and-five-direct-LegalIR-framework-owners"})
        _deadline(operation_deadline, cancellation)
    if reviewed:
        if _is_realization(reviewed):
            _realization_policy(**_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
        else:
            _reviewed_policy(**_reviewed_identity_keywords(instance_identity_profile))
        receipt_builder = _realization_receipt if _is_realization(reviewed) else _reviewed_receipt
        receipt = receipt_builder(receipt, checked, reviewed_execution, expected_preparation_sha256,
            timeout_seconds, operation_timeout_seconds)
        _deadline(operation_deadline, cancellation)
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.replace(".", "/") + ".olean": raw for name, raw in retained.items()}
    shared._write_compiled(output / "compiled", compiled)
    if strict:
        _deadline(operation_deadline, cancellation)
        observed = shared.joint_owner._read_files(output / "compiled", set(compiled), maximum_files=shared.MAX_REVIEWED_PRESERVATION_MODULES if reviewed else 34)
        if observed != compiled:
            _fail("retained parent compiler artifacts differ on exact readback")
    for name, raw in (("cache.json", cache_raw), ("toolchain-closure.jsonl", closure_raw),
                      ("module-executions.jsonl", observation_raw)):
        if strict:
            _deadline(operation_deadline, cancellation)
        with (output / name).open("xb") as stream:
            stream.write(raw)
        if (output / name).read_bytes() != raw:
            _fail("retained native build evidence differs on readback")
    # Publish the receipt only after all referenced compiler evidence exists.
    if strict:
        _deadline(operation_deadline, cancellation)
    receipt_raw = canonical_dag_json_bytes(receipt)
    if realization_fence is not None:
        # All extensible serialization/writes have completed. Replay original
        # caller inputs once more before publishing the detached receipt.
        final_checked = replay(preparation)
        if contract_fence is not None:
            contract_fence()
            contract_fence(cache["execution_contract"])
            if prior_contract_fence is not None:
                prior_contract_fence()
        if (type(final_checked) is not shared.ReviewedPreservationCorpusPreparation
                or final_checked != checked
                or shared.reviewed_preservation_corpus_sha256(final_checked) != expected_preparation_sha256
                or _owner_pins(incremental, passes, reviewed=reviewed, manifest=checked.to_dict(),
                    instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile)) != owner_pins):
            _fail("final realization replay or producer differs from executed snapshot")
        closed_receipt = json.loads(receipt_raw)
        _deadline(operation_deadline, cancellation)
        realization_fence()
    with (output / "build-receipt.json").open("xb") as stream:
        stream.write(receipt_raw)
    if (output / "build-receipt.json").read_bytes() != receipt_raw:
        _fail("retained native build receipt differs on readback")
    if realization_fence is not None:
        # No user/product callback follows the final input/policy fence.
        return closed_receipt
    if strict:
        _deadline(operation_deadline, cancellation)
    if reviewed:
        _reviewed_policy(**_reviewed_identity_keywords(instance_identity_profile))
    return receipt


def build_incremental_shared_corpus(preparation, *, candidate_inputs, expected_population, toolchain,
        lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, cancellation=None):
    """Preserved legacy profile; parent caches and modules are deliberately separate."""
    return _build_incremental_corpus(preparation, candidate_inputs=candidate_inputs,
        expected_population=expected_population, toolchain=toolchain, lake_executable=lake_executable,
        output_directory=output_directory, previous_cache_raw=previous_cache_raw,
        expected_previous_cache_sha256=expected_previous_cache_sha256, previous_artifacts=previous_artifacts,
        timeout_seconds=timeout_seconds, cancellation=cancellation)


def build_incremental_parent_shared_corpus_v1(preparation, *, component_inputs, expected_population,
        expected_preparation_sha256, toolchain, lake_executable, output_directory,
        previous_cache_raw=None, expected_previous_cache_sha256=None, previous_artifacts=None,
        timeout_seconds=60, operation_timeout_seconds=3600, cancellation=None):
    """Replay current parent sources/reviews; reuse independently pinned technical artifacts.

    The <=60-second cumulative compiler budget excludes synchronous full source/review
    replays. The <=3600-second whole-operation deadline is checked cooperatively;
    the caller's existing owned resource timeout remains the outer hard boundary.
    Cache hits establish neither new theorem execution nor legal authority.
    """
    return _build_incremental_corpus(preparation, component_inputs=component_inputs,
        expected_population=expected_population, expected_preparation_sha256=expected_preparation_sha256,
        parent=True, toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
        previous_cache_raw=previous_cache_raw, expected_previous_cache_sha256=expected_previous_cache_sha256,
        previous_artifacts=previous_artifacts, timeout_seconds=timeout_seconds,
        operation_timeout_seconds=operation_timeout_seconds, cancellation=cancellation)


__all__ = ["build_incremental_shared_corpus", "build_incremental_parent_shared_corpus_v1"]


# Explicit reviewed mixed preservation domain. Legacy and parent public entry
# points retain their schemas, cache identities and default execution paths.
REVIEWED_CACHE_SCHEMA = "legal-corpus-reviewed-mixed-direct-lean-cache/v3"
REVIEWED_CONTRACT_SCHEMA = "legal-corpus-reviewed-mixed-direct-lean-execution-contract/v3"
REVIEWED_BUILD_SCHEMA = "legal-corpus-reviewed-mixed-incremental-native-build/v3"
REVIEWED_PROFILE = "verified-reviewed-mixed-preservation-olean-per-module/v3"
REVIEWED_SOURCE_USE_IDENTITY_PROFILE = "reviewed-source-use/v1"
REVIEWED_SOURCE_USE_BINDING_SCHEMA = "legal-native-reviewed-source-use-binding/v1"
REVIEWED_SOURCE_USE_PROFILE = REVIEWED_PROFILE + "+reviewed-source-use/v1"
_REVIEWED_ROOT = "LegalReviewedMixedNormPreservation"
_REVIEWED_MODULE = re.compile(r"(?:LegalReviewedMixedNormPreservation|Legal(?:MixedRelational|Relational)AstPreservation\.(?:Prelude|Semantics|Instance[0-9a-f]{64}))\Z")
_REVIEWED_IMPORT = re.compile(r"^import ((?:LegalReviewedMixedNormPreservation|Legal(?:MixedRelational|Relational)AstPreservation\.(?:Prelude|Semantics|Instance[0-9a-f]{64})))$", re.M)
_REVIEWED_DOMAINS = {
    "LegalRelationalAstPreservation": (
        "native_value_exact", "native_ast_closed", "denotation_matches_native",
        "typed_source_lowering_exact", "role_denotation_matches_native"),
    "LegalMixedRelationalAstPreservation": (
        "mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
        "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering"),
}
_REVIEWED_PROVENANCE_FIELDS = {"module", "role", "contributors", "dependency_units", "dependency_record_cids"}


def _reviewed_profile(instance_identity_profile):
    if instance_identity_profile is None:
        return REVIEWED_PROFILE
    if type(instance_identity_profile) is not str or instance_identity_profile != "reviewed-source-use/v1":
        _fail("explicit supported reviewed instance identity profile required")
    return REVIEWED_SOURCE_USE_PROFILE


def _reviewed_identity_keywords(instance_identity_profile):
    _reviewed_profile(instance_identity_profile)
    return {} if instance_identity_profile is None else {"instance_identity_profile": instance_identity_profile}


def _reviewed_policy(*, instance_identity_profile=None):
    _reviewed_profile(instance_identity_profile)
    if (REVIEWED_SOURCE_USE_IDENTITY_PROFILE, REVIEWED_SOURCE_USE_BINDING_SCHEMA, REVIEWED_SOURCE_USE_PROFILE) != (
            "reviewed-source-use/v1", "legal-native-reviewed-source-use-binding/v1",
            "verified-reviewed-mixed-preservation-olean-per-module/v3+reviewed-source-use/v1"):
        _fail("closed reviewed source-use identity domain differs")
    if (REVIEWED_CACHE_SCHEMA, REVIEWED_CONTRACT_SCHEMA, REVIEWED_BUILD_SCHEMA, REVIEWED_PROFILE,
            _REVIEWED_ROOT) != (
            "legal-corpus-reviewed-mixed-direct-lean-cache/v3",
            "legal-corpus-reviewed-mixed-direct-lean-execution-contract/v3",
            "legal-corpus-reviewed-mixed-incremental-native-build/v3",
            "verified-reviewed-mixed-preservation-olean-per-module/v3",
            "LegalReviewedMixedNormPreservation"):
        _fail("fixed reviewed incremental domain cannot alias another profile")
    if (any(type(value) is not int for value in (MAX_ARTIFACT_BYTES, MAX_ARTIFACT_POPULATION_BYTES,
            MAX_LIBRARY_FILES, MAX_LIBRARY_BYTES, MAX_CLOSURE_BYTES, MAX_OBSERVATION_BYTES))
            or (MAX_ARTIFACT_BYTES, MAX_ARTIFACT_POPULATION_BYTES, MAX_LIBRARY_FILES, MAX_LIBRARY_BYTES,
                MAX_CLOSURE_BYTES, MAX_OBSERVATION_BYTES) != (
                4 * 1024**2, 32 * 1024**2, 16384, 3 * 1024**3, 4 * 1024**2, 8 * 1024**2)):
        _fail("reviewed incremental execution retains the original finite bounds")
    owner = _parent_native()
    if not callable(getattr(owner, "validate_reviewed_norm_preservation_native_v3", None)):
        _fail("explicit reviewed V3 native validation interface required")
    owner._reviewed_mixed_native_policy(shared, **_reviewed_identity_keywords(instance_identity_profile))
    if _REVIEWED_DOMAINS != {
        "LegalRelationalAstPreservation": (
            "native_value_exact", "native_ast_closed", "denotation_matches_native",
            "typed_source_lowering_exact", "role_denotation_matches_native"),
        "LegalMixedRelationalAstPreservation": (
            "mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
            "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering"),
    }:
        _fail("reviewed incremental preservation theorem domains changed")


def _reviewed_flags():
    flags = _parent_flags()
    if not flags or any(value is not False for value in flags.values()):
        _fail("reviewed incremental cache grants no legal or release authority")
    return dict(flags)


def _reviewed_owner_pins(incremental, passes, manifest, *, instance_identity_profile=None):
    from ..integration.reasoning import legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps
    _reviewed_policy(**_reviewed_identity_keywords(instance_identity_profile))
    if _sha(Path(__file__).read_bytes()) != _SELF_PIN:
        _fail("reviewed incremental owner changed since import")
    owner = _parent_native()
    return owner._reviewed_mixed_preservation_native_pins(owner._owners(), manifest, **_reviewed_identity_keywords(instance_identity_profile)) | {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in (incremental, passes, legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps)
    } | {str(Path(__file__).resolve()): _SELF_PIN}


def _reviewed_replay(preparation, inputs, expected_preparation_sha256, toolchain):
    return _parent_native().validate_reviewed_norm_preservation_native_v3(
        preparation, inputs["graph"], inputs["admission"], *inputs["args"],
        expected_preservation_sha256=expected_preparation_sha256,
        expected_graph_sha256=inputs["expected_graph_sha256"],
        expected_admission_sha256=inputs["expected_admission_sha256"],
        toolchain=toolchain, **_reviewed_identity_keywords(inputs.get("instance_identity_profile")), **inputs["kwargs"])


def _reviewed_execution_snapshot(inputs):
    """Detach the opening-validated meaning used by recipes and receipts.

    Fresh replay continues to observe the original caller inputs. These copies
    supply execution provenance only, and must match both independent pins.
    """
    graph_owner, admission_owner, _ = shared._reviewed_mixed_preservation_owners()
    current = {"graph": inputs["graph"], "admission": inputs["admission"]}
    if inputs.get("instance_identity_profile") is not None:
        current["instance_identity_profile"] = inputs["instance_identity_profile"]
    detached, _ = admission_owner.norm._snapshot(current)
    if (graph_owner.norm_definition_graph_sha256(detached["graph"]) != inputs["expected_graph_sha256"]
            or admission_owner.norm_content_adjudication_sha256(detached["admission"])
                != inputs["expected_admission_sha256"]):
        _fail("opening reviewed execution snapshot differs from independent graph/admission pins")
    result = {**detached, "expected_graph_sha256": inputs["expected_graph_sha256"],
        "expected_admission_sha256": inputs["expected_admission_sha256"]}
    if inputs.get("instance_identity_profile") is not None:
        _reviewed_profile(detached["instance_identity_profile"])
        result["instance_identity_profile"] = detached["instance_identity_profile"]
    return result


def _reviewed_role(module):
    if type(module) is not str or not _REVIEWED_MODULE.fullmatch(module):
        _fail("closed reviewed preservation module identity required")
    if module == _REVIEWED_ROOT:
        return "root"
    suffix = module.split(".")[1]
    return "prelude" if suffix == "Prelude" else "semantics" if suffix == "Semantics" else "instance"


def _reviewed_graph(facts):
    """Check the preserved child import DAG independently of cache labels."""
    if type(facts) is not list or not 6 <= len(facts) <= shared.MAX_REVIEWED_PRESERVATION_MODULES:
        _fail("complete bounded reviewed preservation module population required")
    known, depths, instances, namespaces = {}, {}, [], set()
    for row in facts:
        module, imports, source = row["module"], row["imports"], row["source"]
        role = _reviewed_role(module)
        if (module in known or type(imports) is not list or len(set(imports)) != len(imports)
                or not set(imports) <= set(known)
                or imports != _REVIEWED_IMPORT.findall(source)
                or re.findall(r"^import ([^\n]+)$", source, re.M) != imports):
            _fail("complete topological reviewed import DAG and exact source imports required")
        namespace = module.split(".")[0]
        if role == "root":
            if imports != instances or not 3 <= len(instances) <= shared.MAX_REVIEWED_PRESERVATION_UNITS:
                _fail("reviewed root must import every complete ordered unit instance")
        else:
            namespaces.add(namespace)
            wanted = [] if role == "prelude" else [namespace + ".Prelude"] if role == "semantics" else [namespace + ".Semantics"]
            if imports != wanted:
                _fail("unchanged profile-specific reviewed child imports required")
        theorems = re.findall(r"^theorem ([A-Za-z0-9_]+)", source, re.M)
        if theorems != (list(_REVIEWED_DOMAINS[namespace]) if role == "instance" else []):
            _fail("five exact profile-specific preservation declarations required")
        if role == "instance":
            instances.append(module)
        depths[module] = max((depths[name] + 1 for name in imports), default=0)
        known[module] = row
    wanted = {_REVIEWED_ROOT, *instances, *(name + suffix for name in namespaces for suffix in (".Prelude", ".Semantics"))}
    if set(known) != wanted or facts[-1]["module"] != _REVIEWED_ROOT:
        _fail("complete reviewed common, instance and root population required")
    return depths



# This named consumer contract is the exact complete V3 unit emitted by the
# existing shared aggregate. It covers copied cache provenance, not a second
# admission or graph implementation. Changing that upstream row requires an
# explicit compatible profile rather than accepting or discarding extra fields.
REVIEWED_UNIT_PROVENANCE_FIELDS_V3 = frozenset({
    "ordinal", "unit_id", "kind", "source_version_cid", "source_occurrence_cid", "document_revision",
    "parent_unit_ids", "source_text_sha256", "graph_unit_record_cid", "graph_ast_record_cid", "complete_ir_sha256",
    "scope_record_cid", "interpretation_record_cid", "signature_id", "relational_request_sha256",
    "relational_report_sha256", "relational_profile", "signature_header", "signature_namespace_sha256",
    "child_preparation_sha256", "child_manifest_sha256", "child_manifest_path", "original_child_files",
    "instance_module", "preservation_obligations", "child_preservation_profile", "child_family",
})


def _reviewed_unit_provenance_v3(row, *, instance_identity_profile=None):
    from ..syntax_core import signatures
    _reviewed_profile(instance_identity_profile)
    fields = REVIEWED_UNIT_PROVENANCE_FIELDS_V3
    if instance_identity_profile is not None:
        fields = fields | {"source_use_binding", "source_use_binding_sha256"}
    contracts.require_keys(row, fields, "complete reviewed V3 unit provenance")
    ordinal = row["ordinal"]
    if type(ordinal) is not int or not 0 <= ordinal < shared.MAX_REVIEWED_PRESERVATION_UNITS:
        _fail("exact integer reviewed source ordinal required")
    for key in ("unit_id", "document_revision", "signature_id"):
        contracts.require_text(row[key], "reviewed unit " + key, max_bytes=512)
    if row["kind"] not in ("definition", "norm"):
        _fail("reviewed source unit kind differs")
    parents = row["parent_unit_ids"]
    if (type(parents) is not list or len(parents) > shared.MAX_REVIEWED_PRESERVATION_UNITS
            or any(type(parent) is not str for parent in parents)
            or len(set(parents)) != len(parents) or row["unit_id"] in parents):
        _fail("complete distinct reviewed parent-unit identifiers required")
    for parent in parents:
        contracts.require_text(parent, "reviewed parent unit", max_bytes=512)
    for key in ("complete_ir_sha256", "source_text_sha256", "relational_request_sha256", "relational_report_sha256",
                "signature_namespace_sha256", "child_preparation_sha256", "child_manifest_sha256"):
        contracts.require_sha256(row[key], "reviewed unit " + key)
    for key in ("source_version_cid", "source_occurrence_cid", "graph_unit_record_cid", "graph_ast_record_cid",
                "scope_record_cid", "interpretation_record_cid"):
        contracts.require_cid(row[key], "reviewed unit " + key)
    domain = _parent_native()._REVIEWED_MIXED_CHILD_DOMAINS.get(row["relational_profile"])
    if domain is None:
        _fail("existing reviewed child provenance domain required")
    profile, family, root, suffixes = domain
    if instance_identity_profile is not None:
        profile += "+reviewed-source-use/v1"
        binding = {"schema": "legal-native-reviewed-source-use-binding/v1", **{key: row[key] for key in (
            "unit_id", "source_version_cid", "source_occurrence_cid", "complete_ir_sha256",
            "graph_unit_record_cid", "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid")}}
        contracts.require_keys(row["source_use_binding"], set(binding), "exact reviewed source-use binding")
        contracts.require_sha256(row["source_use_binding_sha256"], "reviewed source-use binding digest")
        if (row["source_use_binding"] != binding
                or row["source_use_binding_sha256"] != _sha(canonical_dag_json_bytes(binding))):
            _fail("reviewed source-use binding must match the complete physical unit")
    if (row["child_preservation_profile"] != profile or row["child_family"] != family
            or type(row["instance_module"]) is not str
            or not re.fullmatch(re.escape(root) + r"\.Instance[0-9a-f]{64}", row["instance_module"])
            or row["preservation_obligations"] != [row["instance_module"] + "." + suffix for suffix in suffixes]):
        _fail("exact existing child namespace, family and five obligations required")
    header = row["signature_header"]
    contracts.require_keys(header, {"family", "features", "interface", "metadata", "profile", "schema_version",
        "signature_id", "sorts"}, "complete reviewed signature header")
    canonical = signatures.LogicSignature.from_dict(dict(header, symbols=[])).to_dict()
    del canonical["symbols"]
    if (canonical_dag_json_bytes(canonical) != canonical_dag_json_bytes(header)
            or row["signature_id"] != header["signature_id"]
            or row["signature_namespace_sha256"] != _sha(canonical_dag_json_bytes({
                "relational_profile": row["relational_profile"], "signature_header": header}))):
        _fail("complete typed signature header and namespace commitment differ")
    prefix = "unit-companions/" + format(ordinal, "02d") + "-"
    if row["child_manifest_path"] != prefix + "manifest.json":
        _fail("exact reviewed unit manifest locator required")
    companions = row["original_child_files"]
    if type(companions) is not list or len(companions) != 7:
        _fail("all seven original child companions required")
    names = []
    for index, item in enumerate(companions):
        contracts.require_keys(item, {"original_path", "companion_path", "sha256"}, "reviewed child companion")
        contracts.require_sha256(item["sha256"], "complete original child companion")
        if item["companion_path"] != prefix + "file-" + format(index, "02d") + ".txt":
            _fail("complete ordered reviewed child companion locator required")
        contracts.require_text(item["original_path"], "original reviewed child path", max_bytes=256)
        names.append(item["original_path"])
    wanted = {"lakefile.toml", "lean-toolchain", "preservation-inputs.json", root + ".lean",
        root + "/Prelude.lean", root + "/Semantics.lean", row["instance_module"].replace(".", "/") + ".lean"}
    if len(set(names)) != 7 or set(names) != wanted:
        _fail("complete exact reviewed child source and companion population required")
    return row


def _reviewed_recipe_provenance(module, value, *, instance_identity_profile=None):
    contracts.require_keys(value, _REVIEWED_PROVENANCE_FIELDS, "reviewed native recipe provenance")
    role = _reviewed_role(module)
    if value["module"] != module or value["role"] != role:
        _fail("reviewed provenance belongs to another module or role")
    for key in ("contributors", "dependency_units", "dependency_record_cids"):
        maximum = (shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS if key == "dependency_record_cids"
                   else shared.MAX_REVIEWED_PRESERVATION_UNITS)
        if type(value[key]) is not list or len(value[key]) > maximum:
            _fail("bounded complete reviewed provenance population required")
    contributors, dependencies = value["contributors"], value["dependency_units"]
    for rows in (contributors, dependencies):
        for row in rows:
            _reviewed_unit_provenance_v3(row, **_reviewed_identity_keywords(instance_identity_profile))
        if len({row["unit_id"] for row in rows}) != len(rows):
            _fail("reviewed provenance cannot duplicate a physical unit")
    if role == "instance":
        if len(contributors) != 1 or contributors[0]["instance_module"] != module:
            _fail("exact reviewed physical unit contributor required")
    elif role == "root":
        if not 3 <= len(contributors) <= shared.MAX_REVIEWED_PRESERVATION_UNITS:
            _fail("complete ordered reviewed root contributors required")
    elif contributors or dependencies or value["dependency_record_cids"]:
        _fail("generic preservation modules cannot invent statutory contributors")
    for cid in value["dependency_record_cids"]:
        contracts.require_cid(cid, "reviewed governing dependency record")
    if len(set(value["dependency_record_cids"])) != len(value["dependency_record_cids"]):
        _fail("reviewed governing dependency records cannot be duplicated")
    return value


def _reviewed_facts(preparation, contract, graph, *, instance_identity_profile=None):
    manifest, files = preparation.to_dict(), dict(preparation.files)
    if (contract["profile"] != _reviewed_profile(instance_identity_profile)
            or (manifest.get("instance_identity_profile") if instance_identity_profile is not None else None) != instance_identity_profile
            or (instance_identity_profile is None and "instance_identity_profile" in manifest)):
        _fail("current reviewed instance identity domain differs from explicit caller selection")
    units = manifest["units"]
    # Complete graph-unit identities include the common reviewed admission.
    # A correction may therefore invalidate an otherwise byte-identical instance
    # conservatively. Generic Prelude/Semantics reuse remains source/contract
    # based; a warm hit never carries current legal or review eligibility.
    by_unit = {row["unit_id"]: row for row in units}
    if len(by_unit) != len(units) or manifest["definition_use_record_cids"] != [row["record_cid"] for row in graph["definition_use_records"]]:
        _fail("complete reviewed graph definition-use population differs")
    edges = {key: list(row["parent_unit_ids"]) for key, row in by_unit.items()}
    for edge in graph["definition_use_records"]:
        if edge["use_unit_id"] not in by_unit or edge["definition_unit_id"] not in by_unit:
            _fail("reviewed governing dependency endpoint is outside the complete component")
        edges[edge["use_unit_id"]].append(edge["definition_unit_id"])
    def closure(unit_id, active=()):
        if unit_id in active or unit_id not in by_unit:
            _fail("cyclic or unresolved reviewed governing dependency")
        found = set()
        for name in edges[unit_id]:
            found.add(name)
            found.update(closure(name, (*active, unit_id)))
        return found
    result = []
    for module in manifest["expected_modules"]:
        role = _reviewed_role(module)
        contributors = units if role == "root" else [row for row in units if row["instance_module"] == module] if role == "instance" else []
        dependent = set().union(*(closure(row["unit_id"]) for row in contributors)) if contributors else set()
        selected = {row["unit_id"] for row in contributors} | dependent
        provenance = {"module": module, "role": role, "contributors": contributors,
            "dependency_units": [row for row in units if row["unit_id"] in dependent],
            "dependency_record_cids": [row["record_cid"] for row in graph["definition_use_records"] if row["use_unit_id"] in selected]}
        source = files[module.replace(".", "/") + ".lean"]
        imports = _REVIEWED_IMPORT.findall(source)
        if imports != manifest["module_imports"][module]:
            _fail("reviewed source imports differ from current replayed manifest")
        result.append({"module": module, "source": source, "imports": imports,
            "recipe": _recipe(module, source, imports, contract, reviewed_provenance=provenance,
                instance_identity_profile=instance_identity_profile), "output": None})
    _reviewed_graph(result)
    return result


def _reviewed_receipt(receipt, preparation, inputs, expected_preparation_sha256, timeout_seconds, operation_timeout_seconds):
    manifest = preparation.to_dict()
    return contracts.seal_record({**{key: value for key, value in receipt.items() if key not in {"record_cid", "cid_scope"}},
        **_parent_native()._reviewed_mixed_preservation_receipt_binding(manifest, inputs["admission"],
            **_reviewed_identity_keywords(inputs.get("instance_identity_profile"))),
        "expected_preparation_sha256": expected_preparation_sha256,
        "reviewed_graph_sha256": inputs["expected_graph_sha256"],
        "reviewed_admission_sha256": inputs["expected_admission_sha256"],
        "composition_obligations_checked": False,
        "concrete_preservation_obligations_checked": receipt["build_passed"],
        "compiler_timeout_seconds": timeout_seconds, "operation_timeout_seconds": operation_timeout_seconds,
        "deadline_profile": "cooperative-whole-operation; cumulative-compiler-budget-excludes-source-review-replays",
        "invalidation_scope": "Complete unit and governing-dependency rows, including common-admission-derived graph identities; conservative instance recompilation is intentional.",
        "fresh_proof_for_reused_modules": False, "original_success_authenticated": False,
        "live_native_success_authenticated": False, "original_admitted_parent_custody_authenticated": False,
        "authority": dict(_parent_native().AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "native_TDFOL_route_used": False, "native_parser_roundtrip": False,
        "reuse_scope": "Exact technical per-module artifact reuse after fresh complete reviewed V3 replay; independent child preservation only, no cross-unit governing-definition theorem, statutory truth or release admission."})


def build_incremental_reviewed_preservation_corpus_v3(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, operation_timeout_seconds=3600, cancellation=None, instance_identity_profile=None, **kwargs):
    """Replay complete current reviewed meaning; incrementally check its exact witnesses.

    This is the existing direct-Lean pass/runner algorithm in a separate domain.
    Cached proofs never replace current source, interpretation or revocation
    replay and neither this route nor a cache hit issues a release capability.
    """
    _reviewed_profile(instance_identity_profile)
    for name, pin in (("preservation", expected_preservation_sha256), ("graph", expected_graph_sha256),
                      ("admission", expected_admission_sha256)):
        contracts.require_sha256(pin, "reviewed incremental " + name)
    inputs = {"graph": graph, "admission": admission, "args": args, "kwargs": kwargs,
        "expected_graph_sha256": expected_graph_sha256, "expected_admission_sha256": expected_admission_sha256}
    if instance_identity_profile is not None:
        inputs["instance_identity_profile"] = instance_identity_profile
    return _build_incremental_corpus(preparation, reviewed_inputs=inputs, expected_population=None,
        expected_preparation_sha256=expected_preservation_sha256, toolchain=toolchain,
        lake_executable=lake_executable, output_directory=output_directory,
        previous_cache_raw=previous_cache_raw, expected_previous_cache_sha256=expected_previous_cache_sha256,
        previous_artifacts=previous_artifacts, timeout_seconds=timeout_seconds,
        operation_timeout_seconds=operation_timeout_seconds, cancellation=cancellation)


__all__ += ["REVIEWED_CACHE_SCHEMA", "REVIEWED_CONTRACT_SCHEMA", "REVIEWED_BUILD_SCHEMA", "REVIEWED_PROFILE",
    "build_incremental_reviewed_preservation_corpus_v3"]


# A constructed-model profile is a separate technical cache domain. It extends
# the same incremental compiler; neither historical cache evidence nor a warm
# artifact grants current source/review or original admitted-process authority.
REALIZATION_CACHE_SCHEMA = "legal-corpus-reviewed-definition-realization-direct-lean-cache/v1"
REALIZATION_CONTRACT_SCHEMA = "legal-corpus-reviewed-definition-realization-direct-lean-execution-contract/v1"
REALIZATION_BUILD_SCHEMA = "legal-corpus-reviewed-definition-realization-incremental-native-build/v1"
REALIZATION_PROFILE = "verified-reviewed-definition-realization-olean-per-module/v1"
_REALIZATION_ROOT = "LegalReviewedDefinitionRealization"
_REALIZATION_MODULE = re.compile(r"(?:LegalReviewedDefinitionRealization(?:\.Instance[0-9a-f]{64})?|LegalReviewedMixedNormPreservation|Legal(?:MixedRelational|Relational)AstPreservation\.(?:Prelude|Semantics|Instance[0-9a-f]{64}))\Z")
_REALIZATION_IMPORT = re.compile(r"^import ((?:LegalReviewedDefinitionRealization(?:\.Instance[0-9a-f]{64})?|LegalReviewedMixedNormPreservation|Legal(?:MixedRelational|Relational)AstPreservation\.(?:Prelude|Semantics|Instance[0-9a-f]{64})))$", re.M)
_REALIZATION_BINDING_FIELDS = {"preparation_sha256", "preservation_sha256", "graph_sha256", "admission_sha256",
    "input_commitment_sha256", "declaration_sha256", "selection", "selection_sha256", "units",
    "original_file_sha256", "producer_pins", "native_producer_pins"}


def _realization_application_keywords(definition_application_profile):
    """Keep the new selector explicit and absent from legacy callback keywords."""
    if definition_application_profile is None:
        return {}
    if (type(definition_application_profile) is not str
            or definition_application_profile != "whole-norm-definition-expansion/v1"):
        _fail("explicit supported whole-norm definition application profile required")
    return {"definition_application_profile": definition_application_profile}


def _realization_contract_fields(definition_application_profile):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is None:
        return CONTRACT_FIELDS
    if CONTRACT_FIELDS != {"profile", "toolchain", "binary_sha256", "toolchain_closure",
            "owner_pins", "platform", "argv_recipe", "environment"}:
        _fail("closed interned realization execution contract fields required")
    return CONTRACT_FIELDS | {"realization_binding"}


def _realization_contract_keywords(contract, definition_application_profile):
    """Resolve compact recipes only against their own explicit actual contract."""
    _realization_application_keywords(definition_application_profile)
    return {} if definition_application_profile is None else {"execution_contract": contract}


def _realization_preparation_binding(preparation, *, instance_identity_profile=None,
        definition_application_profile=None):
    manifest = preparation.to_dict()
    value = {"preparation_sha256": shared.reviewed_preservation_corpus_sha256(preparation),
        "preservation_sha256": manifest["reviewed_preservation_sha256"],
        "graph_sha256": manifest["reviewed_graph_sha256"],
        "admission_sha256": manifest["reviewed_admission_sha256"],
        "input_commitment_sha256": manifest["input_commitment_sha256"],
        "declaration_sha256": manifest["declaration_sha256"], "selection": manifest["selection"],
        "selection_sha256": _sha(canonical_dag_json_bytes(manifest["selection"])),
        "units": manifest["units"], "original_file_sha256": manifest["upstream_manifest"]["file_sha256"],
        "producer_pins": manifest["producer_pins"], "native_producer_pins": manifest["native_producer_pins"]}
    if instance_identity_profile is not None:
        value["instance_identity_profile"] = instance_identity_profile
    if definition_application_profile is not None:
        value.update({key: manifest[key] for key in ("definition_application_profile",
            "definition_applications", "definition_application_obligations")})
    return _realization_binding(value, **_reviewed_identity_keywords(instance_identity_profile),
        **_realization_application_keywords(definition_application_profile))


def _realization_contract_binding(contract, *, instance_identity_profile=None,
        definition_application_profile=None):
    """Validate the one complete table and its enclosing execution-contract CID."""
    if definition_application_profile is None:
        _fail("interned binding resolution requires explicit whole-norm selection")
    checked = contracts.validate_record(contract, schema=REALIZATION_CONTRACT_SCHEMA,
        fields=_realization_contract_fields(definition_application_profile))
    if checked["profile"] != _realization_profile(instance_identity_profile,
            **_realization_application_keywords(definition_application_profile)):
        _fail("interned binding belongs to another execution profile")
    record = contracts.validate_record(checked["realization_binding"],
        schema="legal-corpus-reviewed-definition-application-binding/v1", fields={"binding"})
    return _realization_binding(record["binding"], **_reviewed_identity_keywords(instance_identity_profile),
        **_realization_application_keywords(definition_application_profile))


def _realization_contract_guard(contract, *, instance_identity_profile=None,
        definition_application_profile=None):
    """Fence local and retained full contracts across extensible callbacks."""
    _realization_contract_binding(contract, **_reviewed_identity_keywords(instance_identity_profile),
        **_realization_application_keywords(definition_application_profile))
    expected = canonical_dag_json_bytes(contract)
    def fence(offered=None):
        value = contract if offered is None else offered
        if canonical_dag_json_bytes(value) != expected:
            _fail("interned realization execution contract changed during operation")
        _realization_contract_binding(value, **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
    return fence


def _realization_profile(instance_identity_profile, *, definition_application_profile=None):
    """Bind a caller-selected realization cache domain, never a saved artifact."""
    _reviewed_profile(instance_identity_profile)
    application = _realization_application_keywords(definition_application_profile)
    return (REALIZATION_PROFILE + ("+reviewed-source-use/v1" if instance_identity_profile is not None else "")
        + ("+whole-norm-definition-expansion/v1+interned-application-binding/v1" if application else ""))


def _is_realization(reviewed):
    return type(reviewed) is str and reviewed == "verified-reviewed-definition-realization-olean-per-module/v1"


def _reviewed_domain_value(reviewed, key):
    if _is_realization(reviewed):
        return {"cache": REALIZATION_CACHE_SCHEMA, "contract": REALIZATION_CONTRACT_SCHEMA,
            "build": REALIZATION_BUILD_SCHEMA, "profile": REALIZATION_PROFILE,
            "module": _REALIZATION_MODULE, "import": _REALIZATION_IMPORT, "root": _REALIZATION_ROOT}[key]
    if reviewed is not True:
        _fail("explicit supported reviewed cache domain required")
    return {"cache": REVIEWED_CACHE_SCHEMA, "contract": REVIEWED_CONTRACT_SCHEMA,
        "build": REVIEWED_BUILD_SCHEMA, "profile": REVIEWED_PROFILE,
        "module": _REVIEWED_MODULE, "import": _REVIEWED_IMPORT, "root": _REVIEWED_ROOT}[key]


def _reviewed_policy_for(reviewed):
    if _is_realization(reviewed):
        _realization_policy()
    elif reviewed is True:
        _reviewed_policy()
    else:
        _fail("explicit supported reviewed policy required")


def _reviewed_graph_for(facts, reviewed, *, instance_identity_profile=None, definition_application_profile=None, execution_contract=None):
    _realization_application_keywords(definition_application_profile)
    if definition_application_profile is not None and not (_is_realization(reviewed)):
        _fail("whole-norm definition application requires the explicit realization domain")
    return _realization_graph(facts, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile), **_realization_contract_keywords(execution_contract, definition_application_profile)) if _is_realization(reviewed) else _reviewed_graph(facts)


def _realization_policy(*, instance_identity_profile=None, definition_application_profile=None):
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    _reviewed_policy(**_reviewed_identity_keywords(instance_identity_profile))
    if (REALIZATION_CACHE_SCHEMA, REALIZATION_CONTRACT_SCHEMA, REALIZATION_BUILD_SCHEMA,
            REALIZATION_PROFILE, _REALIZATION_ROOT) != (
            "legal-corpus-reviewed-definition-realization-direct-lean-cache/v1",
            "legal-corpus-reviewed-definition-realization-direct-lean-execution-contract/v1",
            "legal-corpus-reviewed-definition-realization-incremental-native-build/v1",
            "verified-reviewed-definition-realization-olean-per-module/v1", "LegalReviewedDefinitionRealization"):
        _fail("fixed separate reviewed realization incremental domain required")
    owner = _parent_native()
    for name in ("validate_reviewed_definition_realization_native_v1",
            "_reviewed_definition_realization_native_pins", "_reviewed_definition_realization_native_manifest",
            "_reviewed_definition_realization_receipt_binding"):
        if not callable(getattr(owner, name, None)):
            _fail("explicit reviewed realization native interface required: " + name)
    owner._reviewed_definition_realization_native_policy(shared, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))


def _realization_owner_pins(incremental, passes, manifest, *, instance_identity_profile=None, definition_application_profile=None):
    from ..integration.reasoning import legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps
    _realization_policy(**_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
    if _sha(Path(__file__).read_bytes()) != _SELF_PIN:
        _fail("realization incremental owner changed since import")
    owner = _parent_native()
    return owner._reviewed_definition_realization_native_pins(owner._owners(), manifest, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile)) | {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in (incremental, passes, legal_ir_obligations, legal_ir_schema_evolution, legal_ir_source_maps)
    } | {str(Path(__file__).resolve()): _SELF_PIN}


def _realization_replay(preparation, inputs, expected_preparation_sha256, toolchain):
    definition_application_profile = inputs.get("definition_application_profile")
    _realization_profile(inputs.get("instance_identity_profile"), **_realization_application_keywords(definition_application_profile))
    return _parent_native().validate_reviewed_definition_realization_native_v1(
        preparation, inputs["preservation"], inputs["graph"], inputs["admission"], *inputs["args"],
        expected_realization_sha256=expected_preparation_sha256,
        expected_preservation_sha256=inputs["expected_preservation_sha256"],
        expected_graph_sha256=inputs["expected_graph_sha256"],
        expected_admission_sha256=inputs["expected_admission_sha256"],
        toolchain=toolchain, **inputs["kwargs"], **_reviewed_identity_keywords(inputs.get("instance_identity_profile")), **_realization_application_keywords(definition_application_profile))


def _realization_execution_snapshot(inputs):
    definition_application_profile = inputs.get("definition_application_profile")
    application = _realization_application_keywords(definition_application_profile)
    detached = _reviewed_execution_snapshot(inputs)
    offered, _ = shared._reviewed_mixed_preservation_owners()[1].norm._snapshot(
        shared._reviewed_preservation_offered(inputs["preservation"]))
    preservation = shared.ReviewedPreservationCorpusPreparation(offered["manifest_json"],
        tuple(tuple(pair) for pair in offered["files"]))
    if shared.reviewed_preservation_corpus_sha256(preservation) != inputs["expected_preservation_sha256"]:
        _fail("opening realization upstream snapshot differs from independent preservation pin")
    return {**detached, **application, "preservation": preservation,
        "expected_preservation_sha256": inputs["expected_preservation_sha256"]}


def _realization_callbacks():
    # Finite direct callback inventory, not an environment attestation. These
    # identities supplement current source pins and complete source replay.
    functions = (_realization_policy, _realization_profile, _realization_application_keywords,
        _realization_contract_fields, _realization_contract_keywords, _realization_preparation_binding,
        _realization_contract_binding, _realization_contract_guard, _reviewed_profile, _reviewed_identity_keywords, _reviewed_policy, _reviewed_policy_for, _realization_replay,
        _realization_execution_snapshot, _reviewed_execution_snapshot, _realization_guard,
        _realization_callbacks, _realization_owner_pins, _realization_facts, _realization_graph,
        _realization_recipe_provenance, _realization_binding, _realization_receipt,
        _realization_model, _realization_theorems, _reviewed_unit_provenance_v3,
        _reviewed_recipe_provenance, _reviewed_facts, _reviewed_graph, _reviewed_graph_for,
        _reviewed_domain_value, _is_realization, _build_incremental_corpus,
        _owner_pins, _owners, _parent_native, _parent_contract, _parent_execution_evidence,
        _previous, _recipe, _facts, _compiler, _run, _deadline, _sha,
        shared._write_frozen_project, shared._write_compiled, shared._reviewed_preservation_offered,
        shared.reviewed_preservation_corpus_sha256, shared.ReviewedPreservationCorpusPreparation,
        shared._reviewed_mixed_preservation_owners, canonical_dag_json_bytes,
        contracts.seal_record, contracts.load_record_bytes, contracts.validate_record,
        build_incremental_reviewed_definition_realization_corpus_v1)
    return tuple((function, getattr(function, "__code__", None)) for function in functions)


def _realization_guard(preparation, inputs, expected_preparation_sha256, toolchain):
    instance_identity_profile = inputs.get("instance_identity_profile")
    definition_application_profile = inputs.get("definition_application_profile")
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    norm = shared._reviewed_mixed_preservation_owners()[1].norm
    def offered_inputs():
        offered = {"preparation": shared._reviewed_preservation_offered(preparation),
            "preservation": shared._reviewed_preservation_offered(inputs["preservation"]),
            "graph": inputs["graph"], "admission": inputs["admission"],
            "args": list(inputs["args"]), "kwargs": inputs["kwargs"],
            "expected_preparation_sha256": expected_preparation_sha256,
            "expected_preservation_sha256": inputs["expected_preservation_sha256"],
            "expected_graph_sha256": inputs["expected_graph_sha256"],
            "expected_admission_sha256": inputs["expected_admission_sha256"], "toolchain": toolchain}
        if inputs.get("instance_identity_profile") is not None:
            offered["instance_identity_profile"] = inputs["instance_identity_profile"]
        if inputs.get("definition_application_profile") is not None:
            offered["definition_application_profile"] = inputs["definition_application_profile"]
        return offered
    _, commitment = norm._snapshot(offered_inputs())
    callbacks = _realization_callbacks()
    application_checker = (shared._reviewed_definition_application_rows
        if definition_application_profile is not None else None)
    application_checker_code = getattr(application_checker, "__code__", None)
    application_decoder = (shared._reviewed_definition_application_expression
        if definition_application_profile is not None else None)
    application_decoder_code = getattr(application_decoder, "__code__", None)
    application_contract_callbacks = ()
    if definition_application_profile is not None:
        application_contract_callbacks = tuple((name, function, function.__code__, function.__defaults__,
            tuple(sorted((function.__kwdefaults__ or {}).items())))
            for name, function in (("require_text", shared.contracts.require_text),
                ("require_int", shared.contracts.require_int)))
    flags = _reviewed_flags()
    def fence():
        _realization_policy(**_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
        if (application_checker is not None and (shared._reviewed_definition_application_rows is not application_checker
                or getattr(application_checker, "__code__", None) is not application_checker_code
                or shared._reviewed_definition_application_expression is not application_decoder
                or getattr(application_decoder, "__code__", None) is not application_decoder_code)):
            _fail("whole-norm application checker changed during incremental operation")
        for name, function, code, defaults, keyword_items in application_contract_callbacks:
            current = getattr(shared.contracts, name, None)
            if (current is not function or function.__code__ is not code
                    or function.__defaults__ is not defaults
                    or set(function.__kwdefaults__ or {}) != {key for key, _ in keyword_items}
                    or not all((function.__kwdefaults__ or {})[key] is value for key, value in keyword_items)):
                _fail("whole-norm decoded text/integer contract callback changed during incremental operation")
        if (_realization_callbacks() != callbacks or _reviewed_flags() != flags
                or norm._snapshot(offered_inputs())[1] != commitment):
            _fail("realization incremental inputs, callbacks or policy changed during operation")
    fence()
    return fence


def _realization_model(binding, *, instance_identity_profile=None, definition_application_profile=None):
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    profile = ("reviewed-unary-object-definition-realization/v1"
        + ("+reviewed-source-use/v1" if instance_identity_profile is not None else "")
        + ("+whole-norm-definition-expansion/v1" if definition_application_profile is not None else ""))
    identity = {"profile": profile, "upstream_preservation_sha256": binding["preservation_sha256"],
        "selection": binding["selection"]}
    if definition_application_profile is not None:
        identity["definition_applications"] = binding["definition_applications"]
    digest = _sha(canonical_dag_json_bytes(identity))
    return _REALIZATION_ROOT + ".Instance" + digest


def _realization_theorems(binding, *, definition_application_profile=None):
    _realization_application_keywords(definition_application_profile)
    names = ["definition_body_source_exact", "definition_realized",
        *(name for ordinal in range(len(binding["selection"]["occurrences"]))
          for name in ("occurrence_" + str(ordinal) + "_source_exact", "occurrence_" + str(ordinal) + "_matches_body")),
        *("unit_" + str(ordinal) + "_preservation_under_realization" for ordinal in range(len(binding["units"])))]

    if definition_application_profile is not None:
        names.extend(name for unit in binding["units"] if unit["kind"] == "norm"
            for name in ("unit_" + str(unit["ordinal"]) + "_expansion_source_exact",
                "unit_" + str(unit["ordinal"]) + "_whole_norm_definition_expansion"))
    return names


def _realization_binding(value, *, instance_identity_profile=None, definition_application_profile=None):
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    identity_fields = {"instance_identity_profile"} if instance_identity_profile is not None else set()
    application_fields = ({"definition_application_profile", "definition_applications", "definition_application_obligations"}
        if definition_application_profile is not None else set())
    contracts.require_keys(value, _REALIZATION_BINDING_FIELDS | identity_fields | application_fields, "complete realization cache binding")
    if definition_application_profile is not None and value["definition_application_profile"] != definition_application_profile:
        _fail("realization cache application differs from explicit caller selection")
    if instance_identity_profile is not None and value["instance_identity_profile"] != instance_identity_profile:
        _fail("realization cache identity differs from explicit caller selection")
    for key in ("preparation_sha256", "preservation_sha256", "graph_sha256", "admission_sha256",
            "input_commitment_sha256", "declaration_sha256", "selection_sha256"):
        contracts.require_sha256(value[key], "realization " + key)
    selection = value["selection"]
    contracts.require_keys(selection, {"definition_unit_id", "definition_instance_module", "definition_source_occurrence_cid",
        "definition_ir_sha256", "head_symbol", "head_roles", "definition_binder", "body_typed_path", "body_typed_node",
        "body_typed_sha256", "body_role_ast", "head_role_ast", "definition_use_records", "occurrences"}
        | ({"instance_identity_profile", "source_use_bindings"} if instance_identity_profile is not None else set()), "realization selection")
    if (value["selection_sha256"] != _sha(canonical_dag_json_bytes(selection))
            or selection["body_typed_sha256"] != _sha(canonical_dag_json_bytes(selection["body_typed_node"]))):
        _fail("exact complete realization selection/body commitments required")
    units, occurrences = value["units"], selection["occurrences"]
    if (type(units) is not list or not 3 <= len(units) <= shared.MAX_REVIEWED_PRESERVATION_UNITS
            or type(occurrences) is not list or not 2 <= len(occurrences) <= shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS):
        _fail("complete bounded realization source and occurrence populations required")
    for row in units:
        _reviewed_unit_provenance_v3(row, **_reviewed_identity_keywords(instance_identity_profile))
    if instance_identity_profile is not None:
        expected_bindings = [{"unit_id": row["unit_id"], "source_use_binding": row["source_use_binding"],
            "source_use_binding_sha256": row["source_use_binding_sha256"]} for row in units]
        if (selection["instance_identity_profile"] != instance_identity_profile
                or selection["source_use_bindings"] != expected_bindings):
            _fail("realization cache selection must bind every exact physical source use")
    by_id = {row["unit_id"]: row for row in units}
    if len(by_id) != len(units) or [row["ordinal"] for row in units] != list(range(len(units))):
        _fail("complete unique ordered realization source units required")
    definition = by_id.get(selection["definition_unit_id"])
    if (definition is None or definition["kind"] != "definition"
            or selection["definition_instance_module"] != definition["instance_module"]
            or selection["definition_source_occurrence_cid"] != definition["source_occurrence_cid"]
            or selection["definition_ir_sha256"] != definition["complete_ir_sha256"]):
        _fail("realization selection belongs to another complete definition")
    if definition_application_profile is not None:
        shared._reviewed_definition_application_rows(value["definition_applications"], selection, units,
            definition_application_profile=definition_application_profile)
        model = _realization_model(value, **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
        wanted = [model + "." + name for unit in units if unit["kind"] == "norm"
            for name in ("unit_" + str(unit["ordinal"]) + "_expansion_source_exact",
                "unit_" + str(unit["ordinal"]) + "_whole_norm_definition_expansion")]
        if value["definition_application_obligations"] != wanted:
            _fail("complete ordered whole-norm application obligations required")
    used = set()
    paths = set()
    for ordinal, occurrence in enumerate(occurrences):
        contracts.require_keys(occurrence, {"ordinal", "unit_id", "instance_module", "relational_profile",
            "definition_use_record_cid", "source_occurrence_cid", "typed_path", "typed_node", "argument",
            "binders", "ordered_roles"}, "realization original occurrence")
        unit = by_id.get(occurrence["unit_id"])
        if (type(occurrence["ordinal"]) is not int or occurrence["ordinal"] != ordinal or unit is None
                or unit["kind"] != "norm" or occurrence["instance_module"] != unit["instance_module"]
                or occurrence["relational_profile"] != unit["relational_profile"]
                or occurrence["source_occurrence_cid"] != unit["source_occurrence_cid"]
                or occurrence["ordered_roles"] != selection["head_roles"]):
            _fail("exact original typed occurrence/source/role binding required")
        contracts.require_cid(occurrence["definition_use_record_cid"], "realization governing dependency")
        path = contracts.require_text(occurrence["typed_path"], "realization occurrence path", max_bytes=4096)
        if not re.fullmatch(r"/root(?:/arguments/[01])*", path) or (unit["unit_id"], path) in paths:
            _fail("distinct exact supported original typed occurrence paths required")
        paths.add((unit["unit_id"], path))
        used.add(unit["unit_id"])
    if used != {row["unit_id"] for row in units if row["kind"] == "norm"}:
        _fail("every complete distinct norm must contribute a realization occurrence")
    for key in ("original_file_sha256", "producer_pins", "native_producer_pins"):
        table = value[key]
        if type(table) is not dict or not 1 <= len(table) <= 512:
            _fail("complete bounded realization source/producer map required")
        for name, pin in table.items():
            contracts.require_text(name, "realization source or producer path", max_bytes=4096)
            contracts.require_sha256(pin, "realization source or producer pin")
    if len(_realization_theorems(value, **_realization_application_keywords(definition_application_profile))) + 5 * len(units) > shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS:
        _fail("all realization and original obligations must fit unchanged bound")
    return value


def _realization_recipe_provenance(module, value, *, instance_identity_profile=None, definition_application_profile=None, execution_contract=None):
    binding_key = "realization_binding" if definition_application_profile is None else "realization_binding_cid"
    contracts.require_keys(value, _REVIEWED_PROVENANCE_FIELDS | {binding_key}, "realization native recipe provenance")
    if definition_application_profile is None:
        if execution_contract is not None:
            _fail("legacy inline realization provenance cannot acquire an interned contract")
        binding = _realization_binding(value[binding_key], **_reviewed_identity_keywords(instance_identity_profile))
    else:
        binding = _realization_contract_binding(execution_contract,
            **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
        contracts.require_cid(value[binding_key], "complete interned realization binding reference")
        if value[binding_key] != execution_contract["realization_binding"]["record_cid"]:
            _fail("realization recipe refers to another complete binding table")
    base = {key: item for key, item in value.items() if key != binding_key}
    if _REVIEWED_MODULE.fullmatch(module):
        _reviewed_recipe_provenance(module, base, **_reviewed_identity_keywords(instance_identity_profile))
    else:
        role = "realization" if module == _realization_model(binding, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile)) else "realization-root" if module == _REALIZATION_ROOT else None
        if (role is None or base["module"] != module or base["role"] != role
                or base["contributors"] != binding["units"] or base["dependency_units"] != binding["units"]
                or base["dependency_record_cids"] != [row["record_cid"] for row in binding["selection"]["definition_use_records"]]):
            _fail("complete exact realization contributor/dependency population required")
    return value


def _realization_graph(facts, *, instance_identity_profile=None, definition_application_profile=None, execution_contract=None):
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    if type(facts) is not list or not 8 <= len(facts) <= shared.MAX_REVIEWED_PRESERVATION_MODULES:
        _fail("complete bounded original plus realization module population required")
    depths = _reviewed_graph(facts[:-2])
    if definition_application_profile is None:
        if execution_contract is not None:
            _fail("legacy inline realization graph cannot acquire an interned contract")
        binding = _realization_binding(facts[-2]["recipe"]["realization_provenance"]["realization_binding"],
            **_reviewed_identity_keywords(instance_identity_profile))
    else:
        binding = _realization_contract_binding(execution_contract,
            **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
    model = _realization_model(binding, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
    expected_imports = [row["instance_module"] for row in binding["units"]]
    original_units = [row["module"] for row in facts[:-2] if _reviewed_role(row["module"]) == "instance"]
    if original_units != expected_imports:
        _fail("realization must retain every original ordered preservation unit")
    commitment = canonical_dag_json_bytes(binding)
    for row in facts:
        if (not _REALIZATION_MODULE.fullmatch(row["module"])
                or row["imports"] != _REALIZATION_IMPORT.findall(row["source"])
                or re.findall(r"^import ([^\n]+)$", row["source"], re.M) != row["imports"]
                or re.search(r"^\s*module(?:\s|$)", row["source"], re.M)):
            _fail("closed complete realization namespace/import/source profile required")
        provenance = row["recipe"]["realization_provenance"]
        _realization_recipe_provenance(row["module"], provenance, **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile),
            **_realization_contract_keywords(execution_contract, definition_application_profile))
        if definition_application_profile is None:
            if canonical_dag_json_bytes(provenance["realization_binding"]) != commitment:
                _fail("all realization recipes must share one complete replayed binding")
        elif (provenance["realization_binding_cid"] != execution_contract["realization_binding"]["record_cid"]
                or row["recipe"]["contract_cid"] != execution_contract["record_cid"]):
            _fail("all compact recipes must bind their exact actual execution contract and full table")
    for row, module, imports, names in (
            (facts[-2], model, expected_imports, _realization_theorems(binding, **_realization_application_keywords(definition_application_profile))),
            (facts[-1], _REALIZATION_ROOT, [_REVIEWED_ROOT, model], [])):
        if (row["module"] != module or row["imports"] != imports
                or re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M) != names):
            _fail("complete exact realization model/root/theorem population required")
        depths[module] = max(depths[name] + 1 for name in imports)
    return depths


def _realization_facts(preparation, contract, graph, *, instance_identity_profile=None, definition_application_profile=None):
    if contract["profile"] != _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile)):
        _fail("realization execution contract differs from explicit caller identity selection")
    manifest, files = preparation.to_dict(), dict(preparation.files)
    owner = _parent_native()
    owner._reviewed_definition_realization_native_manifest(manifest, shared, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile))
    upstream_manifest = manifest["upstream_manifest"]
    upstream_files = {name: files[name] for name in upstream_manifest["file_sha256"] if name != "lakefile.toml"}
    upstream_files["lakefile.toml"] = files["definition-realization-original-lakefile.txt"]
    upstream = shared.ReviewedPreservationCorpusPreparation(canonical_dag_json_bytes(upstream_manifest).decode(),
        tuple(sorted(upstream_files.items())))
    if shared.reviewed_preservation_corpus_sha256(upstream) != manifest["reviewed_preservation_sha256"]:
        _fail("complete original V3 project differs from realization upstream commitment")
    # This ephemeral view derives unchanged upstream source/provenance only.
    # Every final recipe below is rebuilt against the actual realization
    # execution contract; no cache or execution record adopts this view.
    original_contract = contracts.seal_record({**{key: value for key, value in contract.items()
        if key not in {"record_cid", "cid_scope", "realization_binding"}}, "schema": REVIEWED_CONTRACT_SCHEMA,
        "profile": _reviewed_profile(instance_identity_profile)})
    original = _reviewed_facts(upstream, original_contract, graph,
        **_reviewed_identity_keywords(instance_identity_profile))
    if definition_application_profile is None:
        binding = _realization_preparation_binding(preparation,
            **_reviewed_identity_keywords(instance_identity_profile))
        recipe_binding = {"realization_binding": binding}
    else:
        binding = _realization_contract_binding(contract, **_reviewed_identity_keywords(instance_identity_profile),
            **_realization_application_keywords(definition_application_profile))
        if binding != _realization_preparation_binding(preparation,
                **_reviewed_identity_keywords(instance_identity_profile),
                **_realization_application_keywords(definition_application_profile)):
            _fail("executed interned binding differs from the complete current preparation")
        recipe_binding = {"realization_binding_cid": contract["realization_binding"]["record_cid"]}
    result = []
    for row in original:
        provenance = {**row["recipe"]["reviewed_provenance"], **recipe_binding}
        result.append({**row, "recipe": _recipe(row["module"], row["source"], row["imports"], contract,
            realization_provenance=provenance, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile))})
    for module, role in ((_realization_model(binding, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile)), "realization"), (_REALIZATION_ROOT, "realization-root")):
        provenance = {"module": module, "role": role, "contributors": manifest["units"],
            "dependency_units": manifest["units"], "dependency_record_cids": [row["record_cid"] for row in graph["definition_use_records"]],
            **recipe_binding}
        source = files[module.replace(".", "/") + ".lean"]
        imports = _REALIZATION_IMPORT.findall(source)
        result.append({"module": module, "source": source, "imports": imports,
            "recipe": _recipe(module, source, imports, contract, realization_provenance=provenance, instance_identity_profile=instance_identity_profile, **_realization_application_keywords(definition_application_profile)), "output": None})
    if ([row["module"] for row in result] != manifest["expected_modules"]
            or {row["module"]: row["imports"] for row in result} != manifest["module_imports"]):
        _fail("complete current realization modules/imports differ from native replay")
    _realization_graph(result, **_reviewed_identity_keywords(instance_identity_profile), **_realization_application_keywords(definition_application_profile),
        **_realization_contract_keywords(contract, definition_application_profile))
    return result


def _realization_receipt(receipt, preparation, inputs, expected_preparation_sha256, timeout_seconds, operation_timeout_seconds):
    definition_application_profile = inputs.get("definition_application_profile")
    _realization_application_keywords(definition_application_profile)
    manifest = preparation.to_dict()
    return contracts.seal_record({**{key: value for key, value in receipt.items() if key not in {"record_cid", "cid_scope"}},
        **_parent_native()._reviewed_definition_realization_receipt_binding(manifest, inputs["admission"],
            **_reviewed_identity_keywords(inputs.get("instance_identity_profile")), **_realization_application_keywords(definition_application_profile)),
        "expected_preparation_sha256": expected_preparation_sha256,
        "reviewed_preservation_sha256": inputs["expected_preservation_sha256"],
        "reviewed_graph_sha256": inputs["expected_graph_sha256"], "reviewed_admission_sha256": inputs["expected_admission_sha256"],
        "composition_obligations_checked": False,
        "concrete_preservation_obligations_checked": receipt["build_passed"],
        "constructed_model_obligations_checked": receipt["build_passed"],
        "compiler_timeout_seconds": timeout_seconds, "operation_timeout_seconds": operation_timeout_seconds,
        "deadline_profile": "cooperative-whole-operation; cumulative-compiler-budget-excludes-source-review-replays",
        "invalidation_scope": "Every recipe binds the complete original V3 population, selected head/body/ordered occurrences, source/review/dependency and producer commitments; conservative recompilation is intentional.",
        "fresh_proof_for_reused_modules": False, "original_success_authenticated": False,
        "live_native_success_authenticated": False, "original_admitted_parent_custody_authenticated": False,
        "authority": dict(_parent_native().AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "native_TDFOL_route_used": False, "native_parser_roundtrip": False,
        "reuse_scope": ("Exact technical per-module artifacts after current complete V3, constructed-model and exact-source-definition-conditional whole-norm replay under unchanged arbitrary original interpretations; no unconditional equivalence, legal applicability/meaning, opaque-modal rewrite, training or release admission."
            if definition_application_profile is not None else
            "Exact technical per-module artifacts after current complete V3 and constructed-model realization replay; no arbitrary interpretation equivalence, opaque-modal rewrite, statutory truth or release admission.")})


def build_incremental_reviewed_definition_realization_corpus_v1(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, operation_timeout_seconds=3600, cancellation=None, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Replay the original V3 project and its explicit constructed-model extension.

    This uses the same per-module compiler/pass/artifact and process-custody
    machinery in a separate cache domain. It issues no original-success or
    legally accepted-meaning capability and never retags an old V3 receipt.
    """
    _realization_profile(instance_identity_profile, **_realization_application_keywords(definition_application_profile))
    for name, pin in (("realization", expected_realization_sha256), ("preservation", expected_preservation_sha256),
            ("graph", expected_graph_sha256), ("admission", expected_admission_sha256)):
        contracts.require_sha256(pin, "realization incremental " + name)
    inputs = {"preservation": preservation, "graph": graph, "admission": admission, "args": args, "kwargs": kwargs,
        "expected_preservation_sha256": expected_preservation_sha256,
        "expected_graph_sha256": expected_graph_sha256, "expected_admission_sha256": expected_admission_sha256}
    if instance_identity_profile is not None:
        inputs["instance_identity_profile"] = instance_identity_profile
    if definition_application_profile is not None:
        inputs["definition_application_profile"] = definition_application_profile
    return _build_incremental_corpus(preparation, reviewed_inputs=inputs, reviewed_domain=REALIZATION_PROFILE,
        expected_population=None, expected_preparation_sha256=expected_realization_sha256, toolchain=toolchain,
        lake_executable=lake_executable, output_directory=output_directory,
        previous_cache_raw=previous_cache_raw, expected_previous_cache_sha256=expected_previous_cache_sha256,
        previous_artifacts=previous_artifacts, timeout_seconds=timeout_seconds,
        operation_timeout_seconds=operation_timeout_seconds, cancellation=cancellation)


__all__ += ["REALIZATION_CACHE_SCHEMA", "REALIZATION_CONTRACT_SCHEMA", "REALIZATION_BUILD_SCHEMA", "REALIZATION_PROFILE",
    "build_incremental_reviewed_definition_realization_corpus_v1"]
