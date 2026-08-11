"""Fail-closed CLI for allowlisted DuckLake query and export APIs (DQK-093).

Exposes only typed, parameterized commands:

* ``discover-catalogs`` — sanitized catalog discovery
* ``discover-datasets`` — dataset / table discovery
* ``select-snapshot`` — snapshot / time-travel selection
* ``list-templates`` — enumerate allowlisted templates
* ``explain`` — plan summary without raw SQL
* ``query`` — bounded aggregate / projection query
* ``page`` — continue a paginated result handle
* ``status`` — inspect a query/export handle
* ``cancel`` — cancel a handle-bound execution
* ``export`` — deterministic snapshot-bound export

Every command is an allowlisted parameterized template. Catalog-management
paths use DQK-104; query/export paths use snapshot-bound workers or the
sanitized publication plane. Secrets, tokens, raw catalog strings, and
unrestricted SQL never appear on the public surface.

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit command runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Final, Mapping, Sequence, TextIO

from ipfs_datasets_py.ducklake import api as lake_api

__all__ = [
    "CLI_SCHEMA",
    "CLI_IMPLEMENTATION_GENERATION",
    "COMMANDS",
    "MAX_JSON_OUTPUT_BYTES",
    "MAX_TEXT_OUTPUT_BYTES",
    "MAX_TEXT_LINE_BYTES",
    "CliError",
    "CommandResult",
    "build_parser",
    "format_output",
    "main",
    "run",
    "run_command",
]


CLI_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-query-cli@1"
CLI_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-093-ducklake-query-export-cli-20260810"
)

COMMANDS: Final[tuple[str, ...]] = (
    "discover-catalogs",
    "discover-datasets",
    "select-snapshot",
    "list-templates",
    "explain",
    "query",
    "page",
    "status",
    "cancel",
    "export",
)

MAX_JSON_OUTPUT_BYTES: Final[int] = 262_144
MAX_TEXT_OUTPUT_BYTES: Final[int] = 16_384
MAX_TEXT_LINE_BYTES: Final[int] = 512
_TRUNCATE_MARKER: Final[str] = "…[truncated]"
_OUTPUT_FORMATS: Final[frozenset[str]] = frozenset({"json", "text"})


class CliError(ValueError):
    """Fail-closed CLI rejection (bad args, policy, or API error)."""


class CommandResult:
    """Structured CLI result envelope."""

    __slots__ = (
        "command",
        "ok",
        "status",
        "data",
        "error",
        "exit_code",
        "reason_code",
    )

    def __init__(
        self,
        command: str,
        *,
        ok: bool,
        status: str,
        data: Mapping[str, Any] | None = None,
        error: str | None = None,
        exit_code: int = 0,
        reason_code: str | None = None,
    ) -> None:
        self.command = command
        self.ok = ok
        self.status = status
        self.data = dict(data or {})
        self.error = error
        self.exit_code = exit_code
        self.reason_code = reason_code

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": CLI_SCHEMA,
            "command": self.command,
            "ok": self.ok,
            "status": self.status,
            "data": lake_api.redact_public_payload(self.data),
            "implementation_generation": CLI_IMPLEMENTATION_GENERATION,
        }
        if self.error:
            body["error"] = lake_api.sanitize_public_error(
                self.error, reason_code=self.reason_code
            )["error"]
        if self.reason_code:
            body["reason_code"] = self.reason_code
        return body


def _clip_utf8(text: str, *, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = _TRUNCATE_MARKER.encode("utf-8")
    if limit <= len(marker):
        return _TRUNCATE_MARKER[:limit]
    budget = limit - len(marker)
    clipped = raw[:budget]
    while clipped and (clipped[-1] & 0xC0) == 0x80:
        clipped = clipped[:-1]
    if clipped and (clipped[-1] & 0xC0) == 0xC0:
        clipped = clipped[:-1]
    return clipped.decode("utf-8", errors="ignore") + _TRUNCATE_MARKER


def _parse_params(raw: str | None) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return {}
    text = str(raw).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid --params JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CliError("--params must be a JSON object")
    # Reject SQL smuggling via parameter keys at the CLI boundary.
    for key in payload:
        if str(key).lower() in {"sql", "query", "raw_sql", "attach", "statement"}:
            raise CliError("arbitrary SQL parameter keys are forbidden")
    return dict(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ducklake-query",
        description=(
            "Allowlisted DuckLake catalog discovery, snapshot selection, "
            "bounded query, cancellation, and deterministic export (DQK-093). "
            "Never accepts unrestricted SQL or returns catalog credentials."
        ),
    )
    parser.add_argument(
        "--format",
        choices=sorted(_OUTPUT_FORMATS),
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--trust",
        choices=("untrusted", "trusted"),
        default="untrusted",
        dest="trust",
        help="Caller trust class (default: untrusted)",
    )
    # Parent-level flags must appear before the subcommand. Subcommands also
    # accept --tenant-id / --trust so operators can place them after the verb.
    parser.add_argument(
        "--tenant-id",
        default=None,
        dest="tenant_id_global",
        help="Tenant isolation key (also accepted on subcommands)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--tenant-id",
            default=None,
            dest="tenant_id_local",
            help="Tenant isolation key",
        )
        p.add_argument(
            "--trust",
            choices=("untrusted", "trusted"),
            default=None,
            dest="trust_local",
            help="Caller trust class (overrides parent)",
        )

    p_dc = sub.add_parser("discover-catalogs", help="Discover sanitized catalogs")
    _add_common(p_dc)
    p_dc.add_argument("--max-rows", type=int, default=None)

    p_dd = sub.add_parser("discover-datasets", help="Discover sanitized datasets")
    _add_common(p_dd)
    p_dd.add_argument("--catalog-id", required=False, default=None)
    p_dd.add_argument("--namespace", default="main")
    p_dd.add_argument("--schema-name", default="main")
    p_dd.add_argument("--max-rows", type=int, default=None)

    p_ss = sub.add_parser("select-snapshot", help="Select snapshot / time-travel")
    _add_common(p_ss)
    p_ss.add_argument("--catalog-id", required=True)
    p_ss.add_argument("--snapshot-version", type=int, required=True)
    p_ss.add_argument(
        "--time-travel",
        action="store_true",
        help="Require snapshot to be within retention window",
    )
    p_ss.add_argument("--logical-query-id", default=None)

    p_lt = sub.add_parser("list-templates", help="List allowlisted templates")
    _add_common(p_lt)
    p_lt.add_argument(
        "--include-catalog-templates",
        action="store_true",
        help="Include DQK-104 catalog-management templates (trusted only)",
    )

    for name, help_text in (
        ("explain", "Explain an allowlisted template without raw SQL"),
        ("query", "Run a bounded allowlisted query"),
        ("export", "Deterministic snapshot-bound export"),
    ):
        p = sub.add_parser(name, help=help_text)
        _add_common(p)
        p.add_argument("--template-id", required=True)
        p.add_argument(
            "--params",
            default=None,
            help="JSON object of template parameters",
        )
        p.add_argument("--snapshot-id", required=True)
        p.add_argument("--catalog-id", default=None)
        if name == "query":
            p.add_argument("--page-size", type=int, default=None)
        if name == "export":
            p.add_argument(
                "--export-format",
                default="json",
                help="Export format (json, markdown, parquet, ...)",
            )
            p.add_argument(
                "--location-hint",
                default="exports/ducklake/",
                help="Non-authority destination hint",
            )

    p_page = sub.add_parser("page", help="Fetch next page for a handle")
    _add_common(p_page)
    p_page.add_argument("--handle-id", required=True)
    p_page.add_argument("--page-token", default=None)

    p_status = sub.add_parser("status", help="Status of a query/export handle")
    _add_common(p_status)
    p_status.add_argument("--handle-id", required=True)

    p_cancel = sub.add_parser("cancel", help="Cancel a query handle")
    _add_common(p_cancel)
    p_cancel.add_argument("--handle-id", required=True)
    p_cancel.add_argument("--reason", default="cancelled")

    return parser


def run_command(
    args: argparse.Namespace,
    *,
    api: lake_api.DuckLakeQueryAPI | None = None,
) -> CommandResult:
    """Dispatch one CLI command through the DuckLake API."""

    gateway = api or lake_api.get_default_api()
    command = str(args.command)
    # Subcommand --trust/--tenant-id override parent-level flags when present.
    trust = (
        getattr(args, "trust_local", None)
        or getattr(args, "trust", None)
        or "untrusted"
    )
    tenant_id = (
        getattr(args, "tenant_id_local", None)
        or getattr(args, "tenant_id_global", None)
        or getattr(args, "tenant_id", None)
    )

    try:
        if command == "discover-catalogs":
            result = gateway.discover_catalogs(
                tenant_id=tenant_id,
                trust=trust,
                max_rows=getattr(args, "max_rows", None),
            )
        elif command == "discover-datasets":
            result = gateway.discover_datasets(
                catalog_id=getattr(args, "catalog_id", None),
                tenant_id=tenant_id,
                namespace=getattr(args, "namespace", "main"),
                schema_name=getattr(args, "schema_name", "main"),
                trust=trust,
                max_rows=getattr(args, "max_rows", None),
            )
        elif command == "select-snapshot":
            result = gateway.select_snapshot(
                catalog_id=args.catalog_id,
                snapshot_version=args.snapshot_version,
                tenant_id=tenant_id,
                trust=trust,
                time_travel=bool(getattr(args, "time_travel", False)),
                logical_query_id=getattr(args, "logical_query_id", None),
            )
        elif command == "list-templates":
            result = gateway.list_templates(
                trust=trust,
                include_catalog_templates=bool(
                    getattr(args, "include_catalog_templates", False)
                ),
            )
        elif command == "explain":
            result = gateway.explain(
                args.template_id,
                _parse_params(getattr(args, "params", None)),
                snapshot_id=args.snapshot_id,
                tenant_id=tenant_id,
                trust=trust,
            )
        elif command == "query":
            result = gateway.query(
                args.template_id,
                _parse_params(getattr(args, "params", None)),
                snapshot_id=args.snapshot_id,
                tenant_id=tenant_id,
                trust=trust,
                page_size=getattr(args, "page_size", None),
                catalog_id=getattr(args, "catalog_id", None),
            )
        elif command == "export":
            result = gateway.export(
                args.template_id,
                _parse_params(getattr(args, "params", None)),
                snapshot_id=args.snapshot_id,
                tenant_id=tenant_id,
                trust=trust,
                format=getattr(args, "export_format", "json"),
                location_hint=getattr(args, "location_hint", "exports/ducklake/"),
                catalog_id=getattr(args, "catalog_id", None),
            )
        elif command == "page":
            result = gateway.page(
                args.handle_id,
                getattr(args, "page_token", None),
            )
        elif command == "status":
            result = gateway.status(args.handle_id)
        elif command == "cancel":
            result = gateway.cancel(
                args.handle_id,
                reason=getattr(args, "reason", "cancelled"),
            )
        else:
            raise CliError(f"unknown command {command!r}")
    except lake_api.DuckLakeAPIError as exc:
        public = lake_api.sanitize_public_error(exc)
        return CommandResult(
            command,
            ok=False,
            status="error",
            error=public["error"],
            reason_code=public["reason_code"],
            exit_code=2,
            data=public,
        )
    except CliError as exc:
        return CommandResult(
            command,
            ok=False,
            status="error",
            error=str(exc),
            reason_code="ducklake_cli.error",
            exit_code=2,
        )

    if result.get("status") == "error":
        return CommandResult(
            command,
            ok=False,
            status="error",
            error=str(result.get("error") or "request denied"),
            reason_code=result.get("reason_code"),
            exit_code=2,
            data=result,
        )

    return CommandResult(
        command,
        ok=True,
        status=str(result.get("status") or "ok"),
        data=result,
        exit_code=0,
    )


def format_output(
    result: CommandResult,
    *,
    fmt: str = "json",
) -> str:
    """Format a command result as bounded JSON or text."""

    fmt_norm = str(fmt or "json").strip().lower()
    if fmt_norm not in _OUTPUT_FORMATS:
        fmt_norm = "json"

    if fmt_norm == "json":
        payload = json.dumps(
            result.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return _clip_utf8(payload, limit=MAX_JSON_OUTPUT_BYTES)

    # Text mode: compact key lines, redacted.
    lines: list[str] = [
        f"command={result.command}",
        f"ok={result.ok}",
        f"status={result.status}",
    ]
    if result.reason_code:
        lines.append(f"reason_code={result.reason_code}")
    if result.error:
        lines.append(f"error={result.error}")
    data = result.data
    for key in (
        "operation",
        "template_id",
        "handle_id",
        "handle_status",
        "plane",
        "count",
        "row_count",
        "cancelled",
    ):
        if key in data:
            lines.append(f"{key}={data[key]}")
    if isinstance(data.get("export"), Mapping):
        export = data["export"]
        for key in ("content_digest", "parameters_digest", "root_cid", "row_count"):
            if key in export:
                lines.append(f"export.{key}={export[key]}")
    if isinstance(data.get("selection"), Mapping):
        sel = data["selection"]
        for key in ("catalog_id", "snapshot_version", "logical_result_digest"):
            if key in sel:
                lines.append(f"selection.{key}={sel[key]}")
    text = "\n".join(
        _clip_utf8(line, limit=MAX_TEXT_LINE_BYTES) for line in lines
    )
    return _clip_utf8(text, limit=MAX_TEXT_OUTPUT_BYTES)


def run(
    argv: Sequence[str] | None = None,
    *,
    api: lake_api.DuckLakeQueryAPI | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse argv, run one command, write output, return process exit code."""

    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 2
        return code

    # Hard deny any accidental SQL flags.
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    for token in raw_argv:
        upper = str(token).upper()
        if upper.startswith("--SQL") or upper in {"--ATTACH", "--QUERY"}:
            message = format_output(
                CommandResult(
                    getattr(args, "command", "unknown"),
                    ok=False,
                    status="error",
                    error="arbitrary SQL and denied surfaces are forbidden",
                    reason_code="query.sql_surface_denied",
                    exit_code=2,
                ),
                fmt=getattr(args, "format", "json"),
            )
            print(message, file=out)
            return 2

    result = run_command(args, api=api)
    text = format_output(result, fmt=getattr(args, "format", "json"))
    print(text, file=out if result.ok else out)
    if not result.ok and result.error:
        print(result.error, file=err)
    return int(result.exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
