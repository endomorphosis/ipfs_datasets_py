#!/usr/bin/env python3
"""Daemon-free LegalIR compiler CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_compiler_api import (  # noqa: E402
    LegalIRCompilerExitCode,
    LegalIRCompilerOptions,
    benchmark_legal_ir,
    compile_legal_ir,
    decompile_legal_ir,
    diff_legal_ir,
    explain_legal_ir,
    export_legal_ir_artifact,
    validate_legal_ir,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile, decompile, validate, diff, explain, benchmark, and export LegalIR artifacts as JSON.",
    )
    parser.add_argument(
        "operation",
        choices=(
            "compile",
            "decompile",
            "validate",
            "diff",
            "explain",
            "benchmark",
            "export-artifact",
            "export_artifact",
        ),
        nargs="?",
        default="compile",
        help="Compiler operation to run.",
    )
    parser.add_argument("--input", "-i", help="Input JSON/text file. Reads stdin when omitted or '-'.")
    parser.add_argument("--before", help="Before JSON/text file for diff.")
    parser.add_argument("--after", help="After JSON/text file for diff.")
    parser.add_argument("--output", "-o", help="Output JSON file. Writes stdout when omitted.")
    parser.add_argument("--iterations", type=int, default=3, help="Benchmark iterations.")
    parser.add_argument("--max-workers", type=int, default=1, help="Maximum deterministic compiler workers.")
    parser.add_argument("--learned-guidance", action="store_true", help="Explicitly activate learned guidance.")
    parser.add_argument("--learned-guidance-artifact", help="JSON file with learned-guidance activation evidence.")
    parser.add_argument("--lsp", action="store_true", help="Include LSP diagnostics in JSON output.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Return diagnostic exit code for warnings.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        options = LegalIRCompilerOptions(
            learned_guidance=bool(args.learned_guidance),
            learned_guidance_artifact=_read_optional_json(args.learned_guidance_artifact),
            include_lsp_diagnostics=bool(args.lsp),
            fail_on_warnings=bool(args.fail_on_warnings),
            max_workers=max(1, int(args.max_workers or 1)),
            resource_limits={"cpu": max(1, int(args.max_workers or 1))},
        )
        operation = args.operation.replace("-", "_")
        if operation == "diff":
            before = _read_input(args.before, parser=parser, label="--before")
            after = _read_input(args.after, parser=parser, label="--after")
            result = diff_legal_ir(before, after, options=options)
        else:
            source = _read_input(args.input, parser=parser, label="--input")
            if operation == "compile":
                result = compile_legal_ir(source, options=options)
            elif operation == "decompile":
                result = decompile_legal_ir(source, options=options)
            elif operation == "validate":
                result = validate_legal_ir(source, options=options)
            elif operation == "explain":
                result = explain_legal_ir(source, options=options)
            elif operation == "benchmark":
                result = benchmark_legal_ir(source, iterations=args.iterations, options=options)
            elif operation == "export_artifact":
                result = export_legal_ir_artifact(source, options=options)
            else:
                parser.error(f"Unsupported operation: {args.operation}")
        _write_output(args.output, result.to_dict(), pretty=not args.compact)
        return int(result.exit_code)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI must normalize process failures
        error_payload = {
            "error": str(exc),
            "exit_code": LegalIRCompilerExitCode.USAGE_ERROR.value,
            "schema_version": "legal-ir-compiler-cli-error-v1",
            "successful": False,
        }
        _write_output(args.output, error_payload, pretty=not args.compact)
        return LegalIRCompilerExitCode.USAGE_ERROR.value


def _read_input(path_text: str | None, *, parser: argparse.ArgumentParser, label: str) -> Any:
    if not path_text or path_text == "-":
        if label != "--input":
            parser.error(f"{label} is required for diff.")
        text = sys.stdin.read()
        return _parse_text(text)
    path = Path(path_text)
    if not path.exists():
        parser.error(f"{label} path does not exist: {path}")
    return _parse_text(path.read_text(encoding="utf-8"))


def _read_optional_json(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    payload = _parse_text(Path(path_text).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"value": payload}


def _parse_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    return text


def _write_output(path_text: str | None, payload: Any, *, pretty: bool) -> None:
    text = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    )
    if path_text:
        Path(path_text).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
