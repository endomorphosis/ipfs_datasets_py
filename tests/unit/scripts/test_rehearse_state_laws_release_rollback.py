"""Focused production-CLI trust-boundary tests for LCR-045."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.legal_data import rehearse_state_laws_release_rollback as rehearsal
from scripts.ops.legal_data import state_laws_release_probe as probe


def test_generation_cli_rejects_external_pin_probe_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    external = tmp_path / "operator-pin-probes.json"
    external.write_text(json.dumps({"new": {}, "previous": {}}), encoding="utf-8")
    assert rehearsal.main(["--pin-probes", str(external)]) == 1
    assert "external --pin-probes cannot authorize" in capsys.readouterr().err


def test_check_remains_offline_and_rejects_network_flag() -> None:
    assert rehearsal.main(["--check", "--network"]) == 1


def test_builder_rejects_unsealed_dual_pin_measurement() -> None:
    from tests.unit.scripts.test_check_state_laws_public_release import (
        _canary,
        _publication_receipt,
    )

    publication = _publication_receipt()
    canary = _canary()
    pin_probes = {
        "new": {
            "bounded": True,
            "fixture_only": False,
            "queryable": True,
            "readable": True,
            "revision": publication["public_revision"],
        },
        "previous": {
            "bounded": True,
            "fixture_only": False,
            "queryable": True,
            "readable": True,
            "revision": publication["previous_public_pin"],
        },
        "switch": {
            "back_to_new": True,
            "bounded": True,
            "deletion_performed": False,
            "recoverable": True,
            "remote_mutation_performed": False,
            "to_previous": True,
        },
        "board_diagnostics": {"blocked": True, "idle": True, "stale": True},
        "externally_supplied": False,
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.dual_pin_probe_bindings(
            repo_id=publication["dataset_repo_id"],
            new_revision=publication["public_revision"],
            previous_revision=publication["previous_public_pin"],
            release_manifest_digest=publication["release_manifest_digest"],
            parent_evidence_digest=canary["canonical_digest"],
        ),
        # Deliberately omitted: measurement_source.
    }
    with pytest.raises(rehearsal.RehearsalMismatchError, match="internally measured"):
        rehearsal.build_canonical_rollback_rehearsal(
            publication_receipt=publication,
            public_canary=canary,
            pin_probes=pin_probes,
        )
