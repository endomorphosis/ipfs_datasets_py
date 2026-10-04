"""Compiler-backed TypeScript/JavaScript frontend tests for DSCON-G120."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.logic.software_contracts.typescript_frontend import (
    PINNED_NODE_VERSION,
    TYPESCRIPT_COMPILER_VERSION,
    TYPESCRIPT_SOURCE_EXTENSIONS,
    TYPESCRIPT_WORKER_PROTOCOL,
    TypeChecker,
    TypeScriptASTWorker,
    TypeScriptFrontend,
)


REPRESENTATIVE_SOURCE = """\
import client, { helper as runHelper } from "./client.js";
export { shared } from "./shared.js";

export interface Runner {
  run(value: number): Promise<string>;
}

export class Service implements Runner {
  async run(value: number): Promise<string> {
    await client.fetch(value);
    throw new Error("stop");
  }
}

export const view = <section>{runHelper()}</section>;
"""


def _worker_script(tmp_path: Path, *, mode: str = "ok") -> Path:
    """Hermetic JSONL worker used when the reviewed compiler is not provisioned.

    Node and compiler versions are fixed to the pinned values so capability
    probes never depend on the host Node release under test.
    """

    worker = tmp_path / "fake-typescript-worker.mjs"
    worker.write_text(
        f"""\
