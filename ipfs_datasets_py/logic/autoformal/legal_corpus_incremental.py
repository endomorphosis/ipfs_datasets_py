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


def _owner_pins(incremental, passes, *, parent=False, manifest=None):
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


def _recipe(module, source, imports, contract, *, provenance=None):
    result = {"module": module, "source_sha256": _sha(source.encode("utf-8")),
              "imports": imports, "contract_cid": contract["record_cid"]}
    if provenance is not None:
        result["provenance"] = _parent_recipe_provenance(module, provenance)
    return result


def _facts(preparation, contract, *, parent=False):
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
                          provenance=provenance.get(module)), "output": None})
    known = {row["module"] for row in facts}
    if len(known) != len(facts) or any(item not in known for row in facts for item in row["imports"]):
        _fail("complete closed generated module population required")
    if parent:
        _parent_graph(facts)
    return facts


def _parent_contract(contract):
    if (contract["profile"] != PARENT_PROFILE or type(contract["toolchain"]) is not str
            or not re.fullmatch(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+", contract["toolchain"])
            or contract["environment"] != {"LEAN_PATH": "compiled", "LEAN_NUM_THREADS": "1"}
            or contract["argv_recipe"] != ["installed-sibling-lean", "-o", "compiled/<module>.olean", "<module>.lean"]):
        _fail("closed parent native execution contract differs")
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


def _parent_execution_evidence(evidence, row, facts, process, contract):
    """Validate historical sampled ownership internally; fresh scope uses its owner."""
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
            or len(command) != 4 or command[1:] != wanted or command[0] != _parent_contract(contract)
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
            {"conditional_theorems": expected}, maximum_theorems=3)
        if not passed or errors or axioms != {name: [] for name in expected}:
            _fail("strict parent conditional axiom observations differ")
    elif re.search(r"\b(?:axiom|axioms|sorry|sorryAx)\b", stdout + stderr):
        _fail("unexpected parent axiom observation without theorem declarations")
    return evidence


def _artifact_root(facts):
    return cid_for_dag_json({row["module"]: row["output"]["artifact_sha256"] for row in facts})


def _previous(raw, expected_sha256, artifacts, *, parent=False):
    if raw is None:
        if expected_sha256 is not None or artifacts is not None:
            _fail("previous cache, independent pin and complete artifacts must be supplied together")
        return None
    value = contracts.load_record_bytes(raw, expected_sha256=expected_sha256)
    flags = _parent_flags() if parent else FALSE_FLAGS
    fields = {"profile", "qualified", "execution_contract", "module_facts", "artifact_root_cid", *flags}
    value = contracts.validate_record(value, schema=PARENT_CACHE_SCHEMA if parent else CACHE_SCHEMA, fields=fields)
    if (value["profile"] != (PARENT_PROFILE if parent else PROFILE) or value["qualified"] is not True
            or any(value[key] is not False for key in flags)):
        _fail("independently pinned qualified technical cache required")
    contract = contracts.validate_record(value["execution_contract"], schema=PARENT_CONTRACT_SCHEMA if parent else CONTRACT_SCHEMA, fields=CONTRACT_FIELDS)
    if contract["profile"] != (PARENT_PROFILE if parent else PROFILE):
        _fail("prior execution contract profile differs")
    if parent:
        _parent_contract(contract)
    facts = value["module_facts"]
    if type(facts) is not list or not 1 <= len(facts) <= (34 if parent else 130) or type(artifacts) is not dict or (parent and len(artifacts) != len(facts)):
        _fail("bounded complete prior module/artifact population required")
    by_module = {row.get("module"): row for row in facts if type(row) is dict}
    if len(by_module) != len(facts) or set(by_module) != set(artifacts):
        _fail("prior artifact population differs or repeats a module")
    total = 0
    prior_bound = (min(MAX_ARTIFACT_POPULATION_BYTES,
        shared.joint_owner.MAX_PROJECT_BYTES + contracts.MAX_RECORD_BYTES) if parent else MAX_ARTIFACT_POPULATION_BYTES)
    for row in facts:
        contracts.require_keys(row, FACT_FIELDS, "prior module fact")
        module = contracts.require_text(row["module"], "prior module")
        if not (_PARENT_MODULE if parent else _MODULE).fullmatch(module):
            _fail("unsupported prior module identity")
        source = contracts.require_text(row["source"], "prior generated source", max_bytes=contracts.MAX_RECORD_BYTES)
        imports = (_PARENT_IMPORT if parent else _IMPORT).findall(source)
        if row["imports"] != imports or any(item not in by_module for item in imports):
            _fail("prior import population differs")
        provenance = row["recipe"].get("provenance") if parent and type(row["recipe"]) is dict else None
        if parent and provenance is None:
            _fail("complete parent semantic recipe required")
        recipe = _recipe(module, source, imports, contract, provenance=provenance)
        if row["recipe"] != recipe:
            _fail("prior recipe differs from its exact source and contract")
        output = contracts.require_keys(row["output"], OUTPUT_FIELDS | ({"execution_evidence"} if parent else set()), "prior native output")
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
    if parent:
        _parent_graph(facts)
        process = _parent_native()._owners()[3]
        for row in facts:
            _parent_execution_evidence(row["output"]["execution_evidence"], row, by_module, process, contract)
    if value["artifact_root_cid"] != _artifact_root(facts):
        _fail("prior artifact root differs")
    return value


