"""Audit one pinned materialized entity cache after native child admission.

The existing parent launcher owns resource admission, process supervision,
durability and release. This helper supplies no lease or admission authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DESCRIPTOR_SHA256 = "4cb4ac3e3d9fa5857fdc4f4ad288b7c1d565cf77da83a155fbf7e5f7a5317c85"
REPOSITORY = "justicedao/uscode-autoformal-entity-cache"
REVISION = "79d54378c5d6a89ab56e7a27e0f0ba867e800e19"
REPOSITORY_PATH = "autoformal/uscode/kg-logic-index.parquet"
FILE_BYTES = 11_139_328
FILE_SHA256 = "f5f07379d4ca913cb2d8d98505a4ecb01e4d0658039a2f4ff84fb4fb585e8233"
PUBLIC_URL = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{REPOSITORY_PATH}"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_ROWS = 3_000_000
MAX_SCRATCH_BYTES = 256 * 1024 * 1024
CHECKS = ["verified_entity_cache_acquisition", "pinned_footer_population",
          "complete_entity_index_census", "entity_input_refusal_controls"]
PRODUCT_MODULES = frozenset({
    "ipfs_datasets_py", "ipfs_datasets_py.router_deps", "ipfs_datasets_py.logic",
    "ipfs_datasets_py.logic.autoformal", "ipfs_datasets_py.logic.autoformal.meta_ontology",
    "ipfs_datasets_py.logic.autoformal.legal_entity_index_intake",
})
FORBIDDEN_ROOTS = frozenset({
    "torch", "transformers", "sentence_transformers", "tensorflow", "jax", "jaxlib",
    "onnxruntime", "vllm", "diffusers", "accelerate", "huggingface_hub", "datasets",
    "multiformats", "multiformats_config", "cid", "ipfshttpclient", "ipfs_kit_py",
})
WRITE_ROOTS = {}


class AuditFailure(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise AuditFailure(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate JSON metadata key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise AuditFailure("nonfinite JSON metadata refused")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def parents_are_directories(path):
    need(path.is_absolute(), "absolute input path required")
    for parent in (path.parent, *path.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased input directory required")


def snapshot(path, maximum):
    path = Path(path)
    parents_are_directories(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and 0 < before.st_size <= maximum, "bounded single-link regular input required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    need(len(raw) == before.st_size and file_identity(before) == file_identity(after)
         == file_identity(path.lstat()), "bounded input changed while reading")
    return raw


def code_guard(pins):
    for path, expected in pins.items():
        need(type(path) is str and type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected),
             "valid frozen source pin required")
        need(sha(snapshot(Path(path), MAX_SOURCE_BYTES)) == expected, "frozen source changed")


def check_write_parent(path):
    path = Path(path)
    need(path.is_absolute() and path.parent in WRITE_ROOTS, "write outside native output directories refused")
    parents_are_directories(path)
    info = path.parent.lstat()
    need((info.st_dev, info.st_ino) == WRITE_ROOTS[path.parent]
         and stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) & 0o077 == 0,
         "native output directory identity changed")


def new_file(path):
    check_write_parent(path)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    need(len(raw) <= MAX_RECORD_BYTES, "bounded audit output required")
    with os.fdopen(new_file(path), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    need(snapshot(Path(path), MAX_RECORD_BYTES) == raw, "audit output readback differs")
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def no_forbidden_modules():
    need(not any(name.partition(".")[0] in FORBIDDEN_ROOTS for name in sys.modules),
         "model, SDK or CID runtime loaded")


class BufferLoader(importlib.abc.Loader):
    def __init__(self, path, raw):
        self.path, self.raw = path, raw

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.raw, str(self.path), "exec", dont_inherit=True, optimize=0), module.__dict__)


class DiscoveryOnlyLoader(importlib.abc.Loader):
    def __init__(self, finder):
        self.finder = finder

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.finder.refused.append(module.__name__)
        raise ImportError("discovery-only router probe cannot execute a router body")


class PinnedProductFinder(importlib.abc.MetaPathFinder):
    """Compile checked product source buffers without consulting stale pyc."""
    def __init__(self, root, pins):
        self.root, self.pins, self.loaded, self.refused = root, pins, {}, []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in FORBIDDEN_ROOTS:
            self.refused.append(fullname)
            raise ImportError("model, SDK or CID import refused")
        if fullname != "ipfs_datasets_py" and not fullname.startswith("ipfs_datasets_py."):
            return None
        if fullname == "ipfs_datasets_py.ipfs_backend_router":
            # The unchanged package initializer probes capability with find_spec.
            # Preserve its real discovery result without reading/executing the
            # router source or permitting a later unpinned router import.
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is not None:
                spec.loader = DiscoveryOnlyLoader(self)
            return spec
        if fullname not in PRODUCT_MODULES:
            self.refused.append(fullname)
            raise ImportError("product import outside entity census closure refused")
        source = self.root.joinpath(*fullname.split("."))
        package = source / "__init__.py"
        is_package = package.is_file()
        source = package if is_package else source.with_suffix(".py")
        need(str(source) in self.pins, "product source absent from frozen pin map")
        raw = snapshot(source, MAX_SOURCE_BYTES)
        need(sha(raw) == self.pins[str(source)], "product buffer differs from frozen source")
        self.loaded[fullname] = {"path": str(source), "sha256": self.pins[str(source)]}
        arguments = {"submodule_search_locations": [str(source.parent)]} if is_package else {}
        return importlib.util.spec_from_file_location(fullname, str(source),
            loader=BufferLoader(source, raw), **arguments)


def product_origins(root, pins, finder):
    result = {}
    for name, module in tuple(sys.modules.items()):
        if name != "ipfs_datasets_py" and not name.startswith("ipfs_datasets_py."):
            continue
        path = Path(module.__dict__.get("__file__", ""))
        need(name in PRODUCT_MODULES and path.is_absolute() and path.suffix == ".py"
             and root in path.parents and str(path) in pins, "unqualified loaded product origin")
        need(finder.loaded.get(name) == {"path": str(path), "sha256": pins[str(path)]},
             "product module did not execute the pinned source buffer")
        result[name] = finder.loaded[name]
    need(not finder.refused, "a forbidden import was attempted, even if its exception was suppressed")
    return result


@contextmanager
def verified_file(path):
    parents_are_directories(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == FILE_BYTES,
             "entity input is not the exact-size single-link regular file")
        digest, total = hashlib.sha256(), 0
        while chunk := stream.read(256 * 1024):
            total += len(chunk)
            need(total <= FILE_BYTES, "entity input grew beyond frozen size")
            digest.update(chunk)
        need(total == FILE_BYTES and digest.hexdigest() == FILE_SHA256, "entity input byte commitment differs")
        need(file_identity(before) == file_identity(os.fstat(stream.fileno()))
             == file_identity(path.lstat()), "entity input changed during hash")
        stream.seek(0)
        try:
            yield stream
        finally:
            need(file_identity(before) == file_identity(os.fstat(stream.fileno()))
                 == file_identity(path.lstat()), "entity input changed during checked read")


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        hostname = parsed.hostname or ""
        need(parsed.scheme == "https" and parsed.username is None and parsed.password is None
             and parsed.port in (None, 443) and not parsed.fragment
             and (hostname == "huggingface.co" or hostname.endswith(".huggingface.co")
                  or hostname == "hf.co" or hostname.endswith(".hf.co")), "nonpublic Hub redirect refused")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def acquire(path, descriptor):
    request = Request(descriptor["resolve_url"], headers={
        "Accept": "application/octet-stream", "User-Agent": "legal-entity-cache-native-audit/1"})
    digest, total = hashlib.sha256(), 0
    opener = build_opener(PublicRedirects())
    with opener.open(request, timeout=30) as response:
        need(response.status == 200, "entity acquisition HTTP status differs")
        final_hostname = urlsplit(response.geturl()).hostname
        declared = response.headers.get("Content-Length")
        need(declared is None or (declared.isdecimal() and int(declared) == FILE_BYTES),
             "entity acquisition declared byte length differs")
        with os.fdopen(new_file(path), "wb") as stream:
            while chunk := response.read(min(256 * 1024, FILE_BYTES - total + 1)):
                total += len(chunk)
                need(total <= FILE_BYTES, "entity acquisition exceeded frozen byte length")
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
    need(total == FILE_BYTES and digest.hexdigest() == FILE_SHA256, "entity acquisition hash or length differs")
    with verified_file(path):
        pass
    return {"requested_public_url": PUBLIC_URL, "final_hostname": final_hostname, "http_status": 200,
            "declared_content_length": declared, "path": str(path), "bytes": total,
            "sha256": digest.hexdigest(), "revision": REVISION, "file_payload_hash_verified": True,
            "redirect_urls_or_credentials_retained": False, "legal_source_authenticity_verified": False}


def footer_population(path, arrow, parquet):
    with verified_file(path) as stream:
        reader = parquet.ParquetFile(stream, pre_buffer=False,
            thrift_string_size_limit=1024 * 1024, thrift_container_size_limit=100_000)
        schema, metadata = reader.schema_arrow, reader.metadata
        need(type(metadata.num_rows) is int and 0 <= metadata.num_rows <= MAX_ROWS,
             "footer row count exceeds supported population")
        need(0 <= metadata.num_row_groups <= 4096 and 1 <= len(schema) <= 128,
             "footer schema or row-group population exceeds bounds")
        groups, total_rows, total_decoded = [], 0, 0
        for ordinal in range(metadata.num_row_groups):
            group = metadata.row_group(ordinal)
            sizes = [group.column(index).total_uncompressed_size for index in range(group.num_columns)]
            need(all(type(size) is int and size >= 0 for size in sizes)
                 and sum(sizes) <= 128 * 1024 * 1024, "footer row-group decoded size exceeds owner ceiling")
            total_rows += group.num_rows
            total_decoded += sum(sizes)
            groups.append({"row_group": ordinal, "rows": group.num_rows,
                           "footer_uncompressed_bytes": sum(sizes)})
        need(total_rows == metadata.num_rows and total_decoded <= 1024 * 1024 * 1024,
             "footer population sum or decoded size exceeds owner ceiling")
        result = {
            "schema": "legal-entity-cache-pinned-footer-population/v1", "repository_id": REPOSITORY,
            "revision": REVISION, "repository_path": REPOSITORY_PATH,
            "file_sha256": FILE_SHA256, "file_bytes": FILE_BYTES,
            "expected_rows_for_owner": metadata.num_rows,
            "expected_rows_origin": "footer_of_exact_hash_and_length_verified_immutable_file",
            "independent_source_corpus_census_performed": False, "viewer_row_count_used": False,
            "fields": [{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema],
            "arrow_schema_sha256": sha(schema.serialize().to_pybytes()), "row_groups": groups,
            "footer_uncompressed_bytes": total_decoded, "pyarrow_version": arrow.__version__,
            "schema_acceptance_deferred_to_unchanged_entity_index_owner": True,
        }
    return result


def refusal_controls(owner, path, trusted):
    original_rows = owner._rows
    traversal_calls = []

    def traversal_tripwire(*_args, **_kwargs):
        traversal_calls.append(True)
        raise AuditFailure("refusal control reached source-row traversal")

    controls = []
    owner._rows = traversal_tripwire
    try:
        wrong_sha = "0" * 64 if FILE_SHA256 != "0" * 64 else "1" * 64
        wrong_rows = trusted["expected_rows"] + 1 if trusted["expected_rows"] < MAX_ROWS else MAX_ROWS - 1
        for label, changed, expected_error in (
            ("wrong_expected_file_sha256", {"expected_file_sha256": wrong_sha},
             "source file differs from independently pinned SHA256"),
            ("wrong_expected_rows", {"expected_rows": wrong_rows},
             "footer row count differs from expected population"),
        ):
            try:
                owner.census_parquet(path, **{**trusted, **changed})
            except owner.EntityIndexIntakeError as error:
                need(str(error) == expected_error, "refusal control failed at an unexpected boundary")
                need(not traversal_calls, "refusal control decoded source rows")
                controls.append({"name": label, "passed": True, "error_type": type(error).__name__,
                                 "expected_error": expected_error, "source_row_traversal_calls": 0})
            else:
                raise AuditFailure("invalid entity census input was accepted")
    finally:
        owner._rows = original_rows
    need(owner._rows is original_rows, "refusal traversal tripwire was not restored")
    return {"schema": "legal-entity-cache-input-refusal-controls/v1", "controls": controls,
            "complete_censuses_repeated": 0,
            "instrumentation": "Only refusal controls temporarily replace _rows with a traversal tripwire; restored afterward."}


def main():
    need(len(sys.argv) == 2 and not sys.flags.optimize, "one native request and nonoptimized Python required")
    request_path = Path(sys.argv[1])
    request_raw = snapshot(request_path, MAX_RECORD_BYTES)
    request = decode(request_raw)
    need(type(request) is dict and request.get("schema") == "owned-validation-request/v1", "native request schema differs")
    root = Path(request["cwd"])
    need(root.is_absolute() and root == Path.cwd(), "selected native source checkout differs")
    parents_are_directories(root / "__qualified_directory_probe__")
    root_identity = (root.lstat().st_dev, root.lstat().st_ino)
    attempt = Path(request["attempt_directory"])
    layout = {name: str(attempt / name) for name in ("pytest", "tmp", "cache", "db", "exports", "logs")}
    need(request["outputs"] == layout and request["declared_external_writable_paths"] == []
         and request["process_scope"] == "isolated_process_group", "exact native output layout required")
    for spelling in (str(attempt), *layout.values()):
        path = Path(spelling)
        parents_are_directories(path / "__qualified_directory_probe__")
        info = path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) & 0o077 == 0, "private owned native directory required")
        if path != attempt:
            WRITE_ROOTS[path] = (info.st_dev, info.st_ino)
    need(request["selected_checks"] == CHECKS, "complete selected entity audit checks required")
    need(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
         and os.environ.get("TMPDIR") == layout["tmp"]
         and os.environ.get("XDG_CACHE_HOME") == layout["cache"], "native writable redirects differ")
    os.environ.update(TMPDIR=layout["tmp"], TMP=layout["tmp"], TEMP=layout["tmp"], SQLITE_TMPDIR=layout["db"],
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    tempfile.tempdir = layout["tmp"]
    pins = request["source_sha256"]
    helper_path = Path(__file__).absolute()
    descriptor_path = helper_path.with_name("input-descriptor-v01.json")
    need(type(pins) is dict and str(helper_path) in pins
         and pins.get(str(descriptor_path)) == DESCRIPTOR_SHA256, "helper and exact descriptor source pins required")
    receipt = {
        "schema": "legal-entity-cache-native-audit/v1", "status": "failed",
        "request_sha256": sha(request_raw), "selected_checks": CHECKS, "completed_checks": [],
        "repository_id": REPOSITORY, "revision": REVISION, "file_sha256": FILE_SHA256,
        "file_bytes": FILE_BYTES, "independent_source_population_census_performed": False,
        "source_semantics_verified": False, "legal_meanings_reviewed": False,
        "training_performed": False, "training_qualified": False, "lean_executed": False,
        "admitted": False, "formalized": False,
        "parent_native_owner_responsible_for_final_seal_and_release": True,
        "model_sdk_or_cid_imports_performed": False,
    }
    logs, exports = Path(layout["logs"]), Path(layout["exports"])
    stage, started, finder = "source_and_descriptor_preflight", time.monotonic(), None
    try:
        code_guard(pins)
        descriptor_raw = snapshot(descriptor_path, MAX_RECORD_BYTES)
        need(sha(descriptor_raw) == DESCRIPTOR_SHA256, "frozen input descriptor changed")
        descriptor = decode(descriptor_raw)
        expected = {"schema": "legal-entity-cache-pinned-input/v1", "repository_id": REPOSITORY,
            "revision": REVISION, "repository_path": REPOSITORY_PATH, "resolve_url": PUBLIC_URL,
            "expected_file_bytes": FILE_BYTES, "expected_file_sha256": FILE_SHA256,
            "expected_rows": None, "download_allowed_only_after_native_admission": True,
            "admitted": False, "source_semantics_verified": False}
        need(type(descriptor) is dict and all(descriptor.get(key) == value for key, value in expected.items()),
             "pinned entity input descriptor differs")
        no_forbidden_modules()
        need(not any(name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.") for name in sys.modules),
             "fresh product import process required")
        finder = PinnedProductFinder(root, pins)
        sys.meta_path.insert(0, finder)
        stage = CHECKS[0]
        entity_path = exports / "entity-cache.parquet"
        receipt["acquisition"] = acquire(entity_path, descriptor)
        receipt["completed_checks"].append(stage)
        stage = CHECKS[1]
        import pyarrow as arrow
        import pyarrow.parquet as parquet
        arrow.set_cpu_count(1)
        arrow.set_io_thread_count(1)
        footer = footer_population(entity_path, arrow, parquet)
        receipt["footer_population"] = save(exports / "footer-population.json", footer)
        receipt["expected_rows_origin"] = footer["expected_rows_origin"]
        receipt["expected_rows"] = footer["expected_rows_for_owner"]
        receipt["completed_checks"].append(stage)
        stage = CHECKS[2]
        owner = importlib.import_module("ipfs_datasets_py.logic.autoformal.legal_entity_index_intake")
        trusted = dict(expected_file_sha256=FILE_SHA256, expected_rows=footer["expected_rows_for_owner"],
            max_rows=MAX_ROWS, batch_size=512, revision=REVISION,
            max_file_bytes=FILE_BYTES, max_scratch_bytes=MAX_SCRATCH_BYTES)
        report = owner.census_parquet(entity_path, **trusted)
        need(report["rows"] == trusted["expected_rows"] == sum(report["disposition_counts"].values())
             and report["population_complete"] is True and report["coverage_scope"] == "exact_pinned_parquet_rows_only"
             and all(value is False for value in report["authority"].values()), "complete entity census invariants failed")
        need(report["source"]["file_bytes"] == FILE_BYTES
             and report["source"]["file_sha256"] == FILE_SHA256
             and report["source"]["revision"] == REVISION, "entity census source commitment differs")
        receipt["census_report"] = save(exports / "entity-index-census.json", report)
        receipt["census_sha256"] = report["census_sha256"]
        receipt["completed_checks"].append(stage)
        stage = CHECKS[3]
        receipt["refusal_controls"] = save(exports / "input-refusal-controls.json",
                                            refusal_controls(owner, entity_path, trusted))
        receipt["completed_checks"].append(stage)
        stage = "final_source_input_and_origin_guards"
        with verified_file(entity_path):
            pass
        need(snapshot(descriptor_path, MAX_RECORD_BYTES) == descriptor_raw,
             "entity descriptor changed during audit")
        need(snapshot(request_path, MAX_RECORD_BYTES) == request_raw, "native request changed during audit")
        code_guard(pins)
        no_forbidden_modules()
        receipt["loaded_product_source_origins"] = product_origins(root, pins, finder)
        need(Path.cwd() == root and (root.lstat().st_dev, root.lstat().st_ino) == root_identity,
             "source checkout identity changed during audit")
        for spelling in layout.values():
            check_write_parent(Path(spelling) / "__qualified_write_probe__")
        need(receipt["completed_checks"] == CHECKS, "not all declared entity audit checks completed")
        receipt.update(status="pass", elapsed_seconds=time.monotonic() - started,
            complete_row_censuses_performed=1,
            dependency_versions={"pyarrow": arrow.__version__, "numpy":
                getattr(sys.modules.get("numpy"), "__version__", None)},
            limitations=[
                "Population covers only the exact pinned Parquet; footer rows are not an independent source-corpus denominator.",
                "Flat node_id strings are matched exactly; primary entry_cid, candidate-node CIDs and legal IDs are not interchangeable.",
                "Missing endpoint counts combine empty/null values and nonempty dangling IDs; global empty-field counts include non-edge kinds.",
                "Duplicate node identities do not distinguish identical versus conflicting payload variants.",
                "Legacy booleans, ontology mappings and classification rules remain observations without semantic authority.",
                "Original source offsets, governing definitions, legal meaning, graph admission, model training and Lean are not verified.",
                "Producer pins bind executed Python sources; dependency versions do not authenticate installed distributions.",
                "The existing native parent owns resource supervision, final durability sealing and claim release.",
            ])
        evidence = save(logs / "entity-cache-audit.json", receipt)
        print(json.dumps({"status": "pass", "receipt": evidence, "completed_checks": CHECKS}, sort_keys=True))
        return 0
    except BaseException as error:
        receipt.update(status="failed", failure_stage=stage, error_type=type(error).__name__,
            error="Audit stage failed; exception text omitted to avoid retaining redirect credentials or source values.",
            elapsed_seconds=time.monotonic() - started)
        try:
            code_guard(pins)
            receipt["final_source_pins_unchanged"] = True
        except BaseException:
            receipt["final_source_pins_unchanged"] = False
        save(logs / "entity-cache-audit-failed.json", receipt)
        raise AuditFailure("entity cache audit failed at " + stage + " (" + type(error).__name__ + ")") from None
    finally:
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)


if __name__ == "__main__":
    raise SystemExit(main())
