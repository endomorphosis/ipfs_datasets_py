#!/usr/bin/env python3
"""Prove shared substrate and vector-space compatibility across both public pins (LCR-067).

Read-only composition over the immutable state-law and Federal Register
public revisions. Default ``--check`` is credential-free and does not
contact the Hub:

1. Load the sealed public canaries (LCR-043 / LCR-066) and bind their
   immutable 40-hex public SHAs.
2. Rebuild the LCR-067 compatibility proof: shared resolver/descriptor/
   family/bound contracts, exact ``vector_space_id`` identity, labeled
   normalized fusion, per-corpus filters, bounded federated fetch, and
   abstention when spaces diverge.
3. Reject the claim that matching dimension alone establishes
   compatibility.
4. Package every graph/retrieval output as a research aid — never legal
   authority or advice.
5. Compare the rebuilt canary to
   ``docs/reports/legal_corpora_reindex/cross_corpus_canary.json``.

Official validation gate::

    python scripts/ops/legal_data/canary_legal_corpora_public_releases.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_corpora_query import (  # noqa: E402
    ACCEPTANCE_FLAGS,
    CANARY_PRODUCER,
    CORPUS_FEDERAL_REGISTER,
    CORPUS_STATE_LAWS,
    DEFAULT_FEDERAL_PUBLIC_CANARY_RELPATH,
    DEFAULT_FEDERAL_PUBLICATION_RECEIPT_RELPATH,
    DEFAULT_OBSERVATION_CUTOFF,
    DEFAULT_REPORT_RELPATH,
    DEFAULT_STATE_PUBLIC_CANARY_RELPATH,
    DEFAULT_STATE_PUBLICATION_RECEIPT_RELPATH,
    GOAL_ID,
    PROGRAM_ID,
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    RESEARCH_AID_DISCLAIMER,
    SECRET_ENV_NAMES,
    SHARED_VECTOR_SPACE_ID,
    TASK_ID,
    LegalAuthorityCollisionError,
    LegalCorporaQueryError,
    LegalCorporaQueryInputError,
    QueryPinError,
    SharedSubstrateIncompatibilityError,
    VectorSpaceIncompatibilityError,
    assert_immutable_revision,
    assert_no_retrieval_as_legal_authority,
    build_cross_corpus_canary,
    compare_cross_corpus_canaries,
    default_report_path,
    dimension_only_incompatibility_case,
    load_cross_corpus_canary,
    open_legal_corpora_query_client,
    pin_from_public_canary,
    prove_graph_ontologies_remain_private,
    prove_shared_substrate,
    prove_vector_space_compatibility,
    require_compatible_vector_spaces,
    research_aid_semantics,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MutableRevisionError,
    ResolverError,
    validate_repo_id,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

PRODUCER: Final = CANARY_PRODUCER
MAX_REPORT_BYTES: Final = 1_048_576
HEX40_RE: Final = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_OPERATIONS: Final = (
    "change_visibility",
    "delete",
    "delete_file",
    "delete_folder",
    "force",
    "force-push",
    "force_push",
    "history_rewrite",
    "make_private",
    "make_unlisted",
    "overwrite_history",
    "overwrite_legacy",
    "rotate_credentials",
    "set_private",
    "set_unlisted",
    "super_squash_history",
    "visibility_change",
)


class CrossCorpusCanaryError(LegalCorporaQueryError):
    """Raised when the dual-release public canary fails closed."""

    code = "cross_corpus_canary_error"


class CrossCorpusCanarySafetyError(CrossCorpusCanaryError):
    """Raised when credentials, mutation, or secrets are observed."""

    code = "cross_corpus_canary_unsafe"


class CrossCorpusCanaryPinError(CrossCorpusCanaryError, QueryPinError):
    """Raised when a public pin is missing, fixture-only, or mutable."""

    code = "cross_corpus_canary_pin_invalid"


# ---------------------------------------------------------------------------
# IO / safety
# ---------------------------------------------------------------------------


def repository_root(path: Path | str | None = None) -> Path:
    if path is None:
        return REPOSITORY_ROOT
    return Path(path).expanduser().resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise CrossCorpusCanaryError(f"required JSON not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CrossCorpusCanaryError(f"{target} must contain a JSON object")
    return dict(payload)


def write_json(path: Path | str | None, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(target)


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    joined = " ".join(str(item) for item in argv).lower()
    for name in SECRET_ENV_NAMES:
        token = os.environ.get(name)
        if token and token in " ".join(str(item) for item in argv):
            raise CrossCorpusCanarySafetyError(
                f"secret from {name} must not appear on the command line"
            )
        if name.lower() in joined and "=" in joined:
            raise CrossCorpusCanarySafetyError(
                f"secret environment name {name} must not be passed as a value"
            )


_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{20,}")
_BEARER_RE = re.compile(r"bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(r"-----begin (?:rsa |ec |openssh )?private key-----", re.I)


def reject_credentials_in_payload(payload: Mapping[str, Any], *, label: str) -> None:
    blob = json.dumps(payload, ensure_ascii=False)
    lowered = blob.lower()
    if _HF_TOKEN_RE.search(blob) or _BEARER_RE.search(blob) or _PRIVATE_KEY_RE.search(blob):
        raise CrossCorpusCanarySafetyError(
            f"{label} must not embed credentials or private key material"
        )
    if "authorization:" in lowered:
        raise CrossCorpusCanarySafetyError(f"{label} must not embed credentials")
    if "/home/" in lowered or "/users/" in lowered:
        raise CrossCorpusCanarySafetyError(
            f"{label} must not embed absolute filesystem paths"
        )


def _require_hex_pin(value: Any, *, name: str) -> str:
    pin = assert_immutable_revision(value, name=name)
    if not HEX40_RE.fullmatch(pin):
        raise CrossCorpusCanaryPinError(f"{name} must be a 40-hex revision, got {value!r}")
    return pin


def load_public_canary(
    *,
    relpath: Path,
    repo_root: Path | str | None = None,
    override: Path | str | None = None,
) -> dict[str, Any]:
    root = repository_root(repo_root)
    path = Path(override) if override is not None else root / relpath
    payload = load_json_mapping(path)
    reject_credentials_in_payload(payload, label=relpath.as_posix())
    return payload


def load_publication_receipt(
    *,
    relpath: Path,
    repo_root: Path | str | None = None,
    override: Path | str | None = None,
) -> dict[str, Any]:
    root = repository_root(repo_root)
    path = Path(override) if override is not None else root / relpath
    payload = load_json_mapping(path)
    reject_credentials_in_payload(payload, label=relpath.as_posix())
    return payload


def extract_public_pin(payload: Mapping[str, Any], *, name: str) -> str:
    pin = (
        payload.get("public_sha")
        or payload.get("public_revision")
        or payload.get("revision")
    )
    return _require_hex_pin(pin, name=name)


def assert_public_pin_contract(
    canary: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    label: str,
) -> str:
    if canary.get("fixture_only") is not False:
        raise CrossCorpusCanaryPinError(
            f"{label} public canary is fixture-only and cannot seal LCR-067"
        )
    if canary.get("live_network") is not True:
        raise CrossCorpusCanaryPinError(
            f"{label} public canary does not prove a live immutable redownload"
        )
    if canary.get("read_only") is not True:
        raise CrossCorpusCanaryPinError(f"{label} public canary is not read-only")
    if receipt.get("fixture_only") is not False:
        raise CrossCorpusCanaryPinError(
            f"{label} publication receipt is fixture-only"
        )
    if (
        receipt.get("live_network") is not True
        or receipt.get("mutation_executed") is not True
    ):
        raise CrossCorpusCanaryPinError(
            f"{label} publication receipt does not prove the live commit"
        )
    canary_pin = extract_public_pin(canary, name=f"{label}.public_sha")
    receipt_pin = extract_public_pin(receipt, name=f"{label}.receipt.public_sha")
    if canary_pin != receipt_pin:
        raise CrossCorpusCanaryPinError(
            f"{label} public canary SHA {canary_pin} does not match "
            f"publication receipt SHA {receipt_pin}"
        )
    canary_manifest = str(
        canary.get("manifest_digest") or canary.get("final_manifest_digest") or ""
    )
    receipt_manifest = str(
        receipt.get("manifest_digest") or receipt.get("final_manifest_digest") or ""
    )
    if not re.fullmatch(r"[0-9a-f]{64}", canary_manifest) or (
        canary_manifest != receipt_manifest
    ):
        raise CrossCorpusCanaryPinError(
            f"{label} public canary manifest does not match its receipt"
        )
    try:
        validate_repo_id(
            str(
                canary.get("dataset_repo_id")
                or canary.get("target_repo")
                or canary.get("target")
            ),
            name=f"{label}.dataset_repo_id",
        )
    except ResolverError as exc:
        raise CrossCorpusCanaryPinError(str(exc)) from exc
    return canary_pin


# ---------------------------------------------------------------------------
# Canary construction / check
# ---------------------------------------------------------------------------


def build_dual_release_canary(
    *,
    repo_root: Path | str | None = None,
    state_canary_path: Path | str | None = None,
    federal_canary_path: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    """Rebuild the sealed dual-release compatibility canary offline."""

    root = repository_root(repo_root)
    state_canary = load_public_canary(
        relpath=DEFAULT_STATE_PUBLIC_CANARY_RELPATH,
        repo_root=root,
        override=state_canary_path,
    )
    federal_canary = load_public_canary(
        relpath=DEFAULT_FEDERAL_PUBLIC_CANARY_RELPATH,
        repo_root=root,
        override=federal_canary_path,
    )
    state_receipt = load_publication_receipt(
        relpath=DEFAULT_STATE_PUBLICATION_RECEIPT_RELPATH,
        repo_root=root,
    )
    federal_receipt = load_publication_receipt(
        relpath=DEFAULT_FEDERAL_PUBLICATION_RECEIPT_RELPATH,
        repo_root=root,
    )
    if require_public_pin:
        assert_public_pin_contract(state_canary, state_receipt, label="state_laws")
        assert_public_pin_contract(
            federal_canary, federal_receipt, label="federal_register"
        )
    else:
        extract_public_pin(state_canary, name="state_laws.public_sha")
        extract_public_pin(federal_canary, name="federal_register.public_sha")

    state_pin = pin_from_public_canary(state_canary, corpus_id=CORPUS_STATE_LAWS)
    federal_pin = pin_from_public_canary(
        federal_canary, corpus_id=CORPUS_FEDERAL_REGISTER
    )
    prove_shared_substrate(state_pin, federal_pin)
    prove_vector_space_compatibility(state_pin, federal_pin, strict=True)
    prove_graph_ontologies_remain_private(state_pin, federal_pin)
    require_compatible_vector_spaces(state_pin, federal_pin)

    report = build_cross_corpus_canary(
        state_canary=state_canary,
        federal_canary=federal_canary,
    )
    reject_credentials_in_payload(report, label="cross_corpus_canary")
    assert_no_retrieval_as_legal_authority(report.get("research_aid") or {})
    encoded = json.dumps(report, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise CrossCorpusCanaryError(
            f"cross-corpus canary exceeds {MAX_REPORT_BYTES} bytes"
        )
    return report


def _acceptance_failures(payload: Mapping[str, Any]) -> list[str]:
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        return ["acceptance missing"]
    failures: list[str] = []
    for flag in ACCEPTANCE_FLAGS:
        if acceptance.get(flag) is not True:
            failures.append(f"acceptance.{flag}")
    if payload.get("status") != "passed":
        failures.append("status")
    if payload.get("legal_authority") is True:
        failures.append("legal_authority")
    research = payload.get("research_aid") or {}
    if isinstance(research, Mapping):
        if research.get("legal_authority") is not False:
            failures.append("research_aid.legal_authority")
        if research.get("legal_advice") is not False:
            failures.append("research_aid.legal_advice")
    if payload.get("vector_space_id") != SHARED_VECTOR_SPACE_ID:
        failures.append("vector_space_id")
    if payload.get("fixture_only") is not False:
        failures.append("fixture_only")
    if payload.get("live_network") is True or payload.get("network_required") is True:
        failures.append("network")
    if payload.get("task_id") != TASK_ID:
        failures.append("task_id")
    if payload.get("schema") != REPORT_SCHEMA:
        failures.append("schema")
    return failures


def check_cross_corpus_canary(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    """Validate the sealed report against a freshly rebuilt compatibility proof."""

    root = repository_root(repo_root)
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    if not sealed_path.is_file():
        raise CrossCorpusCanaryError(
            f"sealed cross-corpus canary not found: {DEFAULT_REPORT_RELPATH.as_posix()}"
        )
    sealed = load_cross_corpus_canary(sealed_path)
    reject_credentials_in_payload(sealed, label="sealed_cross_corpus_canary")
    fresh = build_dual_release_canary(
        repo_root=root,
        require_public_pin=True,
    )
    mismatches = compare_cross_corpus_canaries(fresh, sealed)
    if mismatches:
        raise CrossCorpusCanaryError(
            "cross-corpus canary check failed: " + ", ".join(mismatches[:16])
        )

    acceptance_failures = _acceptance_failures(sealed)
    if acceptance_failures:
        raise CrossCorpusCanaryError(
            "sealed canary acceptance failed: " + ", ".join(acceptance_failures)
        )

    dimension_case = dimension_only_incompatibility_case()
    if dimension_case.get("ok") is not True:
        raise CrossCorpusCanaryError(
            "dimension-only compatibility case must fail closed"
        )
    try:
        require_compatible_vector_spaces(
            dimension_case["left"],
            dimension_case["right"],
            left_name="gte",
            right_name="minilm",
        )
    except VectorSpaceIncompatibilityError:
        pass
    else:
        raise CrossCorpusCanaryError(
            "dimension-matched foreign space must raise VectorSpaceIncompatibilityError"
        )

    client = open_legal_corpora_query_client(
        state_canary=load_public_canary(
            relpath=DEFAULT_STATE_PUBLIC_CANARY_RELPATH, repo_root=root
        ),
        federal_canary=load_public_canary(
            relpath=DEFAULT_FEDERAL_PUBLIC_CANARY_RELPATH, repo_root=root
        ),
    )
    proof = client.compatibility_proof()
    if proof.get("vector", {}).get("compatible") is not True:
        raise CrossCorpusCanaryError("public pins must share vector_space_id")
    if proof.get("vector", {}).get("dimension_alone_cannot_establish_compatibility") is not True:
        raise CrossCorpusCanaryError("dimension-alone rule missing from proof")
    semantics = research_aid_semantics()
    assert_no_retrieval_as_legal_authority(semantics)
    if RESEARCH_AID_DISCLAIMER not in str(sealed.get("currentness_disclaimer") or ""):
        raise CrossCorpusCanaryError("sealed canary missing research-aid disclaimer")

    return {
        "check": "pass",
        "compatibility_ok": True,
        "dimension_alone_cannot_establish_compatibility": True,
        "fixture_only": False,
        "goal_id": GOAL_ID,
        "graph_retrieval_not_legal_advice": True,
        "graph_retrieval_not_legal_authority": True,
        "mismatches": [],
        "network_required": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "provenance_safe": True,
        "read_only": True,
        "require_public_pin": True,
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "passed",
        "task_id": TASK_ID,
        "vector_space_id": SHARED_VECTOR_SPACE_ID,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canary_legal_corpora_public_releases.py",
        description=(
            "Prove shared substrate and vector-space compatibility across "
            "the immutable state-law and Federal Register public releases."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the sealed cross_corpus_canary.json against a rebuilt proof.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Rebuild and write docs/reports/legal_corpora_reindex/cross_corpus_canary.json.",
    )
    parser.add_argument(
        "--require-public-pin",
        action="store_true",
        help="Refuse fixture-only canaries; require recorded immutable public SHAs.",
    )
    parser.add_argument(
        "--canary-report",
        type=Path,
        default=None,
        help="Override path to the sealed cross-corpus canary report.",
    )
    parser.add_argument(
        "--state-canary",
        type=Path,
        default=None,
        help="Override path to the state-law public canary.",
    )
    parser.add_argument(
        "--federal-canary",
        type=Path,
        default=None,
        help="Override path to the Federal Register public canary.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the check JSON (default: stdout).",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Rejected: this canary is read-only and never contacts the Hub.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except (CrossCorpusCanaryError, CrossCorpusCanarySafetyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.network:
            raise CrossCorpusCanarySafetyError(
                "cross-corpus canary never contacts the Hub; omit --network"
            )
        if args.require_public_pin and not (args.check or args.write_report):
            args.check = True

        if args.write_report:
            report = build_dual_release_canary(
                require_public_pin=True,
                state_canary_path=args.state_canary,
                federal_canary_path=args.federal_canary,
            )
            target = args.canary_report or default_report_path()
            encoded = (
                json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.partial")
            partial.write_text(encoded, encoding="utf-8")
            partial.replace(target)
            write_json(
                args.output,
                {
                    "ok": True,
                    "path": DEFAULT_REPORT_RELPATH.as_posix(),
                    "status": "report_written",
                    "task_id": TASK_ID,
                    "vector_space_id": SHARED_VECTOR_SPACE_ID,
                },
            )
            return 0

        if args.check or not argv_list:
            result = check_cross_corpus_canary(
                path=args.canary_report,
                require_public_pin=bool(args.require_public_pin),
            )
            write_json(args.output, result)
            return 0 if result.get("ok") else 1

        parser.print_help()
        return 2
    except (
        CrossCorpusCanaryError,
        LegalCorporaQueryError,
        LegalCorporaQueryInputError,
        LegalAuthorityCollisionError,
        SharedSubstrateIncompatibilityError,
        VectorSpaceIncompatibilityError,
        QueryPinError,
        MutableRevisionError,
        ResolverError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
