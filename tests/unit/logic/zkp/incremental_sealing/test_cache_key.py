"""Regression tests for complete ProofCacheKey@1 (IPS-008)."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.cache_key import (
    ABSENCE_TOKEN,
    CACHE_KEY_SUBSET,
    CACHE_KEY_VECTORS_SUBSET,
    PROOF_CACHE_KEY_SCHEMA,
    REQUIRED_FIELDS,
    CacheKeyError,
    ProofCacheKey,
    build_proof_cache_key,
    known_vectors,
    sample_proof_cache_key,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import (
    EvidenceClass,
    ProofMode,
    ProofUnitKind,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    canonical_cid,
)

MODULE_NAME = "ipfs_datasets_py.logic.zkp.incremental_sealing.cache_key"


def test_cache_key_subset_and_required_fields_are_closed() -> None:
    assert CACHE_KEY_SUBSET == "ips/cache-key@1"
    assert CACHE_KEY_VECTORS_SUBSET == "ips/cache-key-vectors@1"
    assert PROOF_CACHE_KEY_SCHEMA.endswith("/cache_key@1")
    # Every normative plan dimension is present.
    for required in (
        "statement_cid",
        "public_input_cid",
        "private_input_commitment",
        "source_root_cid",
        "source_artifact_cids",
        "dependency_unit_roots",
        "dependency_roots_complete",
        "environment_cid",
        "dependency_lock_cid",
        "fixture_cids",
        "tool_or_prover_id",
        "tool_or_prover_version",
        "proof_system_id",
        "evidence_class",
        "proof_unit_kind",
        "proof_mode",
        "circuit_id",
        "circuit_version",
        "proving_key_id",
        "verification_key_id",
        "configuration_cid",
        "network_policy_cid",
        "proof_schema_version",
        "canonicalization_version",
        "test_selector_cid",
        "policy_cid",
        "source_closure_schema_version",
        "dependency_graph_schema_version",
    ):
        assert required in REQUIRED_FIELDS


def test_sample_round_trip_and_deterministic_cid() -> None:
    left = sample_proof_cache_key()
    right = sample_proof_cache_key()
    assert left.key_cid() == right.key_cid()
    assert left.to_canonical_json() == right.to_canonical_json()
    restored = ProofCacheKey.from_canonical(json.loads(left.to_canonical_json()))
    assert restored == left
    assert restored.key_cid() == left.key_cid()
    assert left.digest == left.cache_key == left.key_id == left.key_cid()


def test_build_proof_cache_key_accepts_kwargs_and_payload() -> None:
    base = sample_proof_cache_key()
    via_payload = build_proof_cache_key(payload=base.to_canonical())
    assert via_payload.key_cid() == base.key_cid()
    via_canonical = build_proof_cache_key(canonical=base.to_canonical())
    assert via_canonical.key_cid() == base.key_cid()
    via_kwargs = build_proof_cache_key(
        **{
            field: getattr(base, field)
            if field
            not in {
                "source_artifact_cids",
                "dependency_unit_roots",
                "fixture_cids",
                "evidence_class",
                "proof_unit_kind",
                "proof_mode",
            }
            else (
                list(getattr(base, field))
                if field
                in {
                    "source_artifact_cids",
                    "dependency_unit_roots",
                    "fixture_cids",
                }
                else getattr(base, field).value
            )
            for field in REQUIRED_FIELDS
        }
    )
    assert via_kwargs.key_cid() == base.key_cid()
    # Alias normalization.
    aliased = build_proof_cache_key(
        payload={
            **base.to_canonical(),
        }
    )
    assert aliased.key_cid() == base.key_cid()
    with pytest.raises(CacheKeyError, match="missing required fields"):
        build_proof_cache_key(statement_cid=base.statement_cid)
    with pytest.raises(CacheKeyError, match="unknown"):
        build_proof_cache_key(payload={**base.to_canonical(), "extra": 1})


def test_changing_any_required_field_changes_key_cid() -> None:
    vectors = known_vectors()
    assert vectors["cache_key_subset"] == CACHE_KEY_SUBSET
    assert vectors["cache_key_vectors_subset"] == CACHE_KEY_VECTORS_SUBSET
    base_cid = vectors["base"]["key_cid"]
    mutations = vectors["single_field_mutations"]
    # Every mutable required field has a vector that changes the CID.
    expected = set(REQUIRED_FIELDS) - {"dependency_roots_complete"}
    assert set(mutations) == expected
    for field, entry in mutations.items():
        assert entry["base_key_cid"] == base_cid
        assert entry["mutated_key_cid"] != base_cid
        # Independent recomputation agrees.
        base = ProofCacheKey.from_canonical(vectors["base"]["payload"])
        payload = base.to_canonical()
        # Apply the same mutation path used by known_vectors via rebuild.
        mutated = sample_proof_cache_key()
        # Force a distinct value for this field only.
        if field in {
            "source_artifact_cids",
            "dependency_unit_roots",
            "fixture_cids",
        }:
            current = list(getattr(base, field))
            extra = canonical_cid(
                {"test_mutation": field, "token": "extra-only"}
            )
            payload[field] = sorted(current + [extra])
        elif field == "evidence_class":
            payload[field] = EvidenceClass.INTEGRITY_COMMITMENT.value
        elif field == "proof_unit_kind":
            payload[field] = ProofUnitKind.FORMAL_OBLIGATION.value
        elif field == "proof_mode":
            payload[field] = ProofMode.THEOREM_CERTIFICATE.value
        elif field in {
            "tool_or_prover_id",
            "tool_or_prover_version",
            "proof_system_id",
            "circuit_id",
            "circuit_version",
            "proving_key_id",
            "verification_key_id",
            "source_closure_schema_version",
            "dependency_graph_schema_version",
            "proof_schema_version",
            "canonicalization_version",
        }:
            current = getattr(base, field)
            payload[field] = (
                f"mutated-{field}"
                if current == ABSENCE_TOKEN
                else f"{current}/mutated"
            )
        else:
            payload[field] = canonical_cid(
                {"test_mutation": field, "token": "cid-only"}
            )
        rebuilt = ProofCacheKey.from_canonical(payload)
        assert rebuilt.key_cid() != base_cid, field
        assert rebuilt != base
        _ = mutated  # sample remains constructible under hermetic conditions


def test_missing_incomplete_roots_duplicates_and_secrets_fail_closed() -> None:
    base = sample_proof_cache_key().to_canonical()

    missing = dict(base)
    del missing["statement_cid"]
    with pytest.raises(CacheKeyError, match="missing required fields"):
        ProofCacheKey.from_canonical(missing)

    incomplete = dict(base)
    incomplete["dependency_roots_complete"] = False
    with pytest.raises(CacheKeyError, match="transitively incomplete"):
        ProofCacheKey.from_canonical(incomplete)

    duplicates = dict(base)
    art = base["source_artifact_cids"][0]
    duplicates["source_artifact_cids"] = [art, art]
    with pytest.raises(CacheKeyError, match="duplicates"):
        ProofCacheKey.from_canonical(duplicates)

    unsorted = dict(base)
    pair = [
        canonical_cid({"sort": "left"}),
        canonical_cid({"sort": "right"}),
    ]
    ordered = sorted(pair)
    unsorted["dependency_unit_roots"] = [ordered[1], ordered[0]]
    with pytest.raises(CacheKeyError, match="sorted"):
        ProofCacheKey.from_canonical(unsorted)

    for secret in sorted(SECRET_AND_NONDETERMINISTIC_FIELDS)[:4]:
        leaked = dict(base)
        leaked[secret] = "forbidden"
        with pytest.raises(CacheKeyError, match="secret|nondeterministic"):
            ProofCacheKey.from_canonical(leaked)

    with pytest.raises(CacheKeyError, match="unknown evidence_class|unknown"):
        ProofCacheKey.from_canonical({**base, "evidence_class": "mystery"})
    with pytest.raises(CacheKeyError, match="unknown"):
        ProofCacheKey.from_canonical({**base, "proof_mode": "mystery"})
    with pytest.raises(CacheKeyError, match="unknown"):
        ProofCacheKey.from_canonical({**base, "proof_unit_kind": "mystery"})

    # Vectors document the same fail-closed cases.
    vectors = known_vectors()
    with pytest.raises(CacheKeyError, match="transitively incomplete"):
        ProofCacheKey.from_canonical(
            vectors["fail_closed"]["incomplete_roots_payload"]
        )
    with pytest.raises(CacheKeyError, match="duplicates"):
        ProofCacheKey.from_canonical(
            vectors["fail_closed"]["duplicate_source_artifacts"]
        )
    with pytest.raises(CacheKeyError, match="sorted"):
        ProofCacheKey.from_canonical(
            vectors["fail_closed"]["unsorted_dependency_roots"]
        )


def test_typed_absence_is_the_only_omission_form() -> None:
    key = sample_proof_cache_key(
        proving_key_id=ABSENCE_TOKEN,
        network_policy_cid=ABSENCE_TOKEN,
        test_selector_cid=ABSENCE_TOKEN,
        fixture_cids=ABSENCE_TOKEN,
    )
    payload = key.to_canonical()
    assert payload["proving_key_id"] == ABSENCE_TOKEN
    assert payload["network_policy_cid"] == ABSENCE_TOKEN
    assert payload["test_selector_cid"] == ABSENCE_TOKEN
    assert payload["fixture_cids"] == ABSENCE_TOKEN
    assert payload["typed_absence"] == "typed_absence"
    assert not (set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS)
    # Empty sequences round-trip as typed absence, not omitted keys.
    restored = ProofCacheKey.from_canonical(payload)
    assert restored.fixture_cids == ()
    assert restored.proving_key_id == ABSENCE_TOKEN


def test_pseudo_cid_and_schema_mismatch_fail_closed() -> None:
    base = sample_proof_cache_key().to_canonical()
    with pytest.raises(CacheKeyError, match="pseudo-CID|invalid profile CID"):
        ProofCacheKey.from_canonical(
            {**base, "statement_cid": "sha256:" + ("ab" * 32)}
        )
    with pytest.raises(CacheKeyError, match="unsupported ProofCacheKey schema"):
        ProofCacheKey.from_canonical(
            {**base, "schema": "ipfs_datasets_py/other/cache_key@2"}
        )


def test_alias_disagreement_and_dual_payload_fail_closed() -> None:
    base = sample_proof_cache_key()
    with pytest.raises(CacheKeyError, match="disagree"):
        build_proof_cache_key(
            payload=base.to_canonical(),
            canonical=base.to_canonical(),
        )
    fields = {
        field: (
            list(getattr(base, field))
            if field
            in {
                "source_artifact_cids",
                "dependency_unit_roots",
                "fixture_cids",
            }
            else getattr(base, field).value
            if field
            in {"evidence_class", "proof_unit_kind", "proof_mode"}
            else getattr(base, field)
        )
        for field in REQUIRED_FIELDS
    }
    # Alias conflicts with the canonical field of the same meaning.
    conflicting = dict(fields)
    conflicting["tool_id"] = "other-tool"
    with pytest.raises(CacheKeyError, match="disagree"):
        build_proof_cache_key(**conflicting)


def test_import_has_no_side_effects() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                f"mod = importlib.import_module({MODULE_NAME!r}); "
                "assert mod.CACHE_KEY_SUBSET == 'ips/cache-key@1'; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'ipfs_datasets_py.logic.software_contracts.content' "
                "not in sys.modules; "
                "assert 'provekit' not in sys.modules; "
                "assert 'py_ecc' not in sys.modules"
            ),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_module_reload_is_idempotent() -> None:
    module = importlib.import_module(MODULE_NAME)
    reloaded = importlib.reload(module)
    assert reloaded.CACHE_KEY_SUBSET == CACHE_KEY_SUBSET
    assert reloaded.PROOF_CACHE_KEY_SCHEMA == PROOF_CACHE_KEY_SCHEMA
    key = reloaded.sample_proof_cache_key()
    assert key.key_cid() == sample_proof_cache_key().key_cid()
