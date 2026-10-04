"""Bounded TypeScript/JavaScript Compiler API frontend.

``TypeScriptFrontend`` communicates with the pinned Node worker over one-shot
JSONL.  The worker builds a TypeScript ``SourceFile`` and a no-resolution
``TypeChecker``/``Symbol`` view, but emits only lexical parsing facts into the
shared language-neutral AST records.  It never evaluates analyzed JavaScript,
loads analyzed modules, installs packages, or accesses the network.

Compiler absence, version mismatch, malformed input, protocol failure and
resource exhaustion all produce explicit unsupported AST evidence.  Regex
fallbacks are intentionally absent.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, Mapping

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTIRValidationError,
    ASTRecord,
    CallRecord,
    DiagnosticRecord,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
    UnsupportedConstruct,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)


TYPESCRIPT_FRONTEND_VERSION: Final[str] = "1.0.0"
TYPESCRIPT_COMPILER_VERSION: Final[str] = "5.6.3"
PINNED_NODE_VERSION: Final[str] = "v18.19.1"
PINNED_NODE_IDENTITY: Final[str] = (
    "sha256:2b0f6efd95c31c5538cc0a9042d5d13b7328cffcfdcc409f2e2ef336c4402086"
)
PINNED_TYPESCRIPT_IDENTITY: Final[str] = (
    "sha256:7372ce6f9939dbc90ebcbd3874dfdecae9440dc503ecf2cf61510ccea54da4f4"
)
TYPESCRIPT_WORKER_PROTOCOL: Final[str] = (
    "ipfs-datasets.software-contracts.typescript-worker@1"
)
TYPESCRIPT_SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".cjs",
    ".js",
    ".jsx",
    ".mjs",
    ".mts",
    ".ts",
    ".tsx",
)
DEFAULT_MAX_SOURCE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_AST_NODES: Final[int] = 5_000_000
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
MAX_TIMEOUT_SECONDS: Final[float] = 900.0
DEFAULT_MAX_OUTPUT_BYTES: Final[int] = 64 * 1024 * 1024


class TypeScriptFrontendError(RuntimeError):
    """A bounded worker or protocol failure."""


@dataclass(frozen=True, slots=True)
class TypeScriptCapability:
    """Result of probing the exact pinned compiler capability."""

    supported: bool
    compiler_version: str
    node_version: str
    reason: str = ""


def _default_worker_path() -> Path:
    # package/ipfs_datasets_py/logic/software_contracts -> package root
    package_root = Path(__file__).resolve().parents[3]
    return package_root / "scripts" / "software_contracts" / "typescript_ast_worker.mjs"


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.as_posix()
    for suffix in TYPESCRIPT_SOURCE_EXTENSIONS:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("/", ".").replace(" ", "_") or "__main__"


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive exact integer")
    return value


class TypeScriptASTWorker:
    """One-shot bounded JSONL client for ``typescript_ast_worker.mjs``."""

    def __init__(
        self,
        *,
        worker_path: str | Path | None = None,
        node_binary: str = "node",
        typescript_module: str = "typescript",
        expected_compiler_version: str = TYPESCRIPT_COMPILER_VERSION,
        expected_node_version: str = PINNED_NODE_VERSION,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self.worker_path = Path(worker_path or _default_worker_path()).resolve()
        if type(node_binary) is not str or not node_binary.strip():
            raise ValueError("node_binary must be a non-empty exact string")
        if type(typescript_module) is not str or not typescript_module.strip():
            raise ValueError("typescript_module must be a non-empty exact string")
        if (
            type(expected_compiler_version) is not str
            or not expected_compiler_version.strip()
        ):
            raise ValueError(
                "expected_compiler_version must be a non-empty exact string"
            )
        if type(expected_node_version) is not str or not expected_node_version.strip():
            raise ValueError("expected_node_version must be a non-empty exact string")
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds cannot exceed {MAX_TIMEOUT_SECONDS:g}"
            )
        self.node_binary = node_binary
        self.typescript_module = typescript_module
        self.expected_compiler_version = expected_compiler_version
        self.expected_node_version = expected_node_version
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = _positive_int(max_output_bytes, "max_output_bytes")
        if self.max_output_bytes > DEFAULT_MAX_OUTPUT_BYTES:
            raise ValueError(
                f"max_output_bytes cannot exceed {DEFAULT_MAX_OUTPUT_BYTES}"
            )

    def _command(self) -> list[str]:
        return [
            self.node_binary,
            str(self.worker_path),
            "--typescript-module",
            self.typescript_module,
            "--expected-version",
            self.expected_compiler_version,
        ]

    def _invoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self.worker_path.is_file():
            raise TypeScriptFrontendError(
                f"TypeScript worker is absent: {self.worker_path}"
            )
        encoded = (
            json.dumps(
                dict(request),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
        }
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.worker_path.parent),
                env=environment,
                start_new_session=True,
            )
        except OSError as exc:
            raise TypeScriptFrontendError(
                f"unable to start TypeScript worker: {exc}"
            ) from exc
        try:
            stdout, stderr = process.communicate(
                encoded,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise TypeScriptFrontendError(
                f"TypeScript worker exceeded {self.timeout_seconds:g}s"
            ) from exc
        if len(stdout) > self.max_output_bytes:
            raise TypeScriptFrontendError(
                f"TypeScript worker output exceeded {self.max_output_bytes} bytes"
            )
        if len(stderr) > self.max_output_bytes:
            raise TypeScriptFrontendError(
                f"TypeScript worker stderr exceeded {self.max_output_bytes} bytes"
            )
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace").strip()
            raise TypeScriptFrontendError(
                f"TypeScript worker exited {process.returncode}: "
                f"{error[:2048] or 'no diagnostic'}"
            )
        lines = stdout.splitlines()
        if len(lines) != 1:
            raise TypeScriptFrontendError(
                "TypeScript worker must return exactly one JSONL record"
            )

        def reject_constant(value: str) -> None:
            raise TypeScriptFrontendError(
                f"TypeScript worker returned non-canonical number {value}"
            )

        def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise TypeScriptFrontendError(
                        f"TypeScript worker returned duplicate key {key!r}"
                    )
                result[key] = value
            return result

        try:
            response = json.loads(
                lines[0].decode("utf-8"),
                parse_float=reject_constant,
                parse_constant=reject_constant,
                object_pairs_hook=reject_duplicate,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TypeScriptFrontendError(
                "TypeScript worker returned invalid JSON"
            ) from exc
        if type(response) is not dict:
            raise TypeScriptFrontendError(
                "TypeScript worker response must be an exact object"
            )
        if response.get("protocol") != TYPESCRIPT_WORKER_PROTOCOL:
            raise TypeScriptFrontendError("TypeScript worker protocol mismatch")
        if response.get("request_id") != request.get("request_id"):
            raise TypeScriptFrontendError("TypeScript worker request ID mismatch")
        return response

    def probe(self) -> TypeScriptCapability:
        try:
            response = self._invoke(
                {
                    "protocol": TYPESCRIPT_WORKER_PROTOCOL,
                    "request_id": "probe",
                    "operation": "probe",
                }
            )
        except TypeScriptFrontendError as exc:
            return TypeScriptCapability(False, "", "", str(exc))
        supported = response.get("status") == "ok"
        compiler_version = response.get("compiler_version", "")
        node_version = response.get("node_version", "")
        reason = response.get("reason", "")
        if not all(
            type(value) is str
            for value in (compiler_version, node_version, reason)
        ):
            return TypeScriptCapability(
                False,
                "",
                "",
                "worker capability fields are not exact strings",
            )
        if supported and compiler_version != self.expected_compiler_version:
            return TypeScriptCapability(
                False,
                compiler_version,
                node_version,
                (
                    f"compiler version {compiler_version} does not match "
                    f"{self.expected_compiler_version}"
                ),
            )
        if supported and node_version != self.expected_node_version:
            return TypeScriptCapability(
                False,
                compiler_version,
                node_version,
                (
                    f"Node version {node_version} does not match "
                    f"{self.expected_node_version}"
                ),
            )
        return TypeScriptCapability(
            supported,
            compiler_version,
            node_version,
            reason,
        )

    def parse(
        self,
        source: str,
        *,
        path: str,
        max_source_bytes: int,
        max_ast_nodes: int,
    ) -> dict[str, Any]:
        return self._invoke(
            {
                "protocol": TYPESCRIPT_WORKER_PROTOCOL,
                "request_id": "parse",
                "operation": "parse",
                "path": path,
                "source": source,
                "max_source_bytes": _positive_int(
                    max_source_bytes, "max_source_bytes"
                ),
                "max_ast_nodes": _positive_int(max_ast_nodes, "max_ast_nodes"),
            }
        )


class TypeScriptFrontend:
    """Map compiler-backed JS-family parsing facts into the shared AST IR."""

    def __init__(
        self,
        *,
        worker: TypeScriptASTWorker | None = None,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        max_ast_nodes: int = DEFAULT_MAX_AST_NODES,
    ) -> None:
        self.worker = worker or TypeScriptASTWorker()
        self.max_source_bytes = _positive_int(
            max_source_bytes, "max_source_bytes"
        )
        self.max_ast_nodes = _positive_int(max_ast_nodes, "max_ast_nodes")
        if self.max_source_bytes > DEFAULT_MAX_SOURCE_BYTES:
            raise ValueError(
                f"max_source_bytes cannot exceed {DEFAULT_MAX_SOURCE_BYTES}"
            )
        if self.max_ast_nodes > DEFAULT_MAX_AST_NODES:
            raise ValueError(
                f"max_ast_nodes cannot exceed {DEFAULT_MAX_AST_NODES}"
            )

    @property
    def capability(self) -> FrontendCapability:
        try:
            worker_source = self.worker.worker_path.read_bytes()
        except OSError:
            worker_source = b""
        toolchain = {
            "frontend": "typescript-compiler-api",
            "frontend_version": TYPESCRIPT_FRONTEND_VERSION,
            "compiler": f"typescript@{self.worker.expected_compiler_version}",
            "compiler_identity": PINNED_TYPESCRIPT_IDENTITY,
            "node": self.worker.expected_node_version,
            "node_identity": PINNED_NODE_IDENTITY,
            "worker_source_cid": cid_for_bytes(worker_source),
            "worker_protocol": TYPESCRIPT_WORKER_PROTOCOL,
            "execution": False,
            "regex_fallback": False,
        }
        return FrontendCapability(
            frontend_name="typescript-compiler-api",
            frontend_version=TYPESCRIPT_FRONTEND_VERSION,
            language="typescript",
            language_version=self.worker.expected_compiler_version,
            capabilities=(
                "annotations",
                "awaits",
                "calls",
                "compiler_api",
                "diagnostics",
                "effects",
                "exports",
                "imports",
                "jsx",
                "modules",
                "references",
                "scopes",
                "signatures",
                "state_access",
                "symbols",
                "tsx",
                "unsupported_constructs",
            ),
            source_extensions=TYPESCRIPT_SOURCE_EXTENSIONS,
            toolchain_cid=cid_for_structured(toolchain),
        )

    def probe(self) -> TypeScriptCapability:
        return self.worker.probe()

    def extract(
        self,
        source: str | bytes,
        *,
        path: str = "source.ts",
        repository_id: str = "repository:unknown",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        module_name: str | None = None,
    ) -> ASTRecord:
        if type(source) is str:
            try:
                source_bytes = source.encode("utf-8")
            except UnicodeEncodeError as exc:
                return self._unsupported_record(
                    b"",
                    "",
                    path=path,
                    repository_id=repository_id,
                    revision=revision,
                    repository_tree_cid=repository_tree_cid,
                    module_name=module_name,
                    code="typescript.invalid_encoding",
                    construct="source_encoding",
                    reason=f"Source is not strict UTF-8: {exc.reason}.",
                )
            source_text = source
        elif type(source) is bytes:
            source_bytes = source
            try:
                source_text = source.decode("utf-8")
            except UnicodeDecodeError as exc:
                return self._unsupported_record(
                    source_bytes,
                    "",
                    path=path,
                    repository_id=repository_id,
                    revision=revision,
                    repository_tree_cid=repository_tree_cid,
                    module_name=module_name,
                    code="typescript.invalid_encoding",
                    construct="source_encoding",
                    reason=f"Source is not strict UTF-8 at byte {exc.start}.",
                )
        else:
            raise TypeError("source must be an exact str or bytes value")

        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in TYPESCRIPT_SOURCE_EXTENSIONS:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.unsupported_extension",
                construct="source_extension",
                reason=f"Source extension {suffix or '<none>'} is unsupported.",
            )
        if len(source_bytes) > self.max_source_bytes:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.resource_limit",
                construct="source_size",
                reason=(
                    f"Source has {len(source_bytes)} bytes; limit is "
                    f"{self.max_source_bytes}."
                ),
            )
        try:
            response = self.worker.parse(
                source_text,
                path=path,
                max_source_bytes=self.max_source_bytes,
                max_ast_nodes=self.max_ast_nodes,
            )
        except TypeScriptFrontendError as exc:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.compiler_unavailable",
                construct="compiler_capability",
                reason=str(exc),
            )
        if response.get("status") != "ok":
            reason = response.get("reason")
            if type(reason) is not str or not reason:
                reason = "TypeScript compiler worker reported unsupported input."
            code = response.get("code")
            if type(code) is not str or not code:
                code = "typescript.unsupported"
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code=code,
                construct="compiler_parse",
                reason=reason,
            )
        if response.get("compiler_version") != self.worker.expected_compiler_version:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.compiler_version_mismatch",
                construct="compiler_capability",
                reason=(
                    f"Compiler {response.get('compiler_version')!r} does not "
                    f"match {self.worker.expected_compiler_version}."
                ),
            )
        if response.get("node_version") != self.worker.expected_node_version:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.node_version_mismatch",
                construct="compiler_capability",
                reason=(
                    f"Node {response.get('node_version')!r} does not match "
                    f"{self.worker.expected_node_version}."
                ),
            )
        facts = response.get("facts")
        fact_fields = {
            "module",
            "scopes",
            "symbols",
            "imports",
            "references",
            "calls",
            "effects",
            "diagnostics",
            "unsupported",
        }
        if type(facts) is not dict or set(facts) != fact_fields:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.invalid_worker_response",
                construct="worker_protocol",
                reason="Compiler worker omitted the exact facts mapping.",
            )
        provenance = SourceProvenance(
            source_cid=cid_for_bytes(source_bytes),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        try:
            record = ASTRecord(
                provenance=provenance,
                frontend=self.capability,
                module=ModuleDefinition.from_dict(facts["module"]),
                scopes=[
                    ScopeDefinition.from_dict(item) for item in facts["scopes"]
                ],
                symbols=[
                    SymbolDefinition.from_dict(item) for item in facts["symbols"]
                ],
                imports=[
                    ImportDefinition.from_dict(item) for item in facts["imports"]
                ],
                references=[
                    ReferenceRecord.from_dict(item)
                    for item in facts["references"]
                ],
                calls=[CallRecord.from_dict(item) for item in facts["calls"]],
                effects=[
                    EffectRecord.from_dict(item) for item in facts["effects"]
                ],
                diagnostics=[
                    DiagnosticRecord.from_dict(item)
                    for item in facts["diagnostics"]
                ],
                unsupported=[
                    UnsupportedConstruct.from_dict(item)
                    for item in facts["unsupported"]
                ],
            )
        except (KeyError, TypeError, ValueError, ASTIRValidationError) as exc:
            return self._unsupported_record(
                source_bytes,
                source_text,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                module_name=module_name,
                code="typescript.invalid_worker_response",
                construct="worker_protocol",
                reason=f"Compiler facts failed shared-schema validation: {exc}.",
            )
        expected_name = module_name or _module_name(path)
        if record.module.name != expected_name:
            # A caller override belongs to provenance projection, not to the
            # worker's syntax facts.
            if module_name is not None:
                record = ASTRecord(
                    provenance=record.provenance,
                    frontend=record.frontend,
                    module=ModuleDefinition(
                        module_id=record.module.module_id,
                        name=module_name,
                        scope_id=record.module.scope_id,
                        span=record.module.span,
                        export_names=record.module.export_names,
                    ),
                    scopes=record.scopes,
                    symbols=record.symbols,
                    imports=record.imports,
                    references=record.references,
                    calls=record.calls,
                    effects=record.effects,
                    diagnostics=record.diagnostics,
                    unsupported=record.unsupported,
                )
            else:
                return self._unsupported_record(
                    source_bytes,
                    source_text,
                    path=path,
                    repository_id=repository_id,
                    revision=revision,
                    repository_tree_cid=repository_tree_cid,
                    module_name=module_name,
                    code="typescript.invalid_worker_response",
                    construct="worker_protocol",
                    reason="Compiler worker returned a mismatched module name.",
                )
        return record

    def parse(self, source: str | bytes, **kwargs: Any) -> ASTRecord:
        return self.extract(source, **kwargs)

    def _unsupported_record(
        self,
        source_bytes: bytes,
        source_text: str,
        *,
        path: str,
        repository_id: str,
        revision: str,
        repository_tree_cid: str | None,
        module_name: str | None,
        code: str,
        construct: str,
        reason: str,
    ) -> ASTRecord:
        lines = source_text.splitlines(keepends=True) or [""]
        if lines[-1].endswith("\n"):
            end_line = len(lines) + 1
            end_column = 0
        else:
            end_line = len(lines)
            end_column = len(lines[-1].encode("utf-8"))
        whole = SourceSpan(
            start_byte=0,
            end_byte=len(source_text.encode("utf-8")),
            start_line=1,
            start_column=0,
            end_line=end_line,
            end_column=end_column,
        )
        provenance = SourceProvenance(
            source_cid=cid_for_bytes(source_bytes),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        return ASTRecord(
            provenance=provenance,
            frontend=self.capability,
            module=ModuleDefinition(
                module_id=f"module:{provenance.source_cid}",
                name=module_name or _module_name(path),
                scope_id="scope:module",
                span=whole,
            ),
            scopes=(
                ScopeDefinition(
                    scope_id="scope:module",
                    kind="module",
                    span=whole,
                ),
            ),
            diagnostics=(
                DiagnosticRecord(
                    code=code,
                    severity="error",
                    message=reason,
                    span=whole,
                ),
            ),
            unsupported=(
                UnsupportedConstruct(
                    unsupported_id="unsupported:frontend:0",
                    code=code,
                    construct=construct,
                    reason=reason,
                    span=whole,
                ),
            ),
        )


# Compatibility nouns used by the goal AST query.  They point to the shared
# records and the worker's Compiler API surfaces; they do not create a
# TypeScript-owned durable schema separate from ast_ir.
SourceFile = ASTRecord
Symbol = SymbolDefinition
# The worker builds a no-resolution TypeChecker/Symbol view via the pinned
# Compiler API.  The Python adapter never reimplements type checking.
TypeChecker = TypeScriptASTWorker


__all__ = [
    "DEFAULT_MAX_AST_NODES",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_MAX_SOURCE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "PINNED_NODE_IDENTITY",
    "PINNED_NODE_VERSION",
    "PINNED_TYPESCRIPT_IDENTITY",
    "SourceFile",
    "Symbol",
    "TypeChecker",
    "TYPESCRIPT_COMPILER_VERSION",
    "TYPESCRIPT_FRONTEND_VERSION",
    "TYPESCRIPT_SOURCE_EXTENSIONS",
    "TYPESCRIPT_WORKER_PROTOCOL",
    "TypeScriptASTWorker",
    "TypeScriptCapability",
    "TypeScriptFrontend",
    "TypeScriptFrontendError",
]
