"""Prepare a source/graph-bound Lean package through the existing native owner.

The bounded profile retains one joint definition/norm declaration per candidate.
It does not resolve external definitions, deduplicate their meanings, execute
Lake, or promote caller interpretations. Native owners are imported on demand.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

from . import corpus_contracts as contracts
from . import corpus_definition_norm_adapter as adapter
from . import corpus_graph, corpus_source

SCHEMA = "legal-corpus-definition-norm-lake-preparation/v1"
PROFILE = "independently-bound-section-local-joint-modules/v1"
MANIFEST_FILE = "corpus-manifest.json"
MAX_CANDIDATES = 64
MAX_INPUT_BYTES = 8 * 1024**2
MAX_PROJECT_BYTES = 8 * 1024**2
MAX_FILES = MAX_CANDIDATES + 5
INPUT_FIELDS = {"candidate_raw", "report_raw", "request_raw", "raw_html"}
POPULATION_FIELDS = {
    "candidate_sha256", "candidate_cid", "graph_cid", "request_sha256",
    "report_sha256", "raw_sha256", "extracted_sha256",
}
FALSE_FLAGS = dict.fromkeys((
    "source_semantics_verified", "source_authenticity_verified", "context_closure_verified",
    "independently_reviewed", "admitted", "formalized", "training_qualified",
    "proof_authority", "backend_executed", "lean_compilation_verified",
), False)
FIELDS = {
    "profile", "toolchain", "population", "population_cid", "bindings",
    "native_preparation_manifest", "file_sha256", "producer_pins", "preparation_only",
    "shared_definition_deduplication", "external_definition_resolution", "expected_modules",
    "hash_recipes", *FALSE_FLAGS,
}
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+")


@dataclass(frozen=True)
class CorpusPreparation:
    """Immutable generated text plus a sealed, externally reproducible manifest."""

    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _stable_stat(item):
    return (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)


def _path(value):
    try:
        path = Path(value).absolute()
    except (TypeError, ValueError) as error:
        raise contracts.CorpusContractError("ordinary corpus directory path required") from error
    if ".." in path.parts or "\x00" in str(path):
        _fail("corpus directory traversal is refused")
    return path


def _check_directories(path, descriptor=None, *, allow_missing=False):
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            _fail("corpus paths must use ordinary directories without symlinks")
    if descriptor is not None:
        current, opened = path.lstat(), os.fstat(descriptor)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            _fail("corpus directory changed during operation")


def _pins():
    modules = (contracts, adapter, corpus_graph, corpus_source, cid_utils)
    paths = [Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in modules)]
    return {str(path): _sha(path.read_bytes()) for path in paths}


def _population(candidate_inputs, expected_population):
    if (type(candidate_inputs) is not list or type(expected_population) is not list
            or not 1 <= len(candidate_inputs) <= MAX_CANDIDATES
            or len(candidate_inputs) != len(expected_population)):
        _fail("complete ordered candidate and independently pinned population required")
    population = contracts.clone_json(expected_population)
    total = 0
    for inputs, pins in zip(candidate_inputs, population, strict=True):
        contracts.require_keys(inputs, INPUT_FIELDS, "candidate byte inputs")
        contracts.require_keys(pins, POPULATION_FIELDS, "independent population pins")
        for key in POPULATION_FIELDS - {"candidate_cid", "graph_cid"}:
            contracts.require_sha256(pins[key], key)
        for key in ("candidate_cid", "graph_cid"):
            contracts.require_cid(pins[key], key, codecs=("dag-json",))
        for key, raw in inputs.items():
            limit = adapter.MAX_RAW_HTML_BYTES if key == "raw_html" else contracts.MAX_RECORD_BYTES
            if type(raw) is not bytes or not 1 <= len(raw) <= limit:
                _fail("bounded nonempty ordinary candidate input bytes required")
            total += len(raw)
            if total > MAX_INPUT_BYTES:
                _fail("complete input byte bound exceeded; no candidate may be omitted")
    for key in ("candidate_cid", "graph_cid"):
        if len({row[key] for row in population}) != len(population):
            _fail("duplicate candidate or graph identity in complete population")
    return population


def prepare_definition_norm_corpus(candidate_inputs, *, expected_population, toolchain):
    """Regenerate every candidate and delegate a complete ordered native batch.

    Population pins must originate independently of the incoming files. Exact
    request/report/source bytes and full candidate companions remain necessary
    for replay; this package stores their identities and generated request text.
    Duplicate native (norm_id, family) identities fail without rewriting inputs.
    """
    population = _population(candidate_inputs, expected_population)
    if type(toolchain) is not str or not _TOOLCHAIN.fullmatch(toolchain):
        _fail("version-pinned Lean toolchain required")
    producer_pins = _pins()
    candidates, requests, reports = [], [], []
    for inputs, pins in zip(candidate_inputs, population, strict=True):
        candidate = contracts.load_record_bytes(
            inputs["candidate_raw"], expected_sha256=pins["candidate_sha256"])
        candidate = adapter.validate_definition_norm_candidate(
            candidate, inputs["report_raw"], expected_report_sha256=pins["report_sha256"],
            request_raw=inputs["request_raw"], expected_request_sha256=pins["request_sha256"],
            raw_html=inputs["raw_html"], expected_raw_sha256=pins["raw_sha256"],
            expected_extracted_sha256=pins["extracted_sha256"],
        )
        if (candidate["record_cid"] != pins["candidate_cid"]
                or candidate["graph"]["record_cid"] != pins["graph_cid"]):
            _fail("candidate or graph differs from independent population identity")
        candidates.append(candidate)
        requests.append(contracts.load_record_bytes(
            inputs["request_raw"], expected_sha256=pins["request_sha256"]))
        reports.append(contracts.load_record_bytes(
            inputs["report_raw"], expected_sha256=pins["report_sha256"]))

    from . import legal_source_definition_norm_lake as owner

    try:
        native = owner.prepare(requests, toolchain=toolchain)
        owner.validate(native)
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        raise contracts.CorpusContractError("native corpus preparation refused: " + str(error)) from error
    native_manifest = native.to_dict()
    if len(native_manifest["bindings"]) != len(population):
        _fail("native preparation omitted a candidate")
    files = dict(native.files)
    if len(files) != len(native.files) or len(files) > MAX_FILES or MANIFEST_FILE in files:
        _fail("native preparation has duplicate, reserved or excessive files")
    expected_paths = {
        "lakefile.toml", "lean-toolchain", "LegalDefinitionNorm/Prelude.lean",
        "definition-inputs.json", "LegalDefinitionNorm.lean",
        *(f"LegalDefinitionNorm/Definition{index:04d}.lean" for index in range(len(population))),
    }
    if set(files) != expected_paths:
        _fail("native preparation file population differs from complete module coverage")
    if sum(len(body.encode("utf-8")) for body in files.values()) > MAX_PROJECT_BYTES:
        _fail("complete generated project exceeds byte bound")
    bindings = []
    for ordinal, (candidate, request, report, native_binding) in enumerate(zip(
            candidates, requests, reports, native_manifest["bindings"], strict=True)):
        module = f"LegalDefinitionNorm.Definition{ordinal:04d}"
        module_path = module.replace(".", "/") + ".lean"
        if (native_binding["module"] != module
                or native_binding["norm_id"] != report["norm_id"]
                or native_binding["family"] != report["family"]
                or native_binding["request_sha256"] != owner.bridge.digest(request)
                or native_binding["bridge_sha256"] != owner.bridge.digest(report)
                or native_binding["native_ast_sha256"] != owner.bridge.digest(candidate["ast_record"]["native_ast"])
                or files.get(module_path) != "import LegalDefinitionNorm.Prelude\nnamespace " + module
                + "\n" + candidate["ast_record"]["lean_body"] + "\nend " + module + "\n"):
            _fail("native source, AST, request or ordered module coverage differs")
        assertion_nodes = {
            node["node_type"]: node["record_cid"] for node in candidate["graph"]["nodes"]
            if node["node_type"] in corpus_graph.ASSERTIONS
        }
        semantic_nodes = [
            {"node_type": node["node_type"], "node_cid": node["record_cid"],
             "content_cid": node["content_cid"]}
            for node in candidate["graph"]["nodes"]
            if node["node_type"] in {"definition_assertion", "norm_assertion", "scope", "term_sense", "expression"}
        ]
        definition_edges = [
            {"relation": edge["relation"], "edge_cid": edge["record_cid"],
             "src_cid": edge["src_cid"], "dst_cid": edge["dst_cid"]}
            for edge in candidate["graph"]["edges"]
            if edge["relation"] in {"DEFINES", "USES_DEFINITION"}
        ]
        bindings.append({
            "ordinal": ordinal, "candidate_cid": candidate["record_cid"],
            "graph_cid": candidate["graph"]["record_cid"],
            **{key + "_cid": candidate[key]["record_cid"] for key in (
                "source_version", "definition_record", "norm_record", "ast_record",
                "scope_record", "term_record", "symbol_record",
            )},
            "source_occurrence_cids": [row["record_cid"] for row in candidate["source_occurrences"]],
            "source_bindings": candidate["source_bindings"],
            "source_occurrences": [{key: occurrence[key] for key in (
                "record_cid", "source_version_cid", "start_char", "end_char", "start_utf8", "end_utf8",
            )} for occurrence in candidate["source_occurrences"]],
            "graph_assertion_node_cids": assertion_nodes,
            "semantic_nodes": semantic_nodes, "definition_edges": definition_edges,
            "module": module, "module_path": module_path,
            "module_sha256": _sha(files[module_path].encode("utf-8")),
            "declaration": "formula_0", "qualified_declaration": module + ".formula_0",
            "native_binding": native_binding,
        })
    if _pins() != producer_pins:
        _fail("corpus preparation implementation changed during regeneration")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain,
        "population": population, "population_cid": cid_for_dag_json(population),
        "bindings": bindings, "native_preparation_manifest": native_manifest,
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": producer_pins, "preparation_only": True,
        "expected_modules": ["LegalDefinitionNorm.Prelude", *[row["module"] for row in bindings],
                             "LegalDefinitionNorm"],
        "hash_recipes": {
            "population_file_hashes": "SHA256 of exact original input file bytes",
            "native_request_and_bridge_hashes": "SHA256 of existing owner's canonical wire(request/report)",
            "file_sha256": "SHA256 of exact generated UTF8 file bytes; excludes corpus-manifest.json",
        },
        "shared_definition_deduplication": False, "external_definition_resolution": False,
        **FALSE_FLAGS,
    })
    return CorpusPreparation(canonical_dag_json_bytes(manifest).decode("utf-8"), tuple(sorted(files.items())))


def validate_definition_norm_corpus(preparation, *, candidate_inputs, expected_population, toolchain):
    """Rebuild all source, graph and generated-file mappings from external pins."""
    if type(preparation) is not CorpusPreparation:
        _fail("typed corpus preparation required")
    contracts.validate_record(preparation.to_dict(), schema=SCHEMA, fields=FIELDS)
    expected = prepare_definition_norm_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    if preparation != expected:
        _fail("corpus preparation differs from independent complete regeneration")
    return preparation


def _read_files(directory, expected_names):
    """Read the closed two-level generated project without following symlinks."""
    root = _path(directory)
    _check_directories(root)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    root_fd = os.open(root, flags | os.O_DIRECTORY)
    descriptors = {"": root_fd}
    try:
        _check_directories(root, root_fd)
        expected_by_directory = {"": set()}
        for name in expected_names:
            parts = name.split("/")
            if (len(parts) > 2 or any(part in ("", ".", "..") for part in parts)
                    or "\\" in name):
                _fail("unsupported generated file path")
            expected_by_directory[""].add(parts[0])
            if len(parts) == 2:
                expected_by_directory.setdefault(parts[0], set()).add(parts[1])
        for name in sorted(expected_by_directory):
            if name:
                descriptors[name] = os.open(name, flags | os.O_DIRECTORY, dir_fd=root_fd)
            fd = descriptors[name]
            with os.scandir(fd) as entries:
                observed = set()
                for entry in entries:
                    observed.add(entry.name)
                    if (entry.is_symlink() or entry.name not in expected_by_directory[name]
                            or len(observed) > MAX_FILES + 1):
                        _fail("unexpected or linked corpus project entry")
            if observed != expected_by_directory[name]:
                _fail("incomplete corpus project entries")
        total, result = 0, {}
        for name in sorted(expected_names):
            directory_name, _, basename = name.rpartition("/")
            fd = os.open(basename, flags, dir_fd=descriptors[directory_name])
            with os.fdopen(fd, "rb") as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PROJECT_BYTES:
                    _fail("bounded ordinary generated project file required")
                raw = source.read(MAX_PROJECT_BYTES + 1)
                after = os.fstat(source.fileno())
                current = os.stat(basename, dir_fd=descriptors[directory_name], follow_symlinks=False)
                if (_stable_stat(before) != _stable_stat(after) or _stable_stat(before) != _stable_stat(current)
                        or len(raw) != before.st_size):
                    _fail("generated file changed while reading")
            total += len(raw)
            if total > MAX_PROJECT_BYTES + contracts.MAX_RECORD_BYTES:
                _fail("complete corpus project byte bound exceeded")
            result[name] = raw
        _check_directories(root, root_fd)
        return result
    finally:
        for fd in reversed(list(descriptors.values())):
            os.close(fd)


def load_definition_norm_corpus(directory, *, expected_manifest_sha256,
                                candidate_inputs, expected_population, toolchain):
    """Verify exact closed project bytes against a regenerated preparation."""
    expected = prepare_definition_norm_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    files = _read_files(directory, {name for name, _ in expected.files} | {MANIFEST_FILE})
    manifest_raw = files.pop(MANIFEST_FILE)
    manifest = contracts.load_record_bytes(manifest_raw, expected_sha256=expected_manifest_sha256)
    if manifest_raw != expected.manifest_json.encode("utf-8") or manifest != expected.to_dict():
        _fail("corpus manifest differs from independent regeneration")
    if files != {name: body.encode("utf-8") for name, body in expected.files}:
        _fail("generated corpus source differs from independent regeneration")
    return expected


def write_definition_norm_corpus(preparation, directory, *, candidate_inputs,
                                 expected_population, toolchain):
    """Write a fresh local project; publish its manifest after exact file readback."""
    checked = validate_definition_norm_corpus(
        preparation, candidate_inputs=candidate_inputs,
        expected_population=expected_population, toolchain=toolchain)
    root = _path(directory)
    _check_directories(root.parent, allow_missing=True)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    descriptors = {"": root_fd}
    try:
        _check_directories(root, root_fd)
        for name, body in checked.files:
            _check_directories(root, root_fd)
            dirname, _, basename = name.rpartition("/")
            if dirname and dirname not in descriptors:
                os.mkdir(dirname, mode=0o700, dir_fd=root_fd)
                descriptors[dirname] = os.open(
                    dirname, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=root_fd)
            _write_new_file(descriptors[dirname], basename, body.encode("utf-8"))
        for fd in descriptors.values():
            os.fsync(fd)
        if _read_files(root, {name for name, _ in checked.files}) != {
                name: body.encode("utf-8") for name, body in checked.files}:
            _fail("generated corpus source failed pre-manifest readback")
        manifest_raw = checked.manifest_json.encode("utf-8")
        _write_new_file(root_fd, MANIFEST_FILE, manifest_raw)
        os.fsync(root_fd)
        load_definition_norm_corpus(
            root, expected_manifest_sha256=_sha(manifest_raw), candidate_inputs=candidate_inputs,
            expected_population=expected_population, toolchain=toolchain)
        _check_directories(root, root_fd)
    finally:
        for fd in reversed(list(descriptors.values())):
            os.close(fd)
    return checked.to_dict()


def _write_new_file(parent_fd, basename, raw):
    fd = os.open(basename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 mode=0o600, dir_fd=parent_fd)
    with os.fdopen(fd, "wb") as destination:
        destination.write(raw)
        destination.flush()
        os.fsync(destination.fileno())


__all__ = [
    "CorpusPreparation", "prepare_definition_norm_corpus", "validate_definition_norm_corpus",
    "write_definition_norm_corpus", "load_definition_norm_corpus",
]
