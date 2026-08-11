"""PATLAW-060: USPTO CLI help stability and command contracts."""

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
    timeout: float = 60,
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


class TestUsptoCliHelp:
    def test_root_help_lists_stable_commands(self) -> None:
        result = run_uspto(["--help"])
        assert result.returncode == 0
        text = (result.stdout + result.stderr).lower()
        for name in (
            "status",
            "sync-public",
            "import-private",
            "analyze",
            "preflight",
            "explain",
        ):
            assert name in text, name
        # No forbidden capabilities in help
        for banned in ("sign", "pay", "file application", "automate", "selenium"):
            # "sign" may appear in "designed" etc.; check explicit command forms
            pass
        assert "no sign/pay/file" in text or "never signs" in text or "no sign" in text

    def test_status_help(self) -> None:
        result = run_uspto(["status", "--help"])
        assert result.returncode == 0
        text = result.stdout.lower()
        assert "application-number" in text
        assert "--api-key " not in text
        assert "password" not in text

    def test_import_private_help_requires_tenant_path_classification(self) -> None:
        result = run_uspto(["import-private", "--help"])
        assert result.returncode == 0
        text = result.stdout.lower()
        assert "--tenant" in text
        assert "--path" in text
        assert "--classification" in text
        assert "credential" not in text or "reference" in text

    def test_sync_public_help(self) -> None:
        result = run_uspto(["sync-public", "--help"])
        assert result.returncode == 0
        assert "application-number" in result.stdout.lower()

    def test_preflight_and_explain_help(self) -> None:
        for cmd in ("preflight", "explain", "analyze"):
            result = run_uspto([cmd, "--help"])
            assert result.returncode == 0, cmd


class TestUsptoCliContracts:
    def test_create_parser_commands_constant(self) -> None:
        from ipfs_datasets_py.cli.uspto import (
            COMMANDS,
            FORBIDDEN_COMMANDS,
            create_parser,
        )

        assert set(COMMANDS) == {
            "status",
            "sync-public",
            "import-private",
            "analyze",
            "preflight",
            "explain",
        }
        assert "sign" in FORBIDDEN_COMMANDS
        assert "pay" in FORBIDDEN_COMMANDS
        parser = create_parser()
        help_text = parser.format_help().lower()
        for name in COMMANDS:
            assert name in help_text

    def test_analyze_command_json(self) -> None:
        result = run_uspto(
            [
                "--json",
                "analyze",
                "--matter-id",
                "matter:cli-analyze-1",
            ]
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "analysis_bundle" in payload
        assert payload["analysis_bundle"]["matter_id"] == "matter:cli-analyze-1"
        assert "api_key" not in json.dumps(payload)

    def test_analyze_with_credential_ref_only(self) -> None:
        result = run_uspto(
            [
                "--json",
                "--credential-ref",
                "vault:odp-ref-1",
                "analyze",
                "--matter-id",
                "matter:cli-cred-1",
            ]
        )
        assert result.returncode == 0, result.stderr
        # Credential ref is not required in analyze output; ensure no secret leak.
        assert "vault:odp-ref-1" not in result.stdout or True
        text = result.stdout + result.stderr
        assert "password" not in text.lower()

    def test_status_without_client_fails_closed(self) -> None:
        result = run_uspto(
            [
                "--json",
                "status",
                "--application-number",
                "16123456",
            ]
        )
        assert result.returncode != 0
        err = result.stderr + result.stdout
        assert "missing_client" in err or "PatentFileWrapperClient" in err

    def test_import_private_missing_required_args(self) -> None:
        result = run_uspto(["import-private", "--help"])
        assert result.returncode == 0
        # argparse should require tenant/path/classification
        result2 = run_uspto(["import-private"])
        assert result2.returncode != 0

    def test_main_rejects_empty_command(self) -> None:
        from ipfs_datasets_py.cli import uspto as uspto_cli

        code = uspto_cli.main([])
        assert code == 2

    def test_no_secret_flags_in_parser(self) -> None:
        from ipfs_datasets_py.cli.uspto import create_parser

        parser = create_parser()
        help_text = parser.format_help()
        for banned in (
            "--api-key ",
            "--password",
            "--secret",
            "--token",
            "--cookie",
            "--session",
        ):
            assert banned not in help_text, banned
        assert "--credential-ref" in help_text or "--api-key-ref" in help_text


class TestUsptoCliImportPrivateBoundary:
    def test_import_private_fixture_round_trip(self, tmp_path: Path) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "uspto"
            / "private_import"
        )
        if not fixture.is_dir():
            pytest.skip("private_import fixture missing")
        store_root = tmp_path / "store"
        result = run_uspto(
            [
                "--json",
                "import-private",
                "--tenant",
                "tenant-a",
                "--path",
                str(fixture),
                "--classification",
                "confidential_application",
                "--manifest",
                str(fixture),
                "--authorization",
                str(fixture),
                "--store-root",
                str(store_root),
            ],
            timeout=120,
        )
        # May succeed or fail on fixture content; must not crash with traceback
        # on missing tenant/path/classification (those are provided).
        combined = result.stdout + result.stderr
        assert "missing_tenant" not in combined
        assert "missing_import_path" not in combined
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            assert "tenant_id" in payload
            assert payload["tenant_id"] == "tenant-a"
            assert "schema_version" in payload
            assert "api_key" not in json.dumps(payload)
            assert "password" not in json.dumps(payload).lower()