def _key(module):
    return "m" + _sha(module.encode())


def _compiler(facts, functions, incremental, passes, *, parent=False):
    depths = _parent_graph(facts) if parent else {}
    def order(module):
        if parent:
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
        expected_preparation_sha256=None, parent=False, operation_timeout_seconds=3600, expected_population, toolchain,
        lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, cancellation=None):
    """Compile/reuse exact modules under the caller's shared validation lease."""
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        _fail("bounded complete incremental build timeout required")
    if (type(operation_timeout_seconds) not in (int, float) or not math.isfinite(operation_timeout_seconds)
            or not 0 < operation_timeout_seconds <= 3600):
        _fail("finite whole-operation cooperative deadline required")
    started, deadline = time.monotonic(), time.monotonic() + timeout_seconds
    operation_deadline = started + operation_timeout_seconds if parent else deadline
    if parent:
        deadline = operation_deadline
    _deadline(deadline, cancellation)
    output = shared.joint_owner._path(output_directory)
    shared.joint_owner._check_directories(output.parent, allow_missing=True)
    if output.exists() or output.is_symlink():
        _fail("fresh incremental output directory required")
    prior = _previous(previous_cache_raw, expected_previous_cache_sha256, previous_artifacts, parent=parent) if parent else None
    def replay(offered):
        _deadline(operation_deadline, cancellation)
        if parent:
            result = _parent_native().validate_parent_shared_definition_use_native_v1(offered,
                component_inputs=component_inputs, expected_population=expected_population,
                expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain)
        else:
            result = shared.validate_shared_definition_corpus(offered, candidate_inputs=candidate_inputs,
                expected_population=expected_population, toolchain=toolchain)
        _deadline(operation_deadline, cancellation)
        return result
    checked = replay(preparation)
    if parent:
        if type(checked) is not shared.ParentSharedCorpusPreparation:
            _fail("exact validated parent shared preparation type required")
        checked = shared.ParentSharedCorpusPreparation(checked.manifest_json,
            tuple((name, body) for name, body in checked.files))
        if (_parent_native().parent_shared_preparation_sha256(checked) != expected_preparation_sha256
                or _parent_native().parent_shared_preparation_sha256(preparation) != expected_preparation_sha256):
            _fail("validated parent snapshot differs from independently pinned preparation")
        deadline = min(operation_deadline, time.monotonic() + timeout_seconds)
    else:
        prior = _previous(previous_cache_raw, expected_previous_cache_sha256, previous_artifacts)
    incremental, passes, native = _owners()
    owner_pins = _owner_pins(incremental, passes, parent=parent, manifest=checked.to_dict()) if parent else _owner_pins(incremental, passes)
    _deadline(deadline, cancellation)
    # The two installed-toolchain version probes each have a five-second cap.
    if deadline - time.monotonic() < 10:
        _fail("insufficient complete build deadline for bounded version probes")
    executable, binaries, probes = native.shared._installed_toolchain(lake_executable, toolchain)
    _deadline(deadline, cancellation)
    lean = Path(executable).parent / "lean"
    closure, closure_raw = _toolchain_closure(executable, deadline, cancellation)
    contract = contracts.seal_record({"schema": PARENT_CONTRACT_SCHEMA if parent else CONTRACT_SCHEMA, "profile": PARENT_PROFILE if parent else PROFILE, "toolchain": toolchain,
        "binary_sha256": binaries, "toolchain_closure": closure, "owner_pins": owner_pins,
        "platform": {"system": platform.system(), "machine": platform.machine(), "libc": list(platform.libc_ver())},
        "argv_recipe": ["installed-sibling-lean", "-o", "compiled/<module>.olean", "<module>.lean"],
        "environment": {"LEAN_PATH": "compiled", "LEAN_NUM_THREADS": "1"}})
    facts = _facts(checked, contract, parent=parent)
    by_module = {row["module"]: row for row in facts}
    artifacts = {} if prior is None else {name: raw for name, raw in previous_artifacts.items() if name in by_module}
    old_snapshot = None
    if prior is not None:
        old_facts = prior["module_facts"]
        functions = {_key(row["module"]): (lambda _state, row=row: {"compiled": {_key(row["module"]): row["output"]}})
                     for row in old_facts}
        old_result = _run(_compiler(old_facts, functions, incremental, passes, parent=parent), old_facts)
        if not old_result.successful:
            _fail("prior module dependency graph failed independent reconstruction")
        old_snapshot = old_result.snapshot
    observations, fresh, cleanup_latch = [], [], []

    def function(row):
        def compile_module(state):
            if cleanup_latch:
                raise cleanup_latch[0]
            if parent:
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
            inputs["compiled/" + ("LegalCorpusParent" if parent else "LegalCorpus") + "/.keep"] = b""
            command = (str(lean), "-o", path, module.replace(".", "/") + ".lean")
            captured_inputs = {name: (raw.encode() if type(raw) is str else raw)
                               for name, raw in inputs.items() if not name.endswith("/.keep")}
            try:
                result = native.process.BoundedToolRunner().run(native.process.ToolRunRequest(
                    argv=command, input_files=inputs,
                    output_paths=tuple([path, *sorted(captured_inputs)]) if parent else (path,),
                    environment=contract["environment"], owned_process_observation=parent,
                    limits=native.process.ToolRunLimits(timeout_seconds=max(0.001, deadline - time.monotonic()),
                        cpu_seconds=max(0.001, deadline - time.monotonic()), resident_memory_bytes=2 * 1024**3,
                        max_output_bytes=MAX_ARTIFACT_BYTES, max_input_bytes=40 * 1024**2, max_workspace_bytes=128 * 1024**2,
                        max_output_files=len(captured_inputs) + 1 if parent else 1)),
                    **({"cancellation": cancellation} if cancellation is not None else {}))
            except native.process.OwnedToolCleanupError as error:
                if parent and not cleanup_latch:
                    cleanup_latch.append(error)
                raise
            fresh.append(module)
            observations.append({"module": module, **result.to_dict(),
                "output_files": {name: {"bytes": len(raw), "sha256": _sha(raw)} for name, raw in result.output_files.items()}})
            raw = result.output_files.get(path)
            expected_theorems = [module + "." + name for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)]
            axioms = {name: [] for name in expected_theorems if "'" + name + "' does not depend on any axioms" in result.stdout}
            passed = bool(result.ok and result.pid is not None and tuple(result.command) == command
                and set(result.output_files) == ({path, *captured_inputs} if parent else {path}) and type(raw) is bytes and 1 <= len(raw) <= MAX_ARTIFACT_BYTES
                and result.workspace_cleaned and not result.error and not result.output_truncated
                and not result.workspace_limit_exceeded and len(axioms) == len(expected_theorems)
                and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
            if parent:
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
                    _parent_execution_evidence(evidence, row, executed_facts, native.process, contract)
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
        result = _run(_compiler(facts, functions, incremental, passes, parent=parent), facts, old_snapshot)
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
        after_preparation = replay(preparation if parent else checked)
        if parent:
            if (type(after_preparation) is not shared.ParentSharedCorpusPreparation
                    or after_preparation.manifest_json != checked.manifest_json
                    or after_preparation.files != checked.files
                    or _parent_native().parent_shared_preparation_sha256(after_preparation) != expected_preparation_sha256):
                _fail("closing parent replay differs from frozen executed preparation")
            deadline = min(operation_deadline, deadline + time.monotonic() - replay_started)
        after_closure, after_raw = _toolchain_closure(executable, deadline, cancellation)
        if closure != after_closure or closure_raw != after_raw or (_owner_pins(incremental, passes, parent=True, manifest=checked.to_dict()) if parent else _owner_pins(incremental, passes)) != owner_pins:
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
        shared.joint_owner.MAX_PROJECT_BYTES + contracts.MAX_RECORD_BYTES) if parent else MAX_ARTIFACT_POPULATION_BYTES)
    if sum(map(len, retained.values())) > retained_bound:
        _fail("complete compiled artifact population exceeds exact transport byte bound" if parent
              else "complete compiled artifact population exceeds byte bound")
    artifact_root = cid_for_dag_json({name: _sha(raw) for name, raw in sorted(retained.items())})
    cache = contracts.seal_record({"schema": PARENT_CACHE_SCHEMA if parent else CACHE_SCHEMA, "profile": PARENT_PROFILE if parent else PROFILE, "qualified": qualified,
        "execution_contract": contract, "module_facts": facts, "artifact_root_cid": artifact_root, **(_parent_flags() if parent else FALSE_FLAGS)})
    cache_raw = canonical_dag_json_bytes(cache)
    reused = [row["module"] for row in facts if row["module"] not in fresh and row["output"] is not None
              and row["output"]["kernel_checked"]]
    observation_raw = b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                               for row in observations)
    if len(observation_raw) > MAX_OBSERVATION_BYTES:
        _fail("complete native execution observation byte bound exceeded")
    receipt = contracts.seal_record({"schema": PARENT_BUILD_SCHEMA if parent else BUILD_SCHEMA, "profile": PARENT_PROFILE if parent else PROFILE,
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
        "composition_obligations_checked": qualified, **(_parent_flags() if parent else FALSE_FLAGS)})
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
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.replace(".", "/") + ".olean": raw for name, raw in retained.items()}
    shared._write_compiled(output / "compiled", compiled)
    if parent:
        _deadline(operation_deadline, cancellation)
        observed = shared.joint_owner._read_files(output / "compiled", set(compiled), maximum_files=34)
        if observed != compiled:
            _fail("retained parent compiler artifacts differ on exact readback")
    for name, raw in (("cache.json", cache_raw), ("toolchain-closure.jsonl", closure_raw),
                      ("module-executions.jsonl", observation_raw)):
        if parent:
            _deadline(operation_deadline, cancellation)
        with (output / name).open("xb") as stream:
            stream.write(raw)
        if (output / name).read_bytes() != raw:
            _fail("retained native build evidence differs on readback")
    # Publish the receipt only after all referenced compiler evidence exists.
    if parent:
        _deadline(operation_deadline, cancellation)
    receipt_raw = canonical_dag_json_bytes(receipt)
    with (output / "build-receipt.json").open("xb") as stream:
        stream.write(receipt_raw)
    if (output / "build-receipt.json").read_bytes() != receipt_raw:
        _fail("retained native build receipt differs on readback")
    if parent:
        _deadline(operation_deadline, cancellation)
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
