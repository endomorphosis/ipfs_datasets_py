"""Cross-language GUI identity conformance vectors (VGO-075)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.gui_optimizer.identity import (
    CANONICAL_JSON_PROFILE,
    CID_VERSION,
    DOMAIN_APPLICATION,
    DOMAIN_COMPONENT_VERSION,
    DOMAIN_SCREEN,
    DOMAIN_STABLE_IDENTITY,
    IDENTITY_PROFILE_NAME,
    MULTIBASE_NAME,
    MULTICODEC_CODE,
    MULTICODEC_NAME,
    MULTIHASH_CODE,
    MULTIHASH_NAME,
    GuiCanonicalIdentity,
    GuiIdentityError,
    application_identity,
    artifact_digest,
    canonical_identity,
    canonical_json_bytes,
    cid_v1,
    compile_component_version,
    component_version_identity,
    parse_cid_v1,
    screen_identity,
    sha256_digest,
    stable_identity_record,
)
from ipfs_datasets_py.logic.gui_optimizer.models import (
    GuiApplicationIdentity,
    GuiScreenIdentity,
    UiBaseline,
    UiComponentIdentity,
    UiComponentVersion,
)
from ipfs_datasets_py.logic.gui_optimizer.receipts import (
    DOMAIN_IMPROVEMENT_RECEIPT,
    improvement_receipt_identity,
)
from ipfs_datasets_py.logic.gui_optimizer.schema import (
    GUI_APPLICATION_IDENTITY_SCHEMA,
    GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    GUI_SCREEN_IDENTITY_SCHEMA,
    UI_BASELINE_SCHEMA,
    UI_COMPONENT_IDENTITY_SCHEMA,
    UI_COMPONENT_VERSION_SCHEMA,
)

DOMAIN_BASELINE = "gui.ui-baseline"
VECTORS_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "gui_optimizer"
    / "identity-vectors.json"
)
KIND_TO_SLOT = {
    "application": "application",
    "screen": "screen",
    "stable": "stable",
    "component_version": "version",
    "baseline": "baseline",
    "receipt": "receipt",
}


def _load_vectors() -> dict[str, Any]:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _set_path(value: Any, path: list[Any], replacement: Any) -> Any:
    clone = deepcopy(value)
    cursor = clone
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = deepcopy(replacement)
    return clone


def _identity_text(identity: GuiCanonicalIdentity) -> str:
    return identity.canonical_bytes.decode("utf-8")


def _assert_real_identity(
    identity: GuiCanonicalIdentity,
    *,
    domain: str,
    schema_version: str,
    expected_bytes: str | None = None,
    expected_digest: str | None = None,
    expected_cid: str | None = None,
) -> None:
    profile = getattr(identity, "profile", None)
    if profile is not None:
        assert profile == IDENTITY_PROFILE_NAME
    assert identity.domain == domain
    assert identity.schema_version == schema_version
    if expected_bytes is not None:
        assert _identity_text(identity) == expected_bytes
    assert identity.digest == sha256_digest(identity.canonical_bytes)
    parsed = parse_cid_v1(identity.cid)
    assert parsed["version"] == CID_VERSION
    assert parsed["multicodec"] == MULTICODEC_NAME
    assert parsed["multicodec_code"] == MULTICODEC_CODE
    assert parsed["multihash"] == MULTIHASH_NAME
    assert parsed["multihash_code"] == MULTIHASH_CODE
    assert parsed["digest_label"] == identity.digest
    recomputed = identity.rehash()
    assert recomputed.cid == identity.cid
    assert recomputed.digest == identity.digest
    if expected_digest is not None:
        assert identity.digest == expected_digest
    if expected_cid is not None:
        assert identity.cid == expected_cid


def _canonical_for(
    kind: str,
    payload: Any,
    *,
    domain: str,
    schema_version: str,
) -> GuiCanonicalIdentity:
    if kind == "canonical":
        return canonical_identity(
            payload, domain=domain, schema_version=schema_version
        )
    if kind == "artifact":
        return artifact_digest(payload, domain=domain)
    if kind == "application":
        return application_identity(GuiApplicationIdentity.from_dict(payload))
    if kind == "screen":
        return screen_identity(GuiScreenIdentity.from_dict(payload))
    if kind == "stable":
        return stable_identity_record(UiComponentIdentity.from_dict(payload))
    if kind == "component_version":
        return component_version_identity(UiComponentVersion.from_dict(payload))
    if kind == "baseline":
        return canonical_identity(
            UiBaseline.from_dict(payload).to_dict(),
            domain=DOMAIN_BASELINE,
            schema_version=UI_BASELINE_SCHEMA,
        )
    if kind == "receipt":
        return improvement_receipt_identity(payload)
    raise AssertionError(f"unsupported identity kind {kind!r}")


def _compile_version(vector: dict[str, Any]) -> UiComponentVersion:
    return compile_component_version(
        UiComponentIdentity.from_dict(vector["stable_identity"]),
        vector["material"],
        extractor_version=vector["extractor_version"],
    )


def _version_identity(vector: dict[str, Any]) -> GuiCanonicalIdentity:
    return component_version_identity(_compile_version(vector))


def _build_suite(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id = {item["id"]: item for item in doc["identity_vectors"]}
    version = by_id["version-goal-form"]
    compiled = _compile_version(version)
    return {
        "application": {
            "kind": "application",
            "payload": deepcopy(by_id["application-console"]["payload"]),
            "identity": _canonical_for(
                "application",
                by_id["application-console"]["payload"],
                domain=DOMAIN_APPLICATION,
                schema_version=GUI_APPLICATION_IDENTITY_SCHEMA,
            ),
        },
        "screen": {
            "kind": "screen",
            "payload": deepcopy(by_id["screen-console"]["payload"]),
            "identity": _canonical_for(
                "screen",
                by_id["screen-console"]["payload"],
                domain=DOMAIN_SCREEN,
                schema_version=GUI_SCREEN_IDENTITY_SCHEMA,
            ),
        },
        "stable": {
            "kind": "stable",
            "payload": deepcopy(by_id["stable-goal-form"]["payload"]),
            "identity": _canonical_for(
                "stable",
                by_id["stable-goal-form"]["payload"],
                domain=DOMAIN_STABLE_IDENTITY,
                schema_version=UI_COMPONENT_IDENTITY_SCHEMA,
            ),
        },
        "version": {
            "kind": "component_version",
            "payload": compiled.to_dict(),
            "identity": component_version_identity(compiled),
            "facets": {
                "accessibility_digest": compiled.accessibility_digest,
                "actions_digest": compiled.actions_digest,
                "handlers_digest": compiled.handlers_digest,
                "localization_digest": compiled.localization_digest,
                "props_digest": compiled.props_digest,
                "state_digest": compiled.state_digest,
                "structure_digest": compiled.structure_digest,
                "styles_digest": compiled.styles_digest,
            },
            "material": deepcopy(version["material"]),
            "stable_identity": deepcopy(version["stable_identity"]),
            "extractor_version": version["extractor_version"],
        },
        "baseline": {
            "kind": "baseline",
            "payload": deepcopy(by_id["baseline-console"]["payload"]),
            "identity": _canonical_for(
                "baseline",
                by_id["baseline-console"]["payload"],
                domain=DOMAIN_BASELINE,
                schema_version=UI_BASELINE_SCHEMA,
            ),
        },
        "receipt": {
            "kind": "receipt",
            "payload": deepcopy(by_id["receipt-accepted"]["payload"]),
            "identity": _canonical_for(
                "receipt",
                by_id["receipt-accepted"]["payload"],
                domain=DOMAIN_IMPROVEMENT_RECEIPT,
                schema_version=GUI_IMPROVEMENT_RECEIPT_SCHEMA,
            ),
        },
    }


def _recompute_slot(slot: str, payload: Any, suite: dict[str, dict[str, Any]]) -> Any:
    if slot == "version":
        compiled = compile_component_version(
            UiComponentIdentity.from_dict(suite["version"]["stable_identity"]),
            payload,
            extractor_version=suite["version"]["extractor_version"],
        )
        return compiled, component_version_identity(compiled)
    kind = suite[slot]["kind"]
    domain = {
        "application": DOMAIN_APPLICATION,
        "screen": DOMAIN_SCREEN,
        "stable": DOMAIN_STABLE_IDENTITY,
        "baseline": DOMAIN_BASELINE,
        "receipt": DOMAIN_IMPROVEMENT_RECEIPT,
    }[slot]
    schema = {
        "application": GUI_APPLICATION_IDENTITY_SCHEMA,
        "screen": GUI_SCREEN_IDENTITY_SCHEMA,
        "stable": UI_COMPONENT_IDENTITY_SCHEMA,
        "baseline": UI_BASELINE_SCHEMA,
        "receipt": GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    }[slot]
    return payload, _canonical_for(kind, payload, domain=domain, schema_version=schema)


def _negative_input(case: dict[str, Any]) -> Any:
    recipe = case.get("input") or {}
    kind = recipe.get("type")
    if kind == "number":
        return recipe["value"]
    if kind == "surrogate_string":
        return "".join(chr(unit) for unit in recipe["units"])
    if kind == "nfc_collision":
        return {"é": 1, "e\u0301": 2}
    raise AssertionError(f"unsupported negative input {recipe!r}")


def test_fixture_declares_closed_conformance_profile() -> None:
    doc = _load_vectors()
    assert doc["interface"] == "GuiIdentityConformanceVectors@1"
    assert doc["schema_version"] == "gui-identity-conformance-vectors/v1"
    assert doc["identity_profile"] == IDENTITY_PROFILE_NAME
    assert doc["canonicalization"] == CANONICAL_JSON_PROFILE
    profile = doc["cid_profile"]
    assert profile["cid_version"] == CID_VERSION
    assert profile["multicodec"] == MULTICODEC_NAME
    assert profile["multicodec_code"] == MULTICODEC_CODE
    assert profile["multihash"] == MULTIHASH_NAME
    assert profile["multihash_code"] == MULTIHASH_CODE
    assert profile["multibase"] == MULTIBASE_NAME
    assert doc["domains"]["application"] == DOMAIN_APPLICATION
    assert doc["domains"]["screen"] == DOMAIN_SCREEN
    assert doc["domains"]["stable"] == DOMAIN_STABLE_IDENTITY
    assert doc["domains"]["component_version"] == DOMAIN_COMPONENT_VERSION
    assert doc["domains"]["receipt"] == DOMAIN_IMPROVEMENT_RECEIPT
    assert doc["domains"]["baseline"] == DOMAIN_BASELINE
    assert set(KIND_TO_SLOT) <= {
        item["kind"] for item in doc["identity_vectors"]
    } | {"canonical", "artifact"}


@pytest.mark.parametrize(
    "vector",
    _load_vectors()["profile_vectors"],
    ids=lambda item: item["id"],
)
def test_profile_vectors_lock_canonical_bytes_and_real_cids(
    vector: dict[str, Any],
) -> None:
    identity = _canonical_for(
        vector["kind"],
        vector["payload"],
        domain=vector["domain"],
        schema_version=vector["schema_version"],
    )
    if "payload_bytes" in vector:
        assert canonical_json_bytes(vector["payload"]).decode("utf-8") == vector[
            "payload_bytes"
        ]
    _assert_real_identity(
        identity,
        domain=vector["domain"],
        schema_version=vector["schema_version"],
        expected_bytes=vector.get("canonical_bytes"),
        expected_digest=vector.get("digest"),
        expected_cid=vector.get("cid"),
    )
    shuffled = vector.get("shuffled_payload")
    if shuffled is not None:
        again = _canonical_for(
            vector["kind"],
            shuffled,
            domain=vector["domain"],
            schema_version=vector["schema_version"],
        )
        assert again.cid == identity.cid
        assert again.digest == identity.digest
        assert again.canonical_bytes == identity.canonical_bytes


@pytest.mark.parametrize(
    "vector",
    [item for item in _load_vectors()["identity_vectors"] if item["kind"] != "component_version"],
    ids=lambda item: item["id"],
)
def test_identity_vectors_match_expected_canonical_bytes(
    vector: dict[str, Any],
) -> None:
    identity = _canonical_for(
        vector["kind"],
        vector["payload"],
        domain=vector["domain"],
        schema_version=vector["schema_version"],
    )
    _assert_real_identity(
        identity,
        domain=vector["domain"],
        schema_version=vector["schema_version"],
        expected_bytes=vector.get("canonical_bytes"),
        expected_digest=vector.get("digest"),
        expected_cid=vector.get("cid"),
    )


def test_component_version_recipe_compiles_to_real_identity() -> None:
    doc = _load_vectors()
    vector = next(
        item for item in doc["identity_vectors"] if item["kind"] == "component_version"
    )
    compiled = _compile_version(vector)
    identity = component_version_identity(compiled)
    _assert_real_identity(
        identity,
        domain=DOMAIN_COMPONENT_VERSION,
        schema_version=UI_COMPONENT_VERSION_SCHEMA,
    )
    again = _version_identity(vector)
    assert again.cid == identity.cid
    assert compiled.stable_identity.to_dict() == vector["stable_identity"]


def test_known_hello_cid_vector() -> None:
    doc = _load_vectors()
    known = doc["known_cid"]
    encoded = known["preimage"].encode("utf-8")
    assert cid_v1(encoded) == known["cid"]
    parsed = parse_cid_v1(known["cid"])
    assert parsed["digest_label"] == sha256_digest(encoded)


@pytest.mark.parametrize(
    "pair",
    _load_vectors()["baseline_pairs"],
    ids=lambda item: item["id"],
)
def test_identical_sources_and_scenarios_share_baseline_identity(
    pair: dict[str, Any],
) -> None:
    left = _canonical_for(
        "baseline",
        pair["left"],
        domain=DOMAIN_BASELINE,
        schema_version=UI_BASELINE_SCHEMA,
    )
    right = _canonical_for(
        "baseline",
        pair["right"],
        domain=DOMAIN_BASELINE,
        schema_version=UI_BASELINE_SCHEMA,
    )
    _assert_real_identity(
        left, domain=DOMAIN_BASELINE, schema_version=UI_BASELINE_SCHEMA
    )
    _assert_real_identity(
        right, domain=DOMAIN_BASELINE, schema_version=UI_BASELINE_SCHEMA
    )
    if pair["expect_identical"]:
        assert left.cid == right.cid
        assert left.digest == right.digest
        assert left.canonical_bytes == right.canonical_bytes
    else:
        assert left.cid != right.cid
        assert left.digest != right.digest
        assert left.canonical_bytes != right.canonical_bytes


@pytest.mark.parametrize(
    "entry",
    _load_vectors()["mutation_matrix"],
    ids=lambda item: item["id"],
)
def test_bound_mutations_change_only_the_declared_identity(
    entry: dict[str, Any],
) -> None:
    doc = _load_vectors()
    suite = _build_suite(doc)
    mutation = entry["mutation"]
    target = mutation["target"]
    slot = "version" if target == "material" else target
    source = (
        suite["version"]["material"] if target == "material" else suite[slot]["payload"]
    )
    mutated = _set_path(source, list(mutation["path"]), mutation["value"])
    new_payload, new_identity = _recompute_slot(slot, mutated, suite)
    before = suite[slot]["identity"]
    changed = new_identity.cid != before.cid
    if slot in entry["expect_changed"]:
        assert changed, f"{entry['id']} should change {slot} identity"
    else:
        assert not changed, f"{entry['id']} should not change {slot} identity"
        assert new_identity.digest == before.digest
    for other in entry["expect_unchanged"]:
        other_identity = suite[other]["identity"]
        if other == slot:
            assert other_identity.cid == new_identity.cid
            continue
        assert other_identity.cid == suite[other]["identity"].cid
        assert other_identity.digest == suite[other]["identity"].digest
    if target == "material":
        compiled = new_payload
        for facet in entry["changed_facets"]:
            assert getattr(compiled, facet) != suite["version"]["facets"][facet]
        for facet in entry["unchanged_facets"]:
            assert getattr(compiled, facet) == suite["version"]["facets"][facet]
        assert compiled.stable_identity.to_dict() == suite["stable"]["payload"]


@pytest.mark.parametrize(
    "case",
    _load_vectors()["negative_cases"],
    ids=lambda item: item["id"],
)
def test_negative_vectors_fail_closed(case: dict[str, Any]) -> None:
    substring = case.get("error_substring") or None
    if case["kind"] == "canonical_json":
        value = _negative_input(case)
        with pytest.raises(GuiIdentityError, match=substring):
            canonical_json_bytes(value)
        return
    if case["kind"] == "canonical_identity":
        with pytest.raises(GuiIdentityError, match=substring):
            canonical_identity(
                case["payload"],
                domain=case["domain"],
                schema_version=case["schema_version"],
            )
        return
    if case["kind"] == "parse_cid":
        with pytest.raises(GuiIdentityError):
            parse_cid_v1(case["cid"])
        return
    raise AssertionError(f"unsupported negative case {case['kind']!r}")


@pytest.mark.parametrize(
    "entry",
    _load_vectors()["domain_separation"],
    ids=lambda item: item["id"],
)
def test_domain_separation_changes_identity(entry: dict[str, Any]) -> None:
    left = canonical_identity(
        entry["payload"],
        domain=entry["left_domain"],
        schema_version=entry["schema_version"],
    )
    right = canonical_identity(
        entry["payload"],
        domain=entry["right_domain"],
        schema_version=entry["schema_version"],
    )
    assert left.cid != right.cid
    assert left.digest != right.digest
    assert left.canonical_bytes != right.canonical_bytes
    _assert_real_identity(
        left,
        domain=entry["left_domain"],
        schema_version=entry["schema_version"],
    )
    _assert_real_identity(
        right,
        domain=entry["right_domain"],
        schema_version=entry["schema_version"],
    )
