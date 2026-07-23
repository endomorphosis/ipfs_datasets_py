#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CEC Logic CLI Commands

Provides command-line interface for CEC logic operations including parsing,
proving, and analysis with multi-language support.

Also exposes the governed ITP hammer operations (HAMMER-013, ``##
HAMMER-013`` in ``docs/logic/itp_hammer_taskboard.todo.md``) as
``hammer-*`` subcommands backed by
``ipfs_datasets_py.mcp_server.tools.logic_hammer``: ``hammer-inspect``,
``hammer-select-premises``, ``hammer-translate``, ``hammer-run-candidate``,
``hammer-reconstruct``, ``hammer-retrieve-receipt``, ``hammer-persist-receipt``,
and ``hammer-capability-status``. Every operation that launches a native ITP
or solver process (``hammer-inspect``, ``hammer-run-candidate``,
``hammer-reconstruct``) requires an explicit ``--confirm`` flag; without it
the command reports a structured ``confirmation_required`` result and does
not execute anything. See ``docs/logic/itp_hammer_mcp_contract.md`` for the
full request/response contract.
"""

import argparse
import asyncio
import sys
import json
from typing import Any, Coroutine, Dict, List, Optional, TypeVar


def format_output(result: Dict[str, Any], format_type: str = "text") -> str:
    """
    Format result for output.
    
    Args:
        result: Result dictionary from tool execution
        format_type: Output format (text/json/compact)
    
    Returns:
        Formatted string
    """
    if format_type == "json":
        return json.dumps(result, indent=2)
    elif format_type == "compact":
        return json.dumps(result)
    else:  # text
        lines = []
        if result.get('success'):
            lines.append("✅ Success")
        else:
            lines.append("❌ Failed")
        
        # Format based on result type
        if 'formula' in result:
            lines.append(f"Formula: {result['formula']}")
        if 'proved' in result:
            status = "Proved" if result['proved'] else "Not proved"
            lines.append(f"Status: {status}")
        if 'complexity' in result:
            lines.append(f"Complexity: {result['complexity']}")
        # HAMMER-013 governed hammer operations share a common envelope
        # (operation/correlation_id/status/data/error/capability/notes).
        if 'operation' in result and 'correlation_id' in result:
            lines.append(f"Operation: {result['operation']}")
            lines.append(f"Correlation id: {result['correlation_id']}")
            lines.append(f"Status: {result.get('status')}")
            if result.get('data') is not None:
                lines.append(f"Data: {json.dumps(result['data'], indent=2)}")
            if result.get('capability') is not None:
                lines.append(f"Capability: {json.dumps(result['capability'], indent=2)}")
            for note in result.get('notes') or []:
                lines.append(f"Note: {note}")
        if 'error' in result and result['error']:
            lines.append(f"Error: {result['error']}")
        
        return "\n".join(lines)


def parse_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute parse command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        
        result = parse_dcec(
            text=args.text,
            language=args.language,
            domain=args.domain if hasattr(args, 'domain') else None
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def prove_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute prove command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        
        axioms = args.axioms.split(',') if hasattr(args, 'axioms') and args.axioms else None
        
        result = prove_dcec(
            goal=args.goal,
            axioms=axioms,
            strategy=args.strategy if hasattr(args, 'strategy') else "auto",
            timeout=args.timeout if hasattr(args, 'timeout') else 30
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def analyze_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute analyze command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        
        result = analyze_formula(formula=args.formula)
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def profile_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute profile command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import profile_operation
        
        result = profile_operation(
            operation=args.operation,
            formula=args.formula,
            iterations=args.iterations if hasattr(args, 'iterations') else 1
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def translate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute translate command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import translate_dcec
        
        result = translate_dcec(
            formula=args.formula,
            target_format=args.format if hasattr(args, 'format') else "tptp"
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def validate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute validate command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import validate_formula
        
        result = validate_formula(formula=args.formula)
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


_T = TypeVar("_T")


def _run_async(coro: "Coroutine[Any, Any, _T]") -> _T:
    """Run a hammer async operation to completion for CLI use."""

    return asyncio.run(coro)


def _load_json_arg(
    *, inline: Optional[str], file_path: Optional[str], label: str
) -> Optional[Any]:
    """Load a JSON payload from either an inline ``--*-json`` string or a
    ``--*-file`` path. Returns ``None`` if neither was supplied."""

    if inline is not None and file_path is not None:
        raise ValueError(f"pass only one of an inline {label} or a {label} file, not both")
    if inline is not None:
        return json.loads(inline)
    if file_path is not None:
        with open(file_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return None


def _read_text_arg(*, inline: Optional[str], file_path: Optional[str], label: str) -> Optional[str]:
    if inline is not None and file_path is not None:
        raise ValueError(f"pass only one of an inline {label} or a {label} file, not both")
    if inline is not None:
        return inline
    if file_path is not None:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read()
    return None


def hammer_inspect_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``inspect`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_inspect

        native_source = _read_text_arg(
            inline=args.native_source, file_path=args.native_source_file, label="native-source"
        )
        if native_source is None:
            return {"success": False, "error": "one of --native-source or --native-source-file is required"}

        return _run_async(
            hammer_inspect(
                itp=args.itp,
                theorem_id=args.theorem_id,
                native_source=native_source,
                timeout=args.timeout,
                confirm_native_execution=args.confirm,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_select_premises_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``select-premises`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_select_premises

        corpus_manifest = _load_json_arg(
            inline=args.corpus_manifest_json,
            file_path=args.corpus_manifest_file,
            label="corpus-manifest",
        )
        policy = _load_json_arg(inline=args.policy_json, file_path=args.policy_file, label="policy")
        imports = args.imports.split(",") if args.imports else None

        return _run_async(
            hammer_select_premises(
                goal_statement=args.goal_statement,
                corpus_manifest=corpus_manifest,
                corpus_manifest_path=args.corpus_manifest_path,
                theorem_id=args.theorem_id,
                imports=imports,
                top_k=args.top_k,
                policy=policy,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_translate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``translate`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_translate

        term = _load_json_arg(inline=args.term_json, file_path=args.term_file, label="term")
        if term is None:
            return {"success": False, "error": "one of --term-json or --term-file is required"}
        monomorphization = _load_json_arg(
            inline=args.monomorphization_json,
            file_path=args.monomorphization_file,
            label="monomorphization",
        )

        return _run_async(
            hammer_translate(
                request_id=args.request_id,
                source_construct=args.source_construct,
                term=term,
                target=args.target,
                monomorphization=monomorphization,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_run_candidate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``run-candidate`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_run_candidate

        request = _load_json_arg(inline=args.request_json, file_path=args.request_file, label="request")
        attempts = _load_json_arg(
            inline=args.attempts_json, file_path=args.attempts_file, label="attempts"
        )
        if request is None:
            return {"success": False, "error": "one of --request-json or --request-file is required"}
        if attempts is None:
            return {"success": False, "error": "one of --attempts-json or --attempts-file is required"}
        portfolio_policy = _load_json_arg(
            inline=args.portfolio_policy_json,
            file_path=args.portfolio_policy_file,
            label="portfolio-policy",
        )
        translation_map = _load_json_arg(
            inline=args.translation_map_json,
            file_path=args.translation_map_file,
            label="translation-map",
        )
        premise_ids = args.premise_ids.split(",") if args.premise_ids else None

        return _run_async(
            hammer_run_candidate(
                request=request,
                attempts=attempts,
                portfolio_policy=portfolio_policy,
                premise_ids=premise_ids,
                translation_map=translation_map,
                confirm_native_execution=args.confirm,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_reconstruct_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``reconstruct`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_reconstruct

        request = _load_json_arg(inline=args.request_json, file_path=args.request_file, label="request")
        candidate = _load_json_arg(
            inline=args.candidate_json, file_path=args.candidate_file, label="candidate"
        )
        if request is None:
            return {"success": False, "error": "one of --request-json or --request-file is required"}
        if candidate is None:
            return {"success": False, "error": "one of --candidate-json or --candidate-file is required"}
        native_source = _read_text_arg(
            inline=args.native_source, file_path=args.native_source_file, label="native-source"
        )
        if native_source is None:
            return {"success": False, "error": "one of --native-source or --native-source-file is required"}
        environment_lock = _load_json_arg(
            inline=args.environment_lock_json,
            file_path=args.environment_lock_file,
            label="environment-lock",
        )

        return _run_async(
            hammer_reconstruct(
                request=request,
                candidate=candidate,
                itp=args.itp,
                theorem_id=args.theorem_id,
                native_source=native_source,
                environment_lock=environment_lock,
                timeout=args.timeout,
                confirm_native_execution=args.confirm,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_retrieve_receipt_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``retrieve-receipt`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_retrieve_receipt

        return _run_async(
            hammer_retrieve_receipt(
                receipt_id=args.receipt_id,
                publishable=args.publishable,
                store_root=args.store_root,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_persist_receipt_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the ``persist-receipt`` hammer utility operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_persist_receipt

        receipt = _load_json_arg(
            inline=args.receipt_json, file_path=args.receipt_file, label="receipt"
        )
        if receipt is None:
            return {"success": False, "error": "one of --receipt-json or --receipt-file is required"}

        return _run_async(
            hammer_persist_receipt(
                receipt=receipt,
                publish=args.publish,
                store_root=args.store_root,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def hammer_capability_status_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the governed hammer ``capability-status`` operation."""

    try:
        from ipfs_datasets_py.mcp_server.tools.logic_hammer import hammer_capability_status

        itps = args.itps.split(",") if args.itps else None
        solvers = args.solvers.split(",") if args.solvers else None

        return _run_async(
            hammer_capability_status(
                itps=itps,
                solvers=solvers,
                probe_versions=not args.no_probe_versions,
                correlation_id=args.correlation_id,
            )
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for logic commands."""
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets logic',
        description='CEC Logic Operations CLI'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Parse command
    parse_parser = subparsers.add_parser('parse', help='Parse natural language to DCEC formula')
    parse_parser.add_argument('text', help='Text to parse')
    parse_parser.add_argument('--language', '-l', default='en', 
                             help='Language code (en/es/fr/de/auto)')
    parse_parser.add_argument('--domain', '-d', 
                             help='Domain vocabulary (legal/medical/technical)')
    parse_parser.add_argument('--format', '-f', default='text',
                             choices=['text', 'json', 'compact'],
                             help='Output format')
    
    # Prove command
    prove_parser = subparsers.add_parser('prove', help='Prove a theorem')
    prove_parser.add_argument('goal', help='Goal formula to prove')
    prove_parser.add_argument('--axioms', '-a', help='Comma-separated axioms')
    prove_parser.add_argument('--strategy', '-s', default='auto',
                             choices=['auto', 'z3', 'vampire', 'e_prover'],
                             help='Prover strategy')
    prove_parser.add_argument('--timeout', '-t', type=int, default=30,
                             help='Timeout in seconds')
    prove_parser.add_argument('--format', '-f', default='text',
                             choices=['text', 'json', 'compact'],
                             help='Output format')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze formula complexity')
    analyze_parser.add_argument('formula', help='Formula to analyze')
    analyze_parser.add_argument('--format', '-f', default='text',
                               choices=['text', 'json', 'compact'],
                               help='Output format')
    
    # Profile command
    profile_parser = subparsers.add_parser('profile', help='Profile operation performance')
    profile_parser.add_argument('operation', choices=['parse', 'prove', 'analyze'],
                               help='Operation to profile')
    profile_parser.add_argument('formula', help='Formula to use')
    profile_parser.add_argument('--iterations', '-i', type=int, default=10,
                               help='Number of iterations')
    profile_parser.add_argument('--format', '-f', default='text',
                               choices=['text', 'json', 'compact'],
                               help='Output format')
    
    # Translate command
    translate_parser = subparsers.add_parser('translate', help='Translate formula to another format')
    translate_parser.add_argument('formula', help='Formula to translate')
    translate_parser.add_argument('--format', '-f', default='tptp',
                                 choices=['tptp', 'z3', 'json'],
                                 help='Target format')
    translate_parser.add_argument('--output-format', '-o', default='text',
                                 choices=['text', 'json', 'compact'],
                                 help='Output format')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate formula syntax')
    validate_parser.add_argument('formula', help='Formula to validate')
    validate_parser.add_argument('--format', '-f', default='text',
                                choices=['text', 'json', 'compact'],
                                help='Output format')

    # -- ITP hammer (HAMMER-013) governed operations -------------------------
    #
    # Each subcommand below is a thin wrapper over one function in
    # ipfs_datasets_py.mcp_server.tools.logic_hammer. Every ``hammer-*``
    # subcommand accepts a shared --correlation-id (auto-generated if
    # omitted) and --format for output rendering; hammer-inspect,
    # hammer-run-candidate, and hammer-reconstruct additionally require an
    # explicit --confirm flag before they will launch any native ITP/solver
    # process.

    hammer_inspect_parser = subparsers.add_parser(
        'hammer-inspect', help='Capture a native ITP goal snapshot (HAMMER-006)'
    )
    hammer_inspect_parser.add_argument('--itp', required=True, choices=['lean', 'coq', 'isabelle'])
    hammer_inspect_parser.add_argument('--theorem-id', required=True)
    hammer_inspect_parser.add_argument('--native-source', help='Inline native source text')
    hammer_inspect_parser.add_argument('--native-source-file', help='Path to a native source file')
    hammer_inspect_parser.add_argument('--timeout', type=float, default=None)
    hammer_inspect_parser.add_argument(
        '--confirm', action='store_true',
        help='Explicitly authorize launching the native ITP process',
    )
    hammer_inspect_parser.add_argument('--correlation-id', default=None)
    hammer_inspect_parser.add_argument('--format', '-f', default='json',
                                       choices=['text', 'json', 'compact'])

    hammer_select_premises_parser = subparsers.add_parser(
        'hammer-select-premises', help='Rank premises from a corpus manifest (HAMMER-004)'
    )
    hammer_select_premises_parser.add_argument('--goal-statement', required=True)
    hammer_select_premises_parser.add_argument('--corpus-manifest-json', help='Inline manifest JSON')
    hammer_select_premises_parser.add_argument('--corpus-manifest-file', help='Path to a manifest JSON file')
    hammer_select_premises_parser.add_argument(
        '--corpus-manifest-path', help='Path to a manifest previously written by CorpusManifest.save'
    )
    hammer_select_premises_parser.add_argument('--theorem-id', default=None)
    hammer_select_premises_parser.add_argument('--imports', help='Comma-separated imports')
    hammer_select_premises_parser.add_argument('--top-k', type=int, default=8)
    hammer_select_premises_parser.add_argument('--policy-json', help='Inline HammerPolicy JSON')
    hammer_select_premises_parser.add_argument('--policy-file', help='Path to a HammerPolicy JSON file')
    hammer_select_premises_parser.add_argument('--correlation-id', default=None)
    hammer_select_premises_parser.add_argument('--format', '-f', default='json',
                                               choices=['text', 'json', 'compact'])

    hammer_translate_parser = subparsers.add_parser(
        'hammer-translate', help='Lower a construct to TPTP/SMT-LIB (HAMMER-007)'
    )
    hammer_translate_parser.add_argument('--request-id', required=True)
    hammer_translate_parser.add_argument('--source-construct', required=True)
    hammer_translate_parser.add_argument('--term-json', help='Inline term AST JSON')
    hammer_translate_parser.add_argument('--term-file', help='Path to a term AST JSON file')
    hammer_translate_parser.add_argument('--target', required=True, choices=['tptp', 'smtlib'])
    hammer_translate_parser.add_argument('--monomorphization-json', default=None)
    hammer_translate_parser.add_argument('--monomorphization-file', default=None)
    hammer_translate_parser.add_argument('--correlation-id', default=None)
    hammer_translate_parser.add_argument('--format', '-f', default='json',
                                        choices=['text', 'json', 'compact'])

    hammer_run_candidate_parser = subparsers.add_parser(
        'hammer-run-candidate', help='Run a policy-controlled solver portfolio (HAMMER-008/009)'
    )
    hammer_run_candidate_parser.add_argument('--request-json', help='Inline HammerRequest JSON')
    hammer_run_candidate_parser.add_argument('--request-file', help='Path to a HammerRequest JSON file')
    hammer_run_candidate_parser.add_argument('--attempts-json', help='Inline attempts JSON array')
    hammer_run_candidate_parser.add_argument('--attempts-file', help='Path to an attempts JSON file')
    hammer_run_candidate_parser.add_argument('--portfolio-policy-json', default=None)
    hammer_run_candidate_parser.add_argument('--portfolio-policy-file', default=None)
    hammer_run_candidate_parser.add_argument('--premise-ids', help='Comma-separated premise ids')
    hammer_run_candidate_parser.add_argument('--translation-map-json', default=None)
    hammer_run_candidate_parser.add_argument('--translation-map-file', default=None)
    hammer_run_candidate_parser.add_argument(
        '--confirm', action='store_true',
        help='Explicitly authorize launching external solver processes',
    )
    hammer_run_candidate_parser.add_argument('--correlation-id', default=None)
    hammer_run_candidate_parser.add_argument('--format', '-f', default='json',
                                             choices=['text', 'json', 'compact'])

    hammer_reconstruct_parser = subparsers.add_parser(
        'hammer-reconstruct', help='Reconstruct and kernel-check a candidate proof (HAMMER-010)'
    )
    hammer_reconstruct_parser.add_argument('--request-json', help='Inline HammerRequest JSON')
    hammer_reconstruct_parser.add_argument('--request-file', help='Path to a HammerRequest JSON file')
    hammer_reconstruct_parser.add_argument('--candidate-json', help='Inline ProofCandidateRecord JSON')
    hammer_reconstruct_parser.add_argument('--candidate-file', help='Path to a ProofCandidateRecord JSON file')
    hammer_reconstruct_parser.add_argument('--itp', required=True, choices=['lean', 'coq', 'isabelle'])
    hammer_reconstruct_parser.add_argument('--theorem-id', required=True)
    hammer_reconstruct_parser.add_argument('--native-source', help='Inline native source text')
    hammer_reconstruct_parser.add_argument('--native-source-file', help='Path to a native source file')
    hammer_reconstruct_parser.add_argument('--environment-lock-json', default=None)
    hammer_reconstruct_parser.add_argument('--environment-lock-file', default=None)
    hammer_reconstruct_parser.add_argument('--timeout', type=float, default=None)
    hammer_reconstruct_parser.add_argument(
        '--confirm', action='store_true',
        help='Explicitly authorize launching the native ITP kernel process',
    )
    hammer_reconstruct_parser.add_argument('--correlation-id', default=None)
    hammer_reconstruct_parser.add_argument('--format', '-f', default='json',
                                           choices=['text', 'json', 'compact'])

    hammer_retrieve_receipt_parser = subparsers.add_parser(
        'hammer-retrieve-receipt', help='Fetch a persisted hammer receipt (HAMMER-012)'
    )
    hammer_retrieve_receipt_parser.add_argument('--receipt-id', required=True)
    hammer_retrieve_receipt_parser.add_argument('--publishable', action='store_true')
    hammer_retrieve_receipt_parser.add_argument('--store-root', default=None)
    hammer_retrieve_receipt_parser.add_argument('--correlation-id', default=None)
    hammer_retrieve_receipt_parser.add_argument('--format', '-f', default='json',
                                                choices=['text', 'json', 'compact'])

    hammer_persist_receipt_parser = subparsers.add_parser(
        'hammer-persist-receipt', help='Persist a hammer receipt (HAMMER-012 utility)'
    )
    hammer_persist_receipt_parser.add_argument('--receipt-json', help='Inline HammerReceipt JSON')
    hammer_persist_receipt_parser.add_argument('--receipt-file', help='Path to a HammerReceipt JSON file')
    hammer_persist_receipt_parser.add_argument('--publish', action='store_true')
    hammer_persist_receipt_parser.add_argument('--store-root', default=None)
    hammer_persist_receipt_parser.add_argument('--correlation-id', default=None)
    hammer_persist_receipt_parser.add_argument('--format', '-f', default='json',
                                               choices=['text', 'json', 'compact'])

    hammer_capability_status_parser = subparsers.add_parser(
        'hammer-capability-status',
        help='Report structured ITP/solver capability evidence (HAMMER-002/006/010)',
    )
    hammer_capability_status_parser.add_argument('--itps', help='Comma-separated subset of lean,coq,isabelle')
    hammer_capability_status_parser.add_argument('--solvers', help='Comma-separated subset of solver families')
    hammer_capability_status_parser.add_argument(
        '--no-probe-versions', action='store_true',
        help='Skip the bounded --version metadata probe (zero subprocess calls)',
    )
    hammer_capability_status_parser.add_argument('--correlation-id', default=None)
    hammer_capability_status_parser.add_argument('--format', '-f', default='json',
                                                 choices=['text', 'json', 'compact'])

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for logic CLI.
    
    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    command_map = {
        'parse': parse_command,
        'prove': prove_command,
        'analyze': analyze_command,
        'profile': profile_command,
        'translate': translate_command,
        'validate': validate_command,
        'hammer-inspect': hammer_inspect_command,
        'hammer-select-premises': hammer_select_premises_command,
        'hammer-translate': hammer_translate_command,
        'hammer-run-candidate': hammer_run_candidate_command,
        'hammer-reconstruct': hammer_reconstruct_command,
        'hammer-retrieve-receipt': hammer_retrieve_receipt_command,
        'hammer-persist-receipt': hammer_persist_receipt_command,
        'hammer-capability-status': hammer_capability_status_command,
    }
    
    command_func = command_map.get(args.command)
    if not command_func:
        print(f"Error: Unknown command '{args.command}'", file=sys.stderr)
        return 1
    
    try:
        result = command_func(args)
        output_format = getattr(args, 'output_format', None) or getattr(args, 'format', 'text')
        print(format_output(result, output_format))
        return 0 if result.get('success', False) else 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
