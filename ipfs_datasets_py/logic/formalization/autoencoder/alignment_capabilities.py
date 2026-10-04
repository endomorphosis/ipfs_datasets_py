"""Read-only alignment capability inventory, never execution or proof admission.

Catalog declarations, PATH discovery, saved receipts, and current verification
remain separate. This module imports no solver, starts no process, reads no
credentials, and reads only a bounded GGUF metadata prefix, never model tensors.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import struct
from pathlib import Path
from typing import Any, BinaryIO

SCHEMA_VERSION = "autoformal-alignment-capabilities/v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_GGUF_METADATA_BYTES = 16 * 1024 * 1024
_QUALIFICATION = "workspace/generic-prover-admission-qualification-20261003"
_COMMANDS = {
    "z3": ("z3",), "cvc5": ("cvc5",), "vampire": ("vampire",),
    "eprover": ("eprover",), "lean": ("lean", "lake"),
    "rocq": ("rocq", "coqc"), "isabelle": ("isabelle",),
    "tla_tlc": ("tlc",), "apalache": ("apalache-mc",),
    "proverif": ("proverif",), "tamarin": ("tamarin-prover",),
    "hyperltl_autohyper_mchyper": ("autohyper", "mchyper"),
}


def _read_regular(path: Path, limit: int) -> bytes:
    """Reject devices/FIFOs and oversized files before bounded reads."""
    # Nonblocking open also prevents a swapped-in FIFO from blocking before fstat.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not_regular_file")
        if info.st_size > limit:
            raise ValueError("file_size_limit")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("file_size_limit")
        return data


def _binding(path: Path, limit: int = MAX_SOURCE_BYTES) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "status": "unavailable"}
    try:
        data = _read_regular(path, limit)
    except (OSError, ValueError) as error:
        result["reason"] = (str(error) if isinstance(error, ValueError)
                            else type(error).__name__)
    else:
        result.update(status="read", size_bytes=len(data),
                      sha256=hashlib.sha256(data).hexdigest())
    return result


def _json_record(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    binding = _binding(path, MAX_JSON_BYTES)
    if binding["status"] != "read":
        return binding, None
    try:
        data = _read_regular(path, MAX_JSON_BYTES)
        if hashlib.sha256(data).hexdigest() != binding["sha256"]:
            raise ValueError("file_changed_during_inventory")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = value
            return result
        result = json.loads(data, object_pairs_hook=unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict):
            raise ValueError("json_object_required")
    except (OSError, ValueError, RecursionError) as error:
        binding.update(status="invalid", reason=type(error).__name__)
        return binding, None
    return binding, result


class _GGUFMetadataReader:
    """Hash and parse only the metadata prefix, with byte/count/depth bounds."""

    _SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
                6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}

    def __init__(self, stream: BinaryIO):
        self.stream, self.used = stream, 0
        self.digest = hashlib.sha256()

    def read(self, count: int) -> bytes:
        if count < 0 or self.used + count > MAX_GGUF_METADATA_BYTES:
            raise ValueError("metadata_byte_limit")
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError("truncated_metadata")
        self.used += count
        self.digest.update(data)
        return data

    def number(self, code: str) -> Any:
        return struct.unpack("<" + code, self.read(struct.calcsize("<" + code)))[0]

    def discard(self, count: int) -> None:
        if self.used + count > MAX_GGUF_METADATA_BYTES:
            raise ValueError("metadata_byte_limit")
        while count:
            chunk = min(count, 65536)
            self.read(chunk)
            count -= chunk

    def string(self, keep: bool = True) -> str | None:
        count = self.number("Q")
        if count > 1024 * 1024:
            raise ValueError("metadata_string_limit")
        if keep:
            return self.read(count).decode("utf-8")
        self.discard(count)
        return None

    def value(self, kind: int, keep: bool = False, depth: int = 0) -> Any:
        if kind in self._SCALARS:
            return self.number(self._SCALARS[kind])
        if kind == 8:
            return self.string(keep)
        if kind != 9 or depth >= 2:
            raise ValueError("unsupported_metadata_type")
        element, count = self.number("I"), self.number("Q")
        if count > 524288:
            raise ValueError("metadata_array_limit")
        if element in self._SCALARS:
            self.discard(count * struct.calcsize("<" + self._SCALARS[element]))
        else:
            for _ in range(count):
                self.value(element, False, depth + 1)
        return None


def _gguf_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "status": "unavailable",
                              "tensors_loaded": False, "full_model_hash_verified": False}
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not_regular_file")
            reader = _GGUFMetadataReader(stream)
            if reader.read(4) != b"GGUF":
                raise ValueError("invalid_gguf_magic")
            version = reader.number("I")
            if version not in (2, 3):
                raise ValueError("unsupported_gguf_version")
            tensors, count = reader.number("Q"), reader.number("Q")
            if count > 4096:
                raise ValueError("metadata_entry_limit")
            selected: dict[str, Any] = {}
            seen: set[str] = set()
            for _ in range(count):
                key = reader.string()
                if key is None or len(key) > 256 or key in seen:
                    raise ValueError("invalid_or_duplicate_metadata_key")
                seen.add(key)
                keep = key == "general.architecture" or any(key.endswith("." + suffix) for suffix in
                    ("embedding_length", "embedding_length_out", "block_count", "context_length", "expert_count"))
                value = reader.value(reader.number("I"), keep)
                if keep:
                    selected[key] = value
            architecture = selected.get("general.architecture")
            if not isinstance(architecture, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", architecture):
                raise ValueError("architecture_required")
            width = selected.get(architecture + ".embedding_length")
            if type(width) is not int or not 1 <= width <= 65536:
                raise ValueError("embedding_width_required")
            for key, value in selected.items():
                if key != "general.architecture" and (type(value) is not int or not 1 <= value <= 2**40):
                    raise ValueError("invalid_architecture_metadata")
            result.update(status="metadata_read", version=version, tensor_count=tensors,
                size_bytes=info.st_size, metadata_bytes=reader.used,
                metadata_prefix_sha256=reader.digest.hexdigest(), architecture=architecture,
                native_hidden_dimension=width,
                native_output_dimension=selected.get(architecture + ".embedding_length_out", width),
                architecture_metadata={key: value for key, value in selected.items()
                                       if key == "general.architecture" or key.startswith(architecture + ".")})
    except (OSError, ValueError, UnicodeError, struct.error) as error:
        result.update(status="invalid" if isinstance(error, (ValueError, struct.error)) else "unavailable",
                      reason=str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError)
                      else type(error).__name__)
    return result


def _path_expression(node: ast.AST, constants: dict[str, ast.AST], depth: int = 0) -> Path:
    if depth > 5:
        raise ValueError("path_expression_depth")
    if isinstance(node, ast.Name) and node.id in constants:
        return _path_expression(constants[node.id], constants, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = ast.literal_eval(node.right)
        if not isinstance(right, str):
            raise ValueError("path_string_required")
        return _path_expression(node.left, constants, depth + 1) / right
    if isinstance(node, ast.Call) and not node.keywords:
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1:
            value = ast.literal_eval(node.args[0])
            if isinstance(value, str):
                return Path(value)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "home" and
                isinstance(node.func.value, ast.Name) and node.func.value.id == "Path" and not node.args):
            return Path.home()
    raise ValueError("unsupported_path_expression")


def _runner_description(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"source": _binding(path), "status": "unavailable",
                              "execution_performed": False}
    if result["source"]["status"] != "read":
        return result
    try:
        source = _read_regular(path, MAX_SOURCE_BYTES)
        if hashlib.sha256(source).hexdigest() != result["source"]["sha256"]:
            raise ValueError("runner_changed_during_inventory")
        tree = ast.parse(source)
        constants = {node.targets[0].id: node.value for node in tree.body
                     if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
        command = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "server_argv")
        flags = {node.value for node in ast.walk(command) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        result.update(status="source_inspected", embedding_endpoint_configured=bool(flags & {"--embedding", "--embeddings"}),
                      mode="embedding" if flags & {"--embedding", "--embeddings"} else "chat",
                      default_model_path=str(_path_expression(constants["DEFAULT_MODEL"], constants)),
                      declared_flags=sorted(flag for flag in flags if flag.startswith("--")))
        if "CACHE" in constants:
            result["cache_root"] = str(_path_expression(constants["CACHE"], constants))
        defaults = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                for keyword in node.keywords:
                    if keyword.arg == "default" and node.args[0].value == "--binary":
                        result["default_binary_path"] = str(_path_expression(keyword.value, constants))
                    if keyword.arg == "default" and node.args[0].value in {"--context", "--memory-gib", "--cpus", "--tasks", "--gpu-layers"}:
                        value = ast.literal_eval(keyword.value)
                        if type(value) in (int, float):
                            defaults[node.args[0].value] = value
        result["declared_resource_defaults"] = defaults
        for node in ast.walk(command):
            if isinstance(node, (ast.List, ast.Tuple)):
                for index, item in enumerate(node.elts[:-1]):
                    if isinstance(item, ast.Constant) and item.value in {"--batch-size", "--ubatch-size"}:
                        value = ast.literal_eval(node.elts[index + 1])
                        if isinstance(value, str) and value.isdecimal():
                            defaults[item.value] = int(value)
    except (KeyError, StopIteration, OSError, ValueError, SyntaxError, TypeError) as error:
        result.update(status="invalid", reason=type(error).__name__)
    return result


def _saved_execution(repository: Path) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    report = _binding(repository / _QUALIFICATION / "REPORT.md")
    binding, data = _json_record(repository / _QUALIFICATION / "native-final/result.json")
    record: dict[str, Any] = {"report": report, "result": binding, "status": "unavailable",
        "replayed": False, "receipts_verified": False, "current_proof_authority": "none"}
    counts: dict[str, dict[str, int]] = {}
    if data is None:
        return record, counts
    if data.get("schema") != "generic-prover-admission-benchmark@1" or not isinstance(data.get("runs"), list):
        record.update(status="invalid", reason="unsupported_saved_record")
        return record, counts
    for run in data["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("cases"), list):
            record.update(status="invalid", reason="malformed_saved_cases")
            return record, {}
        for case in run["cases"]:
            if not isinstance(case, dict):
                record.update(status="invalid", reason="malformed_saved_case")
                return record, {}
            provider = {"lean": "lean", "rocq": "rocq", "tlc": "tla_tlc"}.get(case.get("kind"))
            if provider is None:
                continue
            summary = counts.setdefault(provider, {"reported_cases": 0, "saved_receipts_present": 0})
            summary["reported_cases"] += 1
            outcome = case.get("outcome")
            receipt = outcome.get("receipt") if isinstance(outcome, dict) else None
            if isinstance(receipt, dict) and isinstance(receipt.get("schema_version"), str) and receipt.get("request_digest"):
                summary["saved_receipts_present"] += 1
    record.update(status="hash_bound_historical_record", reported_status=data.get("status")
                  if data.get("status") in {"passed", "failed"} else "unknown", provider_summaries=counts,
                  scope="historical startup fixtures only; receipt presence is not verification")
    return record, counts


def _trust_policy(repository: Path) -> dict[str, Any]:
    path = repository / "ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_router.py"
    result: dict[str, Any] = {"source": _binding(path), "status": "unavailable",
                              "inventory_authority": "none"}
    if result["source"]["status"] != "read":
        return result
    try:
        raw = _read_regular(path, MAX_SOURCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != result["source"]["sha256"]:
            raise ValueError("policy_changed_during_inventory")
        tree = ast.parse(raw)
        levels = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ProofTrustLevel")
        policy = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ProofRoutingPolicy")
        tiers = {node.targets[0].id: ast.literal_eval(node.value) for node in levels.body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and isinstance(node.value, ast.Constant) and type(node.value.value) is int}
        required = next(node.value for node in policy.body if isinstance(node, ast.AnnAssign)
                        and isinstance(node.target, ast.Name) and node.target.id == "required_trust")
        if not isinstance(required, ast.Attribute) or not isinstance(required.value, ast.Name) or required.value.id != "ProofTrustLevel":
            raise ValueError("unsupported_default_trust")
        if required.attr not in tiers:
            raise ValueError("unknown_default_trust")
        result.update(status="source_inspected", declared_tiers=tiers,
                      default_required_trust=required.attr.lower(),
                      kernel_required_for_kernel_claim=True, policy_executed=False)
    except (OSError, StopIteration, ValueError, SyntaxError, TypeError) as error:
        result.update(status="invalid", reason=type(error).__name__)
    return result


def describe_alignment_capabilities(repository_root: Path | str, workspace_root: Path | str | None = None) -> dict[str, Any]:
    """Inventory canonical declarations and bounded local evidence without probes.

    ``repository_root`` is the datasets checkout; ``workspace_root`` may name
    its enclosing lift workspace. No subprocess, service, install, proof replay,
    or network request is performed. Missing evidence always remains explicit.
    """
    repository = Path(repository_root).resolve()
    if workspace_root is None and repository.parent.name == "external":
        workspace = repository.parent.parent
    else:
        workspace = Path(workspace_root).resolve() if workspace_root is not None else repository
    recorded, saved_counts = _saved_execution(repository)
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "inventory_only": True,
        "execution_performed": False, "proof_verified": False, "production_admitted": False,
        "repository_root": str(repository), "workspace_root": str(workspace),
        "recorded_execution": recorded, "trust_policy": _trust_policy(repository),
        "source_bindings": [], "limitations": [
            "PATH discovery does not establish working runtime, family support, or proof.",
            "Catalog and certificate declarations do not establish current execution or verification.",
            "Saved records are hash-bound historical evidence and are not replayed or promoted.",
            "No version probes, Python solver imports, network calls, model loads, or tensor reads occur."]}
    # Lazy canonical declaration imports: no solver adapters or optional runtimes.
    try:
        module = importlib.import_module("ipfs_datasets_py.logic.families.canonical_catalog")
        snapshot = module.DEFAULT_CANONICAL_CATALOG_SNAPSHOT
        family_registry = importlib.import_module("ipfs_datasets_py.logic.families.registry")
        backend_registry = importlib.import_module("ipfs_datasets_py.logic.backends.registry")
        imported = Path(module.__file__).resolve()
        result["canonical_catalog"] = {"status": "declared", "interface": snapshot.interface,
            "content_digest": snapshot.content_digest, "versions": dict(snapshot.versions),
            "baseline_family_ids": sorted(family_registry.BASELINE_FAMILY_IDS),
            "executable_matrix_provider_ids": list(backend_registry.EXECUTABLE_PROVIDER_IDS),
            "import_matches_repository": imported == repository / "ipfs_datasets_py/logic/families/canonical_catalog.py",
            "families": [{"family_id": family, "publication_stage": snapshot.publication_stage(family).value,
                          "current_execution_verified": False} for family in snapshot.family_ids],
            "profiles": [entry.to_dict() for entry in snapshot.profiles],
            "notations": list(snapshot.notations), "encodings": list(snapshot.encodings)}
        providers = []
        for provider in snapshot.provider_ids:
            cells = snapshot.matrix.cells_for_provider(provider)
            descriptor = snapshot.providers.get(provider)
            commands = _COMMANDS.get(provider, ())
            discovered = [{"command": command, "discoverable_on_path": shutil.which(command) is not None}
                          for command in commands]
            providers.append({"provider_id": provider, "declaration": [cell.to_dict() for cell in cells],
                "runtime_declaration": list(descriptor.runtime_ids),
                "advisory": descriptor.advisory,
                "declared_authority_ceiling": descriptor.authority_ceiling.value,
                "binary_discovery": {"method": "PATH_lookup_only", "commands": discovered,
                    "status": "discovered" if any(row["discoverable_on_path"] for row in discovered) else
                    "not_found_on_path" if commands else "not_applicable_or_unprobed",
                    "version_probed": False, "runtime_verified": False},
                "recorded_execution": saved_counts.get(provider, {"reported_cases": 0, "saved_receipts_present": 0}),
                "certificate_support": {"declared_evidence_kinds": sorted(set(descriptor.evidence_ids) | {cell.evidence_kind for cell in cells}),
                                        "current_certificate_verified": False},
                "proof_verified": False, "current_proof_authority": "none"})
        result["providers"] = providers
        for name in ("canonical_catalog", "registry", "registry_v3", "profiles", "profile_catalog_v3",
                     "providers", "provider_matrix_v2", "generated_catalog", "translations", "namespaces", "models", "aliases"):
            declaration_module = importlib.import_module("ipfs_datasets_py.logic.families." + name)
            result["source_bindings"].append(_binding(Path(declaration_module.__file__).resolve()))
        backend_module = importlib.import_module("ipfs_datasets_py.logic.backends.registry")
        result["source_bindings"].append(_binding(Path(backend_module.__file__).resolve()))
    except (ImportError, ValueError, AttributeError) as error:
        result["canonical_catalog"] = {"status": "unavailable", "reason": type(error).__name__}
        result["providers"] = []
    runner = _runner_description(workspace / "scripts/run_leanstral_ephemeral.py")
    leanstral: dict[str, Any] = {"runner": runner, "runtime_verified": False,
        "embedding_runtime_verified": False, "retrieval_quality_verified": False,
        "chat_template": _binding(workspace / "papers/revisions/autoformalization_empirical_20260914/assistance/leanstral_v15.jinja"),
        "model_metadata": {"status": "unavailable", "reason": "runner_model_path_unavailable"},
        "operational_dependencies": ["pin tokenizer and chat template; verify apply-template before generation",
            "embedding and generation share the GPU lock and require separate admitted residency",
            "reserve prompt plus output tokens within measured context allocation",
            "qualify last pooling first; mean pooling requires one complete physical microbatch"]}
    if runner.get("status") == "source_inspected":
        model = Path(runner["default_model_path"])
        leanstral["model_metadata"] = _gguf_metadata(model)
        binding, manifest = _json_record(Path(str(model) + ".json"))
        leanstral["cache_manifest"] = {"source": binding, "full_model_hash_verified": False}
        if manifest is not None:
            digest = manifest.get("content_sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                leanstral["cache_manifest"]["declared_model_sha256"] = digest
            filename = manifest.get("filename")
            leanstral["cache_manifest"]["filename_matches"] = filename == model.name
        if runner.get("cache_root"):
            backend = Path(runner["cache_root"]) / "source/llama.cpp"
            architecture = leanstral["model_metadata"].get("architecture")
            names = ["tools/server/README.md", "tools/server/server-context.cpp", "src/llama-model.cpp", "src/llama-graph.cpp"]
            if architecture:
                names.append("src/models/" + architecture + ".cpp")
            leanstral["backend_sources"] = [_binding(backend / name) for name in names]
            head = backend / ".git/HEAD"
            leanstral["backend_revision_source"] = _binding(head)
            try:
                value = _read_regular(head, 4096).decode().strip()
                if value.startswith("ref: refs/"):
                    ref = value.removeprefix("ref: ")
                    if ".." in Path(ref).parts:
                        raise ValueError("invalid_git_ref")
                    value = _read_regular(backend / ".git" / ref, 4096).decode().strip()
                if re.fullmatch(r"[0-9a-f]{40}", value):
                    leanstral["backend_revision"] = value
            except (OSError, ValueError, UnicodeError):
                pass
    result["leanstral"] = leanstral
    return result
