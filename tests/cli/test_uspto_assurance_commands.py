"""CLI tests for submission-assurance command (PATLAW-140).

Recorded E2E-style commands work from an input recipe without hand-built
middle-stage objects. Domain non-success yields a non-zero exit code so
scripts cannot mistake transport completion for assurance clearance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_MODULE = "ipfs_datasets_py.cli.uspto"


def _env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def run_uspto(
    args: Sequence[str],
    *,
    timeout: float = 120,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", _CLI_MODULE, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(),
        cwd=str(_REPO_ROOT),
    )


OA_TEXT = (
    "UNITED STATES PATENT AND TRADEMARK OFFICE NON-FINAL OFFICE ACTION "
    "Application No. 16/123,456 Mailing Date: January 15, 2024 "
    "Claims 1-3 are rejected under 35 U.S.C. 103."
)


def _recipe(
    tmp_path: Path,
    *,
    assurance_id: str = "assurance:cli-1",
    classification: str = "public_user",
    force_outage: bool = False,
    force_quarantine: bool = False,
    sparse: bool = False,
) -> Path:
    if sparse:
        documents = [
            {
                "document_id": "art:oa1",
                "role": "office_action",
                "text": OA_TEXT,
                "classification": classification if classification != "unknown" else None,
            }
        ]
    else:
        pub = classification if classification != "unknown" else "public_user"
        documents = [
            {
                "document_id": "art:oa1",
                "role": "office_action",
                "text": OA_TEXT,
                "classification": pub,
            },
            {
                "document_id": "art:spec",
                "role": "specification",
                "text": "DETAILED DESCRIPTION of the invention.",
                "classification": pub,
            },
            {
                "document_id": "art:claims",
                "role": "claims",
                "text": "1. A method comprising steps.",
                "classification": pub,
            },
            {
                "document_id": "art:draw",
                "role": "drawings",
                "text": "FIG. 1 drawing",
                "classification": pub,
            },
            {
                "document_id": "art:ads",
                "role": "ads",
                "text": "Application Data Sheet",
                "classification": pub,
            },
            {
                "document_id": "art:oath",
                "role": "oath",
                "text": "Declaration and oath signed",
                "classification": pub,
            },
            {
                "document_id": "art:fee",
                "role": "fee",
                "text": "Fee payment receipt",
                "classification": pub,
            },
            {
                "document_id": "art:seq",
                "role": "sequence_listing",
                "text": "SEQ ID NO:1",
                "classification": pub,
            },
            {
                "document_id": "art:rem",
                "role": "remarks",
                "text": "Applicant respectfully submits remarks.",
                "classification": pub,
            },
        ]
    payload = {
        "tenant_id": "tenant-cli-140",
        "matter_id": "matter:cli-assurance-1",
        "assurance_id": assurance_id,
        "application_number": "16123456",
        "documents": documents,
        "status_snapshot": {
            "application_number": "16123456",
            "mailing_date": "2024-01-15",
            "status_code": "PEND",
        },
        "source_profile": "offline_authorized",
        "application_type": "utility",
        "scenario": "new_application",
        "as_of_utc": "2024-01-15T00:00:00Z",
        "authority_snapshot_id": "auth:cli-1",
        "classification": classification if classification != "omit" else None,
        "offline": True,
        "run_preflight": False,
        "force_outage": force_outage,
        "force_quarantine": force_quarantine,
        "labels": {"suite": "cli-assurance"},
    }
    # Drop null classification key when omitted so processor defaults to UNKNOWN
    if classification == "omit":
        payload.pop("classification", None)
        for doc in payload["documents"]:
            doc.pop("classification", None)
    path = tmp_path / f"{assurance_id.replace(':', '_')}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


class TestSubmissionAssuranceCliHelp:
    def test_root_help_lists_submission_assurance(self) -> None:
        result = run_uspto(["--help"])
        assert result.returncode == 0
        text = (result.stdout + result.stderr).lower()
        assert "submission-assurance" in text
        assert "no sign" in text or "never signs" in text or "not legal advice" in text

    def test_submission_assurance_help(self) -> None:
        result = run_uspto(["submission-assurance", "--help"])
        assert result.returncode == 0
        text = result.stdout.lower()
        assert "--input-json" in text
        assert "--tenant" in text
        assert "--matter-id" in text
        assert "--api-key " not in text
        assert "password" not in text
        assert "never" in text or "not legal" in text or "review" in text

    def test_commands_constant_includes_assurance(self) -> None:
        from ipfs_datasets_py.cli.uspto import COMMANDS, FORBIDDEN_COMMANDS

        assert "submission-assurance" in COMMANDS
        assert "sign" in FORBIDDEN_COMMANDS
        assert "pay" in FORBIDDEN_COMMANDS
        assert "file" in FORBIDDEN_COMMANDS


class TestSubmissionAssuranceCliE2E:
    def test_recorded_recipe_runs_without_middle_stages(self, tmp_path: Path) -> None:
        recipe = _recipe(tmp_path, assurance_id="assurance:cli-e2e-1")
        ckpt = tmp_path / "ckpt"
        result = run_uspto(
            [
                "--json",
                "submission-assurance",
                "--input-json",
                str(recipe),
                "--checkpoint-dir",
                str(ckpt),
                "--no-preflight",
            ]
        )
        # May be 0 (completed) or 3 (domain non-success); must parse payload
        assert result.returncode in (0, 3), result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema_version"].startswith("uspto.submission-assurance")
        assert payload["tenant_id"] == "tenant-cli-140"
        assert payload["matter_id"] == "matter:cli-assurance-1"
        assert "coverage" in payload
        assert "statuses" in payload["coverage"]
        for dim in ("sync", "extraction", "authority", "proof", "compliance"):
            assert dim in payload["coverage"]["statuses"]
        for key in (
            "satisfied_items",
            "missing_items",
            "contradictory_items",
            "unknown_items",
            "review_items",
        ):
            assert key in payload
            assert isinstance(payload[key], list)
        # Provenance on at least one item when present
        for item in payload.get("items") or []:
            assert "item_id" in item
            assert "kind" in item
            assert "provenance" in item
            for prov in item["provenance"]:
                assert "ref_id" in prov
                assert "kind" in prov
        assert payload["is_legal_advice"] is False
        assert "api_key" not in json.dumps(payload)
        assert "Applicant respectfully" not in result.stdout
        assert payload.get("transport_ok") is True

    def test_quarantine_exits_nonzero(self, tmp_path: Path) -> None:
        recipe = _recipe(
            tmp_path,
            assurance_id="assurance:cli-q-1",
            classification="omit",
            sparse=True,
        )
        result = run_uspto(
            [
                "--json",
                "submission-assurance",
                "--input-json",
                str(recipe),
                "--no-preflight",
            ]
        )
        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["is_quarantined"] is True
        assert payload["disposition"] == "quarantined"
        # Transport completed; domain did not
        assert payload["transport_ok"] is True

    def test_outage_exits_nonzero(self, tmp_path: Path) -> None:
        recipe = _recipe(
            tmp_path,
            assurance_id="assurance:cli-outage-1",
            force_outage=True,
            sparse=True,
        )
        result = run_uspto(
            [
                "--json",
                "submission-assurance",
                "--input-json",
                str(recipe),
                "--no-preflight",
            ]
        )
        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["is_outage"] is True
        assert payload["transport_ok"] is False

    def test_missing_required_args_fails(self) -> None:
        result = run_uspto(["--json", "submission-assurance"])
        assert result.returncode != 0
        err = result.stderr + result.stdout
        assert "missing_assurance_input" in err or "tenant" in err.lower()

    def test_no_secret_flags(self) -> None:
        from ipfs_datasets_py.cli.uspto import create_parser

        help_text = create_parser().format_help()
        for banned in (
            "--api-key ",
            "--password",
            "--secret",
            "--token",
            "--cookie",
            "--session",
        ):
            assert banned not in help_text, banned
        assert "submission-assurance" in help_text