import process from "node:process";
const protocol = {TYPESCRIPT_WORKER_PROTOCOL!r};
const pinnedNode = {PINNED_NODE_VERSION!r};
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const mode = {mode!r};
if (mode === "timeout") {{
  await new Promise((resolve) => setTimeout(resolve, 2000));
}}
if (mode === "malformed") {{
  process.stdout.write("not-json\\n");
  process.exit(0);
}}
if (request.operation === "probe") {{
  process.stdout.write(JSON.stringify({{
    protocol,
    request_id: request.request_id,
    status: mode === "unsupported" ? "unsupported" : "ok",
    code: mode === "unsupported" ? "typescript.compiler_unavailable" : "",
    compiler_version: mode === "wrong-version" ? "5.5.0" : "5.6.3",
    node_version: mode === "wrong-node" ? "v16.0.0" : pinnedNode,
    reason: mode === "unsupported" ? "compiler missing" : "",
  }}) + "\\n");
  process.exit(0);
}}
if (mode === "extra-line") {{
  process.stdout.write("{{}}\\n{{}}\\n");
  process.exit(0);
}}
const end = Buffer.byteLength(request.source, "utf8");
const lines = request.source.split(/\\n/u);
const extension = request.path.match(/(\\.tsx?|\\.jsx?|\\.mjs|\\.cjs|\\.mts)$/u)?.[1] || "";
const moduleName = request.path.slice(0, -extension.length).replaceAll("/", ".");
const whole = {{
  start_byte: 0, end_byte: end, start_line: 1, start_column: 0,
  end_line: lines.length, end_column: Buffer.byteLength(lines.at(-1), "utf8"),
}};
const point = {{...whole, end_byte: Math.min(end, 1), end_line: 1, end_column: Math.min(end, 1)}};
const facts = {{
  module: {{
    module_id: "module:fixture",
    name: moduleName,
    scope_id: "scope:module",
    span: whole,
    export_names: ["Runner", "Service", "view"],
  }},
  scopes: [
    {{scope_id: "scope:module", kind: "module", span: whole, parent_scope_id: null, owner_symbol_id: null}},
    {{scope_id: "scope:interface", kind: "interface", span: point, parent_scope_id: "scope:module", owner_symbol_id: "symbol:runner"}},
    {{scope_id: "scope:class", kind: "class", span: point, parent_scope_id: "scope:module", owner_symbol_id: "symbol:service"}},
    {{scope_id: "scope:function", kind: "function", span: point, parent_scope_id: "scope:class", owner_symbol_id: "symbol:run"}},
  ],
  symbols: [
    {{symbol_id: "symbol:runner", name: "Runner", qualified_name: moduleName + ".Runner", kind: "interface", scope_id: "scope:module", span: point, definition_ordinal: 0, signature: null, visibility: "public", decorator_names: [], flags: ["export"]}},
    {{symbol_id: "symbol:service", name: "Service", qualified_name: moduleName + ".Service", kind: "class", scope_id: "scope:module", span: point, definition_ordinal: 0, signature: null, visibility: "public", decorator_names: [], flags: ["export"]}},
    {{symbol_id: "symbol:run", name: "run", qualified_name: moduleName + ".Service.run", kind: "method", scope_id: "scope:class", span: point, definition_ordinal: 0, signature: {{parameters: [{{name: "value", kind: "positional_or_named", position: 0, annotation: "number", default_kind: "none"}}], return_annotation: "Promise<string>", is_async: true, is_generator: false}}, visibility: "public", decorator_names: [], flags: ["coroutine"]}},
  ],
  imports: [
    {{import_id: "import:client", scope_id: "scope:module", module: "./client.js", kind: "symbol", span: point, imported_name: "default", local_name: "client", is_type_only: false}},
    {{import_id: "import:shared", scope_id: "scope:module", module: "./shared.js", kind: "re_export", span: point, imported_name: "shared", local_name: "shared", is_type_only: false}},
  ],
  references: [
    {{reference_id: "reference:fetch", name: "client.fetch", scope_id: "scope:function", context: "call", span: point, is_qualified: true}},
  ],
  calls: [
    {{call_id: "call:fetch", scope_id: "scope:function", callee_name: "client.fetch", kind: "method", argument_count: 1, span: point, callee_reference_id: "reference:fetch", named_argument_names: [], is_awaited: true}},
  ],
  effects: [
    {{effect_id: "effect:await", scope_id: "scope:function", kind: "await", operation: "await", span: point, subject: "client.fetch"}},
    {{effect_id: "effect:throw", scope_id: "scope:function", kind: "exception", operation: "raise", span: point, subject: "Error"}},
  ],
  diagnostics: [],
  unsupported: [],
}};
process.stdout.write(JSON.stringify({{
  protocol,
  request_id: request.request_id,
  status: "ok",
  code: "",
  compiler_version: mode === "wrong-version" ? "5.5.0" : "5.6.3",
  node_version: mode === "wrong-node" ? "v16.0.0" : pinnedNode,
  reason: "",
  facts,
  usage: {{source_bytes: end, ast_nodes: 20, facts: 15}},
}}) + "\\n");
""",
        encoding="utf-8",
    )
    return worker


def _frontend(tmp_path: Path, *, mode: str = "ok", timeout: float = 5) -> TypeScriptFrontend:
    return TypeScriptFrontend(
        worker=TypeScriptASTWorker(
            worker_path=_worker_script(tmp_path, mode=mode),
            timeout_seconds=timeout,
        )
    )


def _provisioned_typescript_module() -> str | None:
    """Return a path/module name for the pinned compiler when present."""

    override = os.environ.get("IPFS_DATASETS_TYPESCRIPT_MODULE", "").strip()
    if override:
        return override
    try:
        completed = subprocess.run(
            [
                "node",
                "-e",
                (
                    "const {createRequire}=require('module');"
                    "const require=createRequire(process.cwd()+'/package.json');"
                    "const ts=require('typescript');"
                    "if(ts.version!=='5.6.3') process.exit(2);"
                    "process.stdout.write(require.resolve('typescript'));"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return completed.stdout.strip()


def test_transport_maps_compiler_facts_to_shared_ast(tmp_path: Path) -> None:
    frontend = _frontend(tmp_path)
    probe = frontend.probe()
    assert probe.supported is True
    assert probe.compiler_version == TYPESCRIPT_COMPILER_VERSION

    record = frontend.extract(
        REPRESENTATIVE_SOURCE,
        path="src/service.tsx",
        repository_id="repository:swissknife",
        revision="df11f08f",
    )
    assert isinstance(record, ASTRecord)
    assert record.frontend.frontend_name == "typescript-compiler-api"
    assert record.frontend.language == "typescript"
    assert record.frontend.language_version == "5.6.3"
    assert record.frontend.source_extensions == TYPESCRIPT_SOURCE_EXTENSIONS
    assert record.module.name == "src.service"
    assert record.module.export_names == ("Runner", "Service", "view")
    assert {(item.name, item.kind) for item in record.symbols} >= {
        ("Runner", "interface"),
        ("Service", "class"),
        ("run", "method"),
    }
    run = next(item for item in record.symbols if item.name == "run")
    assert run.signature is not None
    assert run.signature.is_async
    assert run.signature.return_annotation == "Promise<string>"
    assert record.imports[1].kind == "re_export"
    assert record.calls[0].callee_name == "client.fetch"
    assert record.calls[0].is_awaited
    assert {item.kind for item in record.effects} == {"await", "exception"}
    assert not record.unsupported
    for item in (*record.references, *record.calls):
        assert {
            "resolved_symbol_id",
            "target_symbol_id",
            "candidate_symbol_ids",
            "resolution_confidence",
        }.isdisjoint(item.to_dict())


@pytest.mark.parametrize("extension", TYPESCRIPT_SOURCE_EXTENSIONS)
def test_all_objective_extensions_use_one_versioned_contract(
    tmp_path: Path,
    extension: str,
) -> None:
    record = _frontend(tmp_path).extract(
        "",
        path=f"src/empty{extension}",
        repository_id="repository:test",
        revision="revision",
    )
    assert not record.unsupported
    assert record.module.name == "src.empty"
    assert record.frontend.source_extensions == TYPESCRIPT_SOURCE_EXTENSIONS


def test_real_worker_is_valid_jsonl_and_missing_compiler_is_explicit() -> None:
    worker = TypeScriptASTWorker()
    completed = subprocess.run(
        ["node", "--check", str(worker.worker_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    capability = worker.probe()
    # This checkout deliberately does not auto-install packages.  If CI
    # provisions the reviewed 5.6.3 module, the same assertion proves the pin.
    if capability.supported:
        assert capability.compiler_version == TYPESCRIPT_COMPILER_VERSION
    else:
        assert capability.reason
        record = TypeScriptFrontend(worker=worker).extract(
            "export const value = 1;",
            path="src/value.ts",
        )
        assert {item.code for item in record.unsupported} == {
            "typescript.compiler_unavailable"
        }
        assert {item.code for item in record.diagnostics} == {
            "typescript.compiler_unavailable"
        }


def test_wrong_version_is_rejected_without_using_facts(tmp_path: Path) -> None:
    frontend = _frontend(tmp_path, mode="wrong-version")
    assert not frontend.probe().supported
    record = frontend.extract("export const x = 1;", path="src/x.ts")
    assert [item.code for item in record.unsupported] == [
        "typescript.compiler_version_mismatch"
    ]
    assert not record.symbols


def test_wrong_node_version_is_rejected_without_using_facts(tmp_path: Path) -> None:
    frontend = _frontend(tmp_path, mode="wrong-node")
    assert not frontend.probe().supported
    record = frontend.extract("export const x = 1;", path="src/x.ts")
    assert [item.code for item in record.unsupported] == [
        "typescript.node_version_mismatch"
    ]
    assert not record.symbols


@pytest.mark.parametrize("mode", ["malformed", "extra-line"])
def test_malformed_worker_protocol_fails_closed(
    tmp_path: Path,
    mode: str,
) -> None:
    record = _frontend(tmp_path, mode=mode).extract(
        "export const x = 1;",
        path="src/x.ts",
    )
    assert [item.code for item in record.unsupported] == [
        "typescript.compiler_unavailable"
    ]
    assert not record.symbols


def test_worker_timeout_is_bounded_and_explicit(tmp_path: Path) -> None:
    record = _frontend(tmp_path, mode="timeout", timeout=0.05).extract(
        "export const x = 1;",
        path="src/x.ts",
    )
    assert [item.code for item in record.unsupported] == [
        "typescript.compiler_unavailable"
    ]
    assert "exceeded" in record.unsupported[0].reason


def test_source_limits_encoding_and_extension_fail_before_worker(
    tmp_path: Path,
) -> None:
    frontend = TypeScriptFrontend(
        worker=TypeScriptASTWorker(
            worker_path=tmp_path / "absent-worker.mjs",
        ),
        max_source_bytes=4,
    )
    oversized = frontend.extract("12345", path="value.ts")
    assert [item.code for item in oversized.unsupported] == [
        "typescript.resource_limit"
    ]
    extension = frontend.extract("", path="value.cts")
    assert [item.code for item in extension.unsupported] == [
        "typescript.unsupported_extension"
    ]
    invalid = frontend.extract(b"\xff", path="value.ts")
    assert [item.code for item in invalid.unsupported] == [
        "typescript.invalid_encoding"
    ]


def test_adapter_round_trip_and_golden_root(tmp_path: Path) -> None:
    record = _frontend(tmp_path).extract(
        REPRESENTATIVE_SOURCE,
        path="src/service.tsx",
        repository_id="repository:swissknife",
        revision="df11f08f",
    )
    assert ASTRecord.from_json(record.to_json()) == record
    assert record.verify_cid(record.cid) == record.cid
    assert (
        record.cid
        == "baguqeeramrqecwub6elecohidj37shzsc3gqe3jq57pcagnlqds7vwjsgmxa"
    )


def test_capability_records_pinned_compiler_api_without_regex_fallback(
    tmp_path: Path,
) -> None:
    frontend = _frontend(tmp_path)
    capability = frontend.capability
    assert capability.frontend_name == "typescript-compiler-api"
    assert "compiler_api" in capability.capabilities
    assert "jsx" in capability.capabilities
    assert "tsx" in capability.capabilities
    assert "regex_fallback" not in capability.capabilities
    assert capability.source_extensions == TYPESCRIPT_SOURCE_EXTENSIONS


def test_worker_bounds_and_protocol_surface(tmp_path: Path) -> None:
    worker_path = _worker_script(tmp_path, mode="ok")
    # Direct protocol contract: exactly one JSONL record and closed keys.
    worker = TypeScriptASTWorker(worker_path=worker_path)
    response = worker.parse(
        "export const x = 1;",
        path="src/x.ts",
        max_source_bytes=1024,
        max_ast_nodes=1000,
    )
    assert response["status"] == "ok"
    assert response["protocol"] == TYPESCRIPT_WORKER_PROTOCOL
    with pytest.raises(ValueError):
        TypeScriptASTWorker(worker_path=worker_path, timeout_seconds=0)
    with pytest.raises(ValueError):
        TypeScriptFrontend(worker=worker, max_source_bytes=0)
    with pytest.raises(ValueError):
        TypeScriptASTWorker(worker_path=worker_path, max_output_bytes=0)


def test_no_execution_when_reviewed_compiler_is_available(tmp_path: Path) -> None:
    module = _provisioned_typescript_module()
    if module is None:
        frontend = TypeScriptFrontend()
        capability = frontend.probe()
        if not capability.supported:
            pytest.skip("reviewed TypeScript 5.6.3 compiler is not provisioned")
        worker = TypeScriptASTWorker()
    else:
        worker = TypeScriptASTWorker(typescript_module=module)
        if not worker.probe().supported:
            pytest.skip("reviewed TypeScript 5.6.3 compiler is not provisioned")
    frontend = TypeScriptFrontend(worker=worker)
    marker = tmp_path / "executed"
    record = frontend.extract(
        (
            "import 'hostile-side-effect';\n"
            f"require('node:fs').writeFileSync({json.dumps(str(marker))}, 'x');\n"
            "process.exit(99);\n"
        ),
        path="src/hostile.js",
    )
    assert not marker.exists()
    assert record.imports
    assert not record.unsupported or all(
        item.code != "typescript.compiler_unavailable" for item in record.unsupported
    )


def test_real_compiler_covers_swissknife_surface_without_regex(
    tmp_path: Path,
) -> None:
    module = _provisioned_typescript_module()
    if module is None:
        pytest.skip("reviewed TypeScript 5.6.3 compiler is not provisioned")
    worker = TypeScriptASTWorker(typescript_module=module)
    capability = worker.probe()
    if not capability.supported:
        pytest.skip(capability.reason or "pinned compiler/node not available")
    frontend = TypeScriptFrontend(worker=worker)
    record = frontend.extract(
        REPRESENTATIVE_SOURCE,
        path="src/service.tsx",
        repository_id="repository:swissknife",
        revision="df11f08f",
    )
    assert not record.unsupported
    assert {"Runner", "Service", "view", "shared"} <= set(record.module.export_names)
    kinds = {item.kind for item in record.symbols}
    assert {"interface", "class", "method", "variable"} <= kinds
    assert any(item.kind == "re_export" for item in record.imports)
    assert any(item.callee_name == "client.fetch" and item.is_awaited for item in record.calls)
    assert {item.kind for item in record.effects} >= {"await", "exception", "import"}
    # References and calls stay unresolved in the frontend (resolver owns joins).
    for item in (*record.references, *record.calls):
        assert {
            "resolved_symbol_id",
            "target_symbol_id",
            "candidate_symbol_ids",
            "resolution_confidence",
        }.isdisjoint(item.to_dict())
    assert ASTRecord.from_json(record.to_json()) == record
    assert record.verify_cid(record.cid) == record.cid
