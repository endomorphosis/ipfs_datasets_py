"""UIR-002 contract tests for MCP-IDL identity interoperability.

Freezes the reviewed CIDv1/raw/sha2-256/base32 interface identity profile used
by UI/UX IR. Tests recompute preimages against accelerator registry
canonicalization and ``kubo_cid.cid_for_bytes`` without rewriting production
registries or silently normalizing legacy identifiers.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_accelerate_py.mcp_server.mcplusplus.idl_registry import (
    canonicalize_descriptor,
    compute_interface_cid,
)
from ipfs_accelerate_py.mcp_server.mcplusplus.kubo_cid import cid_for_bytes


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "v1"
    / "mcp_idl_identity_vectors.json"
)
CONTRACT_DOC_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "architecture"
    / "UI_UX_IR_MCP_IDL_IDENTITY.md"
)

PROFILE_NAME = "mcp-idl-interface-identity-v1"
CID_VERSION = 1
MULTICODEC_RAW = 0x55
MULTIHASH_SHA2_256 = 0x12
DIGEST_SIZE = 32
VERIFIED_CID_PREFIX = "bafkrei"
PLACEHOLDER_RE = re.compile(r"^cidv1-sha256-[0-9a-f]{64}$")
SHA256_ALIAS_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MOCK_BAFY_RE = re.compile(r"^bafy-mock-")


def _load_vectors() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def vectors() -> dict[str, Any]:
    return _load_vectors()


def _canonical_bytes(descriptor: Mapping[str, Any]) -> bytes:
    """Authoritative preimage bytes (matches registry canonicalize_descriptor)."""

    return json.dumps(
        dict(descriptor),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _independent_cid_v1_raw(data: bytes) -> str:
    """Independent CIDv1/raw/sha2-256/base32 constructor (no package import)."""

    digest = hashlib.sha256(bytes(data)).digest()
    assert len(digest) == DIGEST_SIZE
    cid_bytes = bytes([CID_VERSION, MULTICODEC_RAW, MULTIHASH_SHA2_256, DIGEST_SIZE]) + digest
    return "b" + base64.b32encode(cid_bytes).decode("ascii").rstrip("=").lower()


def _dag_pb_cid(data: bytes) -> str:
    """Mislabeled CIDv1/dag-pb twin used only for rejection evidence."""

    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    digest = hashlib.sha256(bytes(data)).digest()
    payload = bytes([CID_VERSION, 0x70, MULTIHASH_SHA2_256, DIGEST_SIZE]) + digest
    bits = 0
    val = 0
    out: list[str] = []
    for byte in payload:
        val = (val << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(alphabet[(val >> bits) & 31])
    if bits:
        out.append(alphabet[(val << (5 - bits)) & 31])
    return "b" + "".join(out)


def _verified_interface_cid(descriptor: Mapping[str, Any]) -> str:
    preimage = _canonical_bytes(descriptor)
    via_kubo = cid_for_bytes(preimage)
    via_independent = _independent_cid_v1_raw(preimage)
    assert via_kubo == via_independent
    return via_kubo


def _is_verified_interface_cid_string(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value != value.lower():
        return False
    if not value.startswith(VERIFIED_CID_PREFIX):
        return False
    if PLACEHOLDER_RE.match(value) or SHA256_ALIAS_RE.match(value) or MOCK_BAFY_RE.match(value):
        return False
    # Structural check: decode multibase base32 body and validate fixed header.
    if not value.startswith("b"):
        return False
    body = value[1:]
    # base32 decode with padding
    padded = body.upper() + ("=" * ((8 - (len(body) % 8)) % 8))
    try:
        raw = base64.b32decode(padded)
    except Exception:
        return False
    if len(raw) != 4 + DIGEST_SIZE:
        return False
    return (
        raw[0] == CID_VERSION
        and raw[1] == MULTICODEC_RAW
        and raw[2] == MULTIHASH_SHA2_256
        and raw[3] == DIGEST_SIZE
    )


def _verify_preimage(interface_cid: str, descriptor: Mapping[str, Any]) -> bool:
    if not _is_verified_interface_cid_string(interface_cid):
        return False
    return interface_cid == _verified_interface_cid(descriptor)


# ---------------------------------------------------------------------------
# Document and fixture presence
# ---------------------------------------------------------------------------


def test_contract_document_exists_and_names_interface() -> None:
    assert CONTRACT_DOC_PATH.is_file(), f"missing contract doc: {CONTRACT_DOC_PATH}"
    text = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    assert "MCPIDLIdentityInterop@1" in text
    assert "mcp-idl-interface-identity-v1" in text
    assert "CIDv1" in text and "raw" in text and "sha2-256" in text and "base32" in text
    assert "ui_ir_cid" in text and "interface_cid" in text and "legacy_alias" in text
    assert "mutable" in text.lower()
    assert "DAG-PB" in text or "dag-pb" in text


def test_vectors_fixture_schema(vectors: dict[str, Any]) -> None:
    assert vectors["schema"] == "ui-ux-ir/mcp-idl-identity-vectors@1"
    assert vectors["interface"] == "MCPIDLIdentityInterop@1"
    assert vectors["task_id"] == "UIR-002"
    assert vectors["profile"]["name"] == PROFILE_NAME
    assert vectors["profile"]["cid_version"] == CID_VERSION
    assert vectors["profile"]["multicodec"] == "raw"
    assert vectors["profile"]["multicodec_code"] == MULTICODEC_RAW
    assert vectors["profile"]["multihash"] == "sha2-256"
    assert vectors["profile"]["multihash_code"] == MULTIHASH_SHA2_256
    assert vectors["profile"]["digest_size"] == DIGEST_SIZE
    assert vectors["profile"]["multibase"] == "base32"
    assert set(vectors["identity_affecting_fields"]) == {
        "name",
        "namespace",
        "version",
        "methods",
        "errors",
        "requires",
        "compatibility",
        "semantic_tags",
        "observability",
        "interaction_patterns",
        "resource_cost_hints",
    }


def test_identity_domains_are_pairwise_nonequatable(vectors: dict[str, Any]) -> None:
    domains = {item["name"]: item for item in vectors["identity_domains"]}
    assert set(domains) == {"interface_cid", "ui_ir_cid", "legacy_alias"}
    for name, item in domains.items():
        assert item["equatable_to"] == []
        assert name not in item["equatable_to"]


# ---------------------------------------------------------------------------
# Golden preimage + verified interface_cid
# ---------------------------------------------------------------------------


def test_golden_preimage_matches_registry_canonicalize(vectors: dict[str, Any]) -> None:
    golden = vectors["golden"]
    descriptor = golden["descriptor"]
    via_registry = canonicalize_descriptor(descriptor)
    via_local = _canonical_bytes(descriptor)
    assert via_registry == via_local
    assert via_local.decode("utf-8") == golden["canonical_preimage_utf8"]
    assert hashlib.sha256(via_local).hexdigest() == golden["sha256_hex"]


def test_golden_interface_cid_is_cidv1_raw_sha2_256_base32(vectors: dict[str, Any]) -> None:
    golden = vectors["golden"]
    descriptor = golden["descriptor"]
    preimage = _canonical_bytes(descriptor)
    expected = golden["interface_cid"]

    assert expected.startswith(VERIFIED_CID_PREFIX)
    assert _is_verified_interface_cid_string(expected)
    assert cid_for_bytes(preimage) == expected
    assert _independent_cid_v1_raw(preimage) == expected
    assert _verify_preimage(expected, descriptor)

    # Optional multiformats cross-check when the package is installed.
    try:
        from multiformats import CID, multihash
    except Exception:
        pytest.skip("multiformats not installed")
    digest = multihash.digest(preimage, "sha2-256")
    assert str(CID("base32", 1, "raw", digest)) == expected
    decoded = CID.decode(expected)
    assert decoded.version == 1
    assert decoded.codec.name == "raw"
    assert decoded.hashfun.name == "sha2-256"


def test_interface_cid_must_not_appear_in_preimage(vectors: dict[str, Any]) -> None:
    descriptor = vectors["golden"]["descriptor"]
    assert "interface_cid" not in descriptor
    preimage_text = vectors["golden"]["canonical_preimage_utf8"]
    assert "interface_cid" not in preimage_text
    # Binding the CID into the descriptor would create a different identity.
    polluted = copy.deepcopy(descriptor)
    polluted["interface_cid"] = vectors["golden"]["interface_cid"]
    assert _verified_interface_cid(polluted) != vectors["golden"]["interface_cid"]


def test_key_order_independence(vectors: dict[str, Any]) -> None:
    golden = vectors["golden"]["descriptor"]
    order = vectors["key_order_independence"]["reordered_descriptor_keys"]
    reordered = {key: golden[key] for key in order}
    assert set(reordered) == set(golden)
    assert _verified_interface_cid(reordered) == vectors["key_order_independence"][
        "expected_interface_cid"
    ]
    assert _verified_interface_cid(reordered) == vectors["golden"]["interface_cid"]


# ---------------------------------------------------------------------------
# Identity-affecting field binding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_index", range(11))
def test_each_identity_affecting_field_changes_cid(
    vectors: dict[str, Any], case_index: int
) -> None:
    cases = vectors["field_sensitivity"]
    assert len(cases) == len(vectors["identity_affecting_fields"])
    case = cases[case_index]
    base = vectors["golden"]["descriptor"]
    mutated = copy.deepcopy(base)
    mutated[case["field"]] = case["mutated_value"]
    new_cid = _verified_interface_cid(mutated)
    assert new_cid == case["expected_interface_cid"]
    assert new_cid != vectors["golden"]["interface_cid"]
    assert _is_verified_interface_cid_string(new_cid)
    assert not _verify_preimage(vectors["golden"]["interface_cid"], mutated)


def test_resource_cost_hints_are_identity_affecting(vectors: dict[str, Any]) -> None:
    case = next(c for c in vectors["field_sensitivity"] if c["field"] == "resource_cost_hints")
    base = vectors["golden"]["descriptor"]
    mutated = copy.deepcopy(base)
    mutated["resource_cost_hints"] = case["mutated_value"]
    assert _verified_interface_cid(mutated) != vectors["golden"]["interface_cid"]


# ---------------------------------------------------------------------------
# Domain separation: never equate ui_ir_cid, interface_cid, legacy_alias
# ---------------------------------------------------------------------------


def test_ui_ir_cid_never_equals_interface_cid(vectors: dict[str, Any]) -> None:
    interface_cid = vectors["golden"]["interface_cid"]
    ui_preimage = vectors["domain_separation"]["ui_ir_preimage_utf8"].encode("utf-8")
    ui_ir_cid = cid_for_bytes(ui_preimage)
    assert ui_ir_cid == vectors["domain_separation"]["ui_ir_cid"]
    assert ui_ir_cid != interface_cid
    # Equality must never be used as an authority bridge.
    assert not (ui_ir_cid == interface_cid)


def test_legacy_aliases_never_equal_verified_interface_cid(vectors: dict[str, Any]) -> None:
    interface_cid = vectors["golden"]["interface_cid"]
    for sample in vectors["legacy_alias_samples"]:
        alias = sample["value"]
        assert sample["disposition"] == "legacy_alias"
        assert sample["verified_interface_cid"] is False
        assert alias != interface_cid
        assert not _is_verified_interface_cid_string(alias)
        # Even when the digest body matches, the wire form is not verified.
        if sample.get("shares_digest_with_golden"):
            assert vectors["golden"]["sha256_hex"] in alias


def test_three_way_domain_nonequivalence(vectors: dict[str, Any]) -> None:
    interface_cid = vectors["golden"]["interface_cid"]
    ui_ir_cid = vectors["domain_separation"]["ui_ir_cid"]
    aliases = [item["value"] for item in vectors["legacy_alias_samples"]]
    assert len({interface_cid, ui_ir_cid, *aliases}) == 2 + len(aliases)
    assert interface_cid not in aliases
    assert ui_ir_cid not in aliases
    assert interface_cid != ui_ir_cid


# ---------------------------------------------------------------------------
# Rejections: pseudo-CID, DAG-PB, mismatched preimage, mutable cache
# ---------------------------------------------------------------------------


def test_reject_pseudo_and_noncanonical_cids(vectors: dict[str, Any]) -> None:
    descriptor = vectors["golden"]["descriptor"]
    for case in vectors["rejection_cases"]:
        if case["kind"] not in {
            "pseudo_cid",
            "non_canonical_casing",
            "mislabeled_dag_pb",
        }:
            continue
        value = case["value"]
        assert not _is_verified_interface_cid_string(value) or case["kind"] == "mislabeled_dag_pb"
        if case["kind"] == "mislabeled_dag_pb":
            # DAG-PB twin decodes as a CIDv1 but wrong codec — not verified here.
            assert value != vectors["golden"]["interface_cid"]
            assert value.startswith("bafybei")
            assert not _verify_preimage(value, descriptor)
        else:
            assert not _verify_preimage(value, descriptor)


def test_reject_mislabeled_dag_pb_twin(vectors: dict[str, Any]) -> None:
    preimage = _canonical_bytes(vectors["golden"]["descriptor"])
    dagpb = _dag_pb_cid(preimage)
    case = next(c for c in vectors["rejection_cases"] if c["id"] == "reject.dag_pb_twin")
    assert dagpb == case["value"]
    assert dagpb != vectors["golden"]["interface_cid"]
    assert not _verify_preimage(dagpb, vectors["golden"]["descriptor"])
    # Same digest body, different multicodec → different authority.
    raw_digest = hashlib.sha256(preimage).digest()
    assert raw_digest.hex() == vectors["golden"]["sha256_hex"]


def test_reject_mismatched_preimage(vectors: dict[str, Any]) -> None:
    case = next(c for c in vectors["rejection_cases"] if c["id"] == "reject.mismatched_preimage")
    claimed = case["claimed_interface_cid"]
    descriptor = copy.deepcopy(vectors["golden"]["descriptor"])
    descriptor.update(case["descriptor_override"])
    assert claimed == vectors["golden"]["interface_cid"]
    assert not _verify_preimage(claimed, descriptor)
    assert _verified_interface_cid(descriptor) != claimed


def test_reject_stale_mutable_cache_behavior() -> None:
    """Record and reject datasets InterfaceDescriptor mutable-cache authority.

    This test intentionally exercises the existing incompatible surface and
    asserts that stale cache results must not be treated as verified identity.
    It does not rewrite the production class.
    """

    from ipfs_datasets_py.mcp_server.interface_descriptor import (
        InterfaceDescriptor,
        MethodSignature,
    )

    descriptor = InterfaceDescriptor(
        name="uir.demo.catalog.v1",
        namespace="uir.demo",
        version="1.0.0",
        methods=[MethodSignature(name="list_items")],
        requires=["mcp++/ucan"],
    )
    first = str(descriptor.interface_cid)
    # Mutate an identity-affecting field after the cache is populated.
    descriptor.name = "uir.demo.catalog.v2"
    second = str(descriptor.interface_cid)
    assert first == second, "expected stale mutable cache (incompatible inventory)"

    # Authoritative recomputation from an immutable snapshot must differ.
    snap_before = {
        "name": "uir.demo.catalog.v1",
        "namespace": "uir.demo",
        "version": "1.0.0",
        "methods": [{"name": "list_items", "input_schema": {}, "output_schema": {}, "errors": [], "streaming": False}],
        "errors": [],
        "requires": ["mcp++/ucan"],
        "compatibility": {"compatible_with": [], "supersedes": []},
        "semantic_tags": [],
        "observability": {"trace": False, "provenance": False},
        "interaction_patterns": {"request_response": True, "event_streams": False},
    }
    snap_after = copy.deepcopy(snap_before)
    snap_after["name"] = "uir.demo.catalog.v2"
    assert _verified_interface_cid(snap_before) != _verified_interface_cid(snap_after)
    # Cached value is non-authoritative relative to the mutated logical state.
    assert second == first
    assert not (first == _verified_interface_cid(snap_after))


def test_reject_datasets_dagpb_as_interface_authority(vectors: dict[str, Any]) -> None:
    from ipfs_datasets_py.mcp_server.interface_descriptor import compute_cid

    preimage = _canonical_bytes(vectors["golden"]["descriptor"])
    datasets_cid = compute_cid(preimage)
    assert datasets_cid.startswith("bafybei")
    assert datasets_cid != vectors["golden"]["interface_cid"]
    assert not _verify_preimage(datasets_cid, vectors["golden"]["descriptor"])


def test_reject_datasets_resource_cost_hints_exclusion() -> None:
    """Existing datasets canonical_bytes omits resource_cost_hints — incompatible."""

    from ipfs_datasets_py.mcp_server.interface_descriptor import (
        InterfaceDescriptor,
        MethodSignature,
    )

    a = InterfaceDescriptor(
        name="hints.demo",
        namespace="demo",
        version="1.0.0",
        methods=[MethodSignature(name="m")],
        resource_cost_hints={"tokens_per_call": 1},
    )
    b = InterfaceDescriptor(
        name="hints.demo",
        namespace="demo",
        version="1.0.0",
        methods=[MethodSignature(name="m")],
        resource_cost_hints={"tokens_per_call": 999},
    )
    # Incompatible surface: identity does not bind hints.
    assert a.canonical_bytes() == b.canonical_bytes()
    assert str(a.interface_cid) == str(b.interface_cid)

    # Profile requires binding when hints are claimed.
    snap_a = {
        "name": "hints.demo",
        "namespace": "demo",
        "version": "1.0.0",
        "methods": [{"name": "m"}],
        "resource_cost_hints": {"tokens_per_call": 1},
    }
    snap_b = {
        "name": "hints.demo",
        "namespace": "demo",
        "version": "1.0.0",
        "methods": [{"name": "m"}],
        "resource_cost_hints": {"tokens_per_call": 999},
    }
    assert _verified_interface_cid(snap_a) != _verified_interface_cid(snap_b)


# ---------------------------------------------------------------------------
# Incompatible inventory is recorded, not rewritten
# ---------------------------------------------------------------------------


def test_incompatible_inventory_is_complete_and_nonrewriting(vectors: dict[str, Any]) -> None:
    inventory = vectors["incompatible_inventory"]
    ids = {item["id"] for item in inventory}
    assert {
        "inv.accelerator_placeholder",
        "inv.ts_sha256_prefix",
        "inv.datasets_dagpb",
        "inv.datasets_mutable_cache",
        "inv.datasets_hints_excluded",
    }.issubset(ids)
    for item in inventory:
        assert item["rewrite_in_uir_002"] is False
        assert "disposition" in item
        assert item["path"]


def test_accelerator_placeholder_is_recorded_not_equated(vectors: dict[str, Any]) -> None:
    descriptor = vectors["golden"]["descriptor"]
    placeholder = compute_interface_cid(descriptor)
    assert PLACEHOLDER_RE.match(placeholder)
    assert placeholder == (
        "cidv1-sha256-" + vectors["golden"]["sha256_hex"]
    )
    assert placeholder != vectors["golden"]["interface_cid"]
    assert not _is_verified_interface_cid_string(placeholder)
    # Digest agreement is acknowledged; wire authority is not.
    assert vectors["golden"]["sha256_hex"] in placeholder


def test_explicit_rejections_cover_acceptance_criteria(vectors: dict[str, Any]) -> None:
    rejections = set(vectors["explicit_rejections"])
    assert "ui_ir_cid_equals_interface_cid" in rejections
    assert "interface_cid_equals_legacy_alias" in rejections
    assert "mutable_cache_identity_as_authority" in rejections
    assert "mislabeled_dag_pb_as_interface_authority" in rejections
    assert "silent_rewrite_of_incompatible_fixtures" in rejections
    assert "pseudo_cid_as_verified_interface_cid" in rejections
    assert "mismatched_preimage_as_identity" in rejections


def test_registry_canonicalize_is_interface_preimage_authority(vectors: dict[str, Any]) -> None:
    """idl_registry.canonicalize_descriptor is the JSON preimage authority.

    Verified CID construction for the frozen profile uses kubo_cid over those
    bytes. compute_interface_cid remains a recorded migration placeholder.
    """

    descriptor = vectors["golden"]["descriptor"]
    preimage = canonicalize_descriptor(descriptor)
    assert cid_for_bytes(preimage) == vectors["golden"]["interface_cid"]
    assert compute_interface_cid(descriptor).startswith("cidv1-sha256-")
