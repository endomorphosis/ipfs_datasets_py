"""Logic CLI.

Minimal CLI surface for the `ipfs_datasets_py.logic` feature.

Design constraints:
- Keep module import light (import feature code inside handlers)
- Prefer stable wrapper functions where available
- Preserve existing command names and behavior (LFV-G071 additive)
"""

from __future__ import annotations

import argparse
import inspect
import json
from typing import Any, Dict, List, Optional

import anyio

LOGIC_VERIFICATION_CLI_INTERFACE = "LogicVerificationCLI@1"


def _print(data: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def _load_json_arg(raw: Optional[str], label: str) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets logic",
        description=(
            "Logic tools (FOL + deontic + temporal-deontic helpers + "
            "software-verification facade)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    # ── Legacy / domain helpers (preserve names and behavior) ─────────────
    p_fol = sub.add_parser("convert-fol", help="Convert text to FOL")
    p_fol.add_argument("text", help="Input text")

    p_deontic = sub.add_parser("convert-deontic", help="Convert legal text to deontic form")
    p_deontic.add_argument("text", help="Input legal text")

    p_norm = sub.add_parser("analyze-normative", help="Analyze a normative sentence")
    p_norm.add_argument("sentence", help="Sentence to analyze")
    p_norm.add_argument("--document-type", default="legal")

    p_add = sub.add_parser("add-theorem", help="Add a temporal-deontic theorem")
    p_add.add_argument("--operator", required=True, choices=["OBLIGATION", "PERMISSION", "PROHIBITION"])
    p_add.add_argument("--proposition", required=True)
    p_add.add_argument("--agent-name", default="Unspecified Party")
    p_add.add_argument("--jurisdiction", default="Federal")
    p_add.add_argument("--legal-domain", default="general")
    p_add.add_argument("--source-case", default="CLI")
    p_add.add_argument("--precedent-strength", type=float, default=0.8)
    p_add.add_argument("--start-date", default=None)
    p_add.add_argument("--end-date", default=None)

    p_query = sub.add_parser("query-theorems", help="Query temporal-deontic theorems")
    p_query.add_argument("query", help="Query string")
    p_query.add_argument("--operator-filter", default="all")
    p_query.add_argument("--jurisdiction", default="all")
    p_query.add_argument("--legal-domain", default="all")
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--min-relevance", type=float, default=0.5)

    p_check_doc = sub.add_parser("check-document", help="Check a document for consistency")
    p_check_doc.add_argument("document_text", help="Document text")
    p_check_doc.add_argument("--document-id", default=None)
    p_check_doc.add_argument("--jurisdiction", default="Federal")
    p_check_doc.add_argument("--legal-domain", default="general")
    p_check_doc.add_argument("--temporal-context", default="current_time")

    # ── Software verification (LogicVerificationCLI@1) ────────────────────
    p_list_features = sub.add_parser(
        "list-features",
        help="List stable verification operations (LogicVerificationCLI@1)",
    )
    p_list_features.add_argument("--request-id", default="")

    p_list_families = sub.add_parser(
        "list-families",
        help="List declarative logic families",
    )
    p_list_families.add_argument("--request-id", default="")

    p_list_providers = sub.add_parser(
        "list-providers",
        help="List declared verification providers (no environment probes)",
    )
    p_list_providers.add_argument("--request-id", default="")

    p_caps = sub.add_parser(
        "provider-capabilities",
        help="Show capability declarations for one or all providers",
    )
    p_caps.add_argument("--provider-id", default=None)
    p_caps.add_argument("--request-id", default="")

    p_compile = sub.add_parser(
        "compile",
        help="Compile a verification artifact (JSON obligation)",
    )
    p_compile.add_argument(
        "--artifact",
        required=True,
        help="JSON mapping for the obligation / artifact",
    )
    p_compile.add_argument("--target", default="smtlib2")
    p_compile.add_argument("--request-id", default="")

    p_check = sub.add_parser(
        "check",
        help="Run a typed verification check (JSON request)",
    )
    p_check.add_argument(
        "--request",
        required=True,
        help="JSON BackendRequest-shaped mapping",
    )
    p_check.add_argument("--backend-id", default=None)
    p_check.add_argument("--request-id", default="")

    p_monitor = sub.add_parser(
        "monitor",
        help="Evaluate a runtime MTL formula over observations",
    )
    p_monitor.add_argument("--formula", required=True, help="JSON formula mapping")
    p_monitor.add_argument(
        "--observations",
        required=True,
        help="JSON trace / observations mapping",
    )
    p_monitor.add_argument("--request-id", default="")

    p_portfolio = sub.add_parser(
        "portfolio",
        help="Plan a property-specific prover portfolio",
    )
    p_portfolio.add_argument("--obligation", required=True, help="JSON obligation mapping")
    p_portfolio.add_argument("--capabilities", default=None, help="Optional JSON capabilities")
    p_portfolio.add_argument("--resource-policy", default=None, help="Optional JSON policy")
    p_portfolio.add_argument("--request-id", default="")

    p_cex = sub.add_parser(
        "counterexample",
        help="Explain a counterexample witness",
    )
    p_cex.add_argument("--witness", required=True, help="JSON witness mapping")
    p_cex.add_argument("--request-id", default="")

    p_receipt = sub.add_parser(
        "verify-receipt",
        help="Validate a translation or proof receipt",
    )
    p_receipt.add_argument("--receipt", required=True, help="JSON receipt mapping")
    p_receipt.add_argument("--expectation", default=None, help="Optional JSON expectation")
    p_receipt.add_argument("--request-id", default="")

    p_advise = sub.add_parser(
        "advise",
        help="Produce untrusted formalization proposals",
    )
    p_advise.add_argument("--request", required=True, help="JSON advisor request")
    p_advise.add_argument("--provider", default="static")
    p_advise.add_argument("--request-id", default="")

    p_attest = sub.add_parser(
        "attest-receipt",
        help="Prepare or record a ZKP attestation for a receipt",
    )
    p_attest.add_argument("--receipt", required=True, help="JSON receipt mapping")
    p_attest.add_argument("--backend-mode", default="disabled")
    p_attest.add_argument("--backend-policy", default=None)
    p_attest.add_argument("--witness", default=None)
    p_attest.add_argument("--issued-at", default="")
    p_attest.add_argument("--expires-at", default="")
    p_attest.add_argument("--request-id", default="")

    p_probe = sub.add_parser(
        "probe-provider",
        help="Opt-in probe of provider availability",
    )
    p_probe.add_argument("provider_id")
    p_probe.add_argument("--request-id", default="")

    p_install = sub.add_parser(
        "install-provider",
        help="Opt-in install of a provider (requires --allow-install)",
    )
    p_install.add_argument("provider_id")
    p_install.add_argument(
        "--allow-install",
        action="store_true",
        help="Explicit opt-in for install side effects",
    )
    p_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Return the reviewed install plan without importing a plugin",
    )
    p_install.add_argument(
        "--offline",
        action="store_true",
        help="Enforce the no-command/no-network offline boundary",
    )
    p_install.add_argument("--force", action="store_true")
    p_install.add_argument("--request-id", default="")

    p_v_caps = sub.add_parser(
        "verification-capabilities",
        help="List CLI/MCP verification tool surface and bounds",
    )
    p_v_caps.add_argument("--request-id", default="")

    return parser


async def _run_verification_command(ns: argparse.Namespace) -> Dict[str, Any]:
    """Dispatch software-verification CLI commands via the MCP tool layer."""

    from ipfs_datasets_py.mcp_server.tools import logic_verification as lv

    cmd = ns.command

    if cmd == "list-features":
        return await lv.verification_list_features()
    if cmd == "list-families":
        return await lv.verification_list_logic_families()
    if cmd == "list-providers":
        return await lv.verification_list_providers()
    if cmd == "provider-capabilities":
        return await lv.verification_provider_capabilities(provider_id=ns.provider_id)
    if cmd == "compile":
        return await lv.verification_compile(
            artifact=_load_json_arg(ns.artifact, "artifact"),
            target=ns.target,
            request_id=ns.request_id or "",
        )
    if cmd == "check":
        return await lv.verification_check(
            request=_load_json_arg(ns.request, "request"),
            backend_id=ns.backend_id,
            request_id=ns.request_id or "",
        )
    if cmd == "monitor":
        return await lv.verification_monitor(
            formula=_load_json_arg(ns.formula, "formula"),
            observations=_load_json_arg(ns.observations, "observations"),
            request_id=ns.request_id or "",
        )
    if cmd == "portfolio":
        return await lv.verification_portfolio(
            obligation=_load_json_arg(ns.obligation, "obligation"),
            capabilities=_load_json_arg(ns.capabilities, "capabilities"),
            resource_policy=_load_json_arg(ns.resource_policy, "resource_policy"),
            request_id=ns.request_id or "",
        )
    if cmd == "counterexample":
        return await lv.verification_explain_counterexample(
            witness=_load_json_arg(ns.witness, "witness"),
            request_id=ns.request_id or "",
        )
    if cmd == "verify-receipt":
        return await lv.verification_verify_receipt(
            receipt=_load_json_arg(ns.receipt, "receipt"),
            expectation=_load_json_arg(ns.expectation, "expectation"),
            request_id=ns.request_id or "",
        )
    if cmd == "advise":
        return await lv.verification_advise(
            request=_load_json_arg(ns.request, "request"),
            provider=ns.provider,
            request_id=ns.request_id or "",
        )
    if cmd == "attest-receipt":
        return await lv.verification_attest_receipt(
            receipt=_load_json_arg(ns.receipt, "receipt"),
            backend_mode=ns.backend_mode,
            backend_policy=_load_json_arg(ns.backend_policy, "backend_policy"),
            witness=_load_json_arg(ns.witness, "witness"),
            issued_at=ns.issued_at or "",
            expires_at=ns.expires_at or "",
            request_id=ns.request_id or "",
        )
    if cmd == "probe-provider":
        return await lv.verification_probe_provider(
            provider_id=ns.provider_id,
            request_id=ns.request_id or "",
        )
    if cmd == "install-provider":
        # A local CLI invocation is itself the operator boundary.  Keep it
        # separate from the MCP wrapper's additional server-policy gate while
        # still offloading potentially long native builds from the event loop.
        from ipfs_datasets_py.logic.verification_api import get_verification_api

        response = await anyio.to_thread.run_sync(
            lambda: get_verification_api().install_provider(
                ns.provider_id,
                allow_install=bool(ns.allow_install),
                dry_run=bool(ns.dry_run),
                offline=bool(ns.offline),
                force=bool(ns.force),
                request_id=ns.request_id or "",
            ),
            abandon_on_cancel=False,
        )
        return response.to_dict()
    if cmd == "verification-capabilities":
        payload = await lv.verification_capabilities()
        payload["cli_interface"] = LOGIC_VERIFICATION_CLI_INTERFACE
        return payload

    raise ValueError(f"Unknown verification command: {cmd}")


async def _run_async(ns: argparse.Namespace) -> Dict[str, Any]:
    cmd = ns.command

    if cmd == "convert-fol":
        from ipfs_datasets_py.logic.api import convert_text_to_fol

        result = convert_text_to_fol(ns.text)
        if inspect.isawaitable(result):
            result = await result
        return result

    if cmd == "convert-deontic":
        from ipfs_datasets_py.logic.api import convert_legal_text_to_deontic

        result = convert_legal_text_to_deontic(ns.text)
        if inspect.isawaitable(result):
            result = await result
        return result

    if cmd == "analyze-normative":
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import analyze_normative_sentence

        return {
            "sentence": ns.sentence,
            "document_type": ns.document_type,
            "analysis": analyze_normative_sentence(ns.sentence, ns.document_type),
        }

    if cmd == "add-theorem":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import add_theorem_from_parameters

        params: Dict[str, Any] = {
            "operator": ns.operator,
            "proposition": ns.proposition,
            "agent_name": ns.agent_name,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "source_case": ns.source_case,
            "precedent_strength": ns.precedent_strength,
        }
        if ns.start_date:
            params["start_date"] = ns.start_date
        if ns.end_date:
            params["end_date"] = ns.end_date
        return await add_theorem_from_parameters(params)

    if cmd == "query-theorems":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import query_theorems_from_parameters

        params = {
            "query": ns.query,
            "operator_filter": ns.operator_filter,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "limit": ns.limit,
            "min_relevance": ns.min_relevance,
        }
        return await query_theorems_from_parameters(params)

    if cmd == "check-document":
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters,
        )

        params = {
            "document_text": ns.document_text,
            "document_id": ns.document_id,
            "jurisdiction": ns.jurisdiction,
            "legal_domain": ns.legal_domain,
            "temporal_context": ns.temporal_context,
        }
        return await check_document_consistency_from_parameters(params)

    # Software-verification commands (LFV-G071).
    verification_commands = {
        "list-features",
        "list-families",
        "list-providers",
        "provider-capabilities",
        "compile",
        "check",
        "monitor",
        "portfolio",
        "counterexample",
        "verify-receipt",
        "advise",
        "attest-receipt",
        "probe-provider",
        "install-provider",
        "verification-capabilities",
    }
    if cmd in verification_commands:
        return await _run_verification_command(ns)

    raise ValueError(f"Unknown command: {cmd}")


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)
    try:
        data = anyio.run(_run_async, ns)
        # Verification commands are always machine-readable JSON when --json
        # is set; without it, still prefer structured dumps for verification.
        force_json = bool(ns.json) or ns.command in {
            "list-features",
            "list-families",
            "list-providers",
            "provider-capabilities",
            "compile",
            "check",
            "monitor",
            "portfolio",
            "counterexample",
            "verify-receipt",
            "advise",
            "attest-receipt",
            "probe-provider",
            "install-provider",
            "verification-capabilities",
        }
        _print(data, json_output=force_json)
        if ns.command == "install-provider" and isinstance(data, dict):
            install_status = str(data.get("status") or "error").strip().lower()
            if install_status == "partial":
                return 3
            if install_status not in {"succeeded", "declarative"}:
                return 2
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({"success": False, "error": str(e)}, json_output=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
