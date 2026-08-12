"""Unit tests for GUI optimizer canonical identity (VGO-010)."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from ipfs_datasets_py.logic.gui_optimizer.identity import (
    CANONICAL_JSON_PROFILE,
    DOMAIN_ARTIFACT,
    DOMAIN_COMPONENT_VERSION,
    DOMAIN_STABLE_IDENTITY,
    GUI_ARTIFACT_DIGEST_INTERFACE,
    GUI_CANONICAL_IDENTITY_INTERFACE,
    IDENTITY_PROFILE,
    IDENTITY_PROFILE_NAME,
    MAX_SAFE_INTEGER,
    MULTICODEC_CODE,
    MULTIHASH_CODE,
    UI_COMPONENT_VERSION_COMPILER_INTERFACE,
    GuiIdentityError,
    artifact_digest,
    build_stable_identity,
    canonical_identity,
    canonical_json_bytes,
    cid_v1,
    compile_component_version,
    component_version_identity,
    create_component_version_compiler,
    facet_digest,
    identity_preimage,
    normalize_material,
    parse_cid_v1,
    sha256_digest,
    stable_identity_record,
    verify_identity,
)
from ipfs_datasets_py.logic.gui_optimizer.schema import (
    UI_COMPONENT_IDENTITY_SCHEMA,
    UI_COMPONENT_VERSION_SCHEMA,
)

# ---------------------------------------------------------------------------
# Golden vectors (shared with TypeScript identity.test.ts)
# ---------------------------------------------------------------------------

GOLDEN_PAYLOAD = {
    "component": "ConsoleRoot",
    "kind": "screen",
    "tags": ["primary", "workspace"],
    "title": "Cafe\u0301",
}

GOLDEN_DOMAIN = "gui.test-vector"
GOLDEN_SCHEMA = "gui-test-vector/v1"

# Computed against the closed profile; tests lock these exact values.
GOLDEN_PAYLOAD_BYTES = (
    b'{"component":"ConsoleRoot","kind":"screen",'
    b'"tags":["primary","workspace"],"title":"Caf\xc3\xa9"}'
)

# Literal cross-runtime contract.  Keep byte-for-byte identical to the vector
# in swissknife/test/unit/services/gui-optimizer/identity.test.ts.
CROSS_RUNTIME_DOMAIN = "gui.cross-runtime-vector"
CROSS_RUNTIME_SCHEMA = "gui-cross-runtime-vector/v1"
CROSS_RUNTIME_PAYLOAD = {
    "astral_and_bmp": {"\ue000": "bmp", "\U00010000": "astral"},
    "boolean_false": False,
    "boolean_true": True,
    "float_one": 1.0,
    "negative_zero": -0.0,
    "safe_integer": 9_007_199_254_740_991,
    "small_exponent": 1e-7,
    "smallest_subnormal": 5e-324,
}
CROSS_RUNTIME_PAYLOAD_JSON = (
    '{"astral_and_bmp":{"\ue000":"bmp","\U00010000":"astral"},'
    '"boolean_false":false,"boolean_true":true,"float_one":1,'
    '"negative_zero":0,"safe_integer":9007199254740991,'
    '"small_exponent":0.0000001,"smallest_subnormal":'
    "0.0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000005}"
)
CROSS_RUNTIME_PREIMAGE_JSON = (
    '{"canonicalization":"gui-optimizer-canonical-json/v1",'
    '"domain":"gui.cross-runtime-vector",'
    '"identity_profile":"gui-optimizer-canonical-identity/v1","payload":'
    + CROSS_RUNTIME_PAYLOAD_JSON
    + ',"schema_version":"gui-cross-runtime-vector/v1"}'
)
CROSS_RUNTIME_DIGEST = (
    "sha256:ca283ecb68a9e75a2b143628f2c98888b749fe0f7fbfc269341d9549c180b93c"
)
CROSS_RUNTIME_CID = (
    "bafkreigkfa7mw2fj45ncwfbwfdzmtceiw5e74d37x7bgsna5sve4dafzhq"
)

ARTIFACT_VECTOR_DOMAIN = "gui.artifact-vector"
ARTIFACT_VECTOR_MATERIAL = {
    "facet": None,
    "label": "\u0085value\u0085",
    "route_path": "/docs/start",
}
ARTIFACT_VECTOR_PREIMAGE = (
    '{"canonicalization":"gui-optimizer-canonical-json/v1",'
    '"domain":"gui.artifact-vector",'
    '"identity_profile":"gui-optimizer-canonical-identity/v1",'
    '"payload":{"facet":null,"label":"value",'
    '"route_path":"/docs/start"},'
    '"schema_version":"gui-artifact-digest/v1"}'
)
ARTIFACT_VECTOR_DIGEST = (
    "sha256:491a93ed0b5c2ee1a60a450cf6a65c331cbdf818541e3d3f5c90f0bd15aa80b6"
)
ARTIFACT_VECTOR_CID = (
    "bafkreicjdkj62c24f3q2mcsfbt3kmxbtds67qgcudy6t6xeq6c6rlkuawy"
)

TRIM_VECTOR_DOMAIN = "\u001cgui.trim\ufeff"
TRIM_VECTOR_PREIMAGE = (
    '{"canonicalization":"gui-optimizer-canonical-json/v1",'
    '"domain":"\\u001cgui.trim\ufeff",'
    '"identity_profile":"gui-optimizer-canonical-identity/v1",'
    '"payload":{},"schema_version":"trim-vector/v1"}'
)
TRIM_VECTOR_DIGEST = (
    "sha256:d7bddc07adbab269eb9cb770b95b6552bb01d348fb8ab3efe088478a1a013e10"
)
TRIM_VECTOR_CID = (
    "bafkreigxxxoapln2wju6xhfxoc4vwzksxma5gsh3rkz67yeii6fbuaj6ca"
)


def _expected_preimage() -> bytes:
    return identity_preimage(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )


def _expected_digest_and_cid() -> tuple[str, str]:
    preimage = _expected_preimage()
    raw = hashlib.sha256(preimage).digest()
    return f"sha256:{raw.hex()}", cid_v1(preimage)


# ---------------------------------------------------------------------------
# Profile / primitives
# ---------------------------------------------------------------------------


def test_identity_profile_is_fixed_and_domain_ready() -> None:
    assert IDENTITY_PROFILE_NAME == "gui-optimizer-canonical-identity/v1"
    assert CANONICAL_JSON_PROFILE == "gui-optimizer-canonical-json/v1"
    assert IDENTITY_PROFILE.multicodec == "raw"
    assert IDENTITY_PROFILE.multihash == "sha2-256"
    assert MULTICODEC_CODE == 0x55
    assert MULTIHASH_CODE == 0x12
    descriptor = IDENTITY_PROFILE.to_dict()
    assert descriptor["name"] == IDENTITY_PROFILE_NAME
    assert descriptor["canonicalization"] == CANONICAL_JSON_PROFILE


def test_canonical_json_normalizes_nfc_and_sorts_keys() -> None:
    encoded = canonical_json_bytes(
        {"b": 1, "a": 2, "title": "Cafe\u0301"}
    )
    assert encoded == b'{"a":2,"b":1,"title":"Caf\xc3\xa9"}'


def test_canonical_json_rejects_non_json_and_key_collisions() -> None:
    with pytest.raises(GuiIdentityError):
        canonical_json_bytes({"x": {1, 2}})
    with pytest.raises(GuiIdentityError):
        canonical_json_bytes(float("nan"))
    with pytest.raises(GuiIdentityError, match="collide"):
        canonical_json_bytes({"é": 1, "e\u0301": 2})


def test_literal_cross_runtime_json_digest_and_cid_vector() -> None:
    encoded = canonical_json_bytes(CROSS_RUNTIME_PAYLOAD)
    assert encoded.decode("utf-8") == CROSS_RUNTIME_PAYLOAD_JSON
    identity = canonical_identity(
        CROSS_RUNTIME_PAYLOAD,
        domain=CROSS_RUNTIME_DOMAIN,
        schema_version=CROSS_RUNTIME_SCHEMA,
    )
    assert identity.canonical_bytes.decode("utf-8") == CROSS_RUNTIME_PREIMAGE_JSON
    assert identity.digest == CROSS_RUNTIME_DIGEST
    assert identity.cid == CROSS_RUNTIME_CID
    # Exact bool/int/float distinctions and negative-zero collapse.
    assert canonical_json_bytes([False, 0, True, 1, 1.0, -0.0]) == (
        b"[false,0,true,1,1,0]"
    )


@pytest.mark.parametrize(
    "value",
    [
        MAX_SAFE_INTEGER + 1,
        -(MAX_SAFE_INTEGER + 1),
        float(MAX_SAFE_INTEGER + 1),
        1e20,
        float.fromhex("0x1.fffffffffffffp+1023"),
    ],
)
def test_cross_runtime_numeric_domain_rejects_unsafe_integers(
    value: int | float,
) -> None:
    with pytest.raises(GuiIdentityError, match="safe-integer"):
        canonical_json_bytes(value)
    with pytest.raises(GuiIdentityError, match="safe-integer"):
        normalize_material({"nested": [value]})


def test_unicode_scalar_and_recursive_collision_policy_fails_closed() -> None:
    for value in ("\ud800", {"\udc00": "value"}, {"nested": ["\udfff"]}):
        with pytest.raises(GuiIdentityError, match="unpaired Unicode surrogate"):
            canonical_json_bytes(value)
        with pytest.raises(GuiIdentityError, match="unpaired Unicode surrogate"):
            normalize_material(value)

    collision = {"outer": {"é": 1, "e\u0301": 2}}
    with pytest.raises(GuiIdentityError, match="collide"):
        canonical_json_bytes(collision)
    with pytest.raises(GuiIdentityError, match="collide"):
        normalize_material(collision)

    with pytest.raises(GuiIdentityError, match="unpaired Unicode surrogate"):
        canonical_identity(
            {}, domain="gui.\ud800", schema_version=CROSS_RUNTIME_SCHEMA
        )


def test_literal_cross_runtime_trim_policy_vector() -> None:
    # U+0085 is profile whitespace; U+001C and U+FEFF are not. This must not
    # inherit Python ``str.strip`` behavior.
    assert normalize_material("\u0085value\u0085") == "value"
    assert normalize_material("\u001cvalue\ufeff") == "\u001cvalue\ufeff"
    with pytest.raises(GuiIdentityError, match="surrounding whitespace"):
        canonical_identity(
            {}, domain="\u0085gui.trim", schema_version="trim-vector/v1"
        )
    identity = canonical_identity(
        {}, domain=TRIM_VECTOR_DOMAIN, schema_version="trim-vector/v1"
    )
    assert identity.canonical_bytes.decode("utf-8") == TRIM_VECTOR_PREIMAGE
    assert identity.digest == TRIM_VECTOR_DIGEST
    assert identity.cid == TRIM_VECTOR_CID


def test_cid_v1_raw_sha256_base32_for_hello() -> None:
    # Known multiformats vector for raw CIDv1 of b"hello".
    assert cid_v1(b"hello") == (
        "bafkreibm6jg3ux5qumhcn2b3flc3tyu6dmlb4xa7u5bf44yegnrjhc4yeq"
    )
    parsed = parse_cid_v1(cid_v1(b"hello"))
    assert parsed["version"] == 1
    assert parsed["multicodec"] == "raw"
    assert parsed["multihash"] == "sha2-256"
    assert len(parsed["digest"]) == 64


def test_parse_cid_rejects_malformed() -> None:
    with pytest.raises(GuiIdentityError):
        parse_cid_v1("not-a-cid")
    with pytest.raises(GuiIdentityError):
        parse_cid_v1("bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi")


# ---------------------------------------------------------------------------
# Golden identity vectors
# ---------------------------------------------------------------------------


def test_golden_canonical_bytes_digest_and_cid() -> None:
    assert canonical_json_bytes(GOLDEN_PAYLOAD) == GOLDEN_PAYLOAD_BYTES
    identity = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )
    expected_digest, expected_cid = _expected_digest_and_cid()
    assert identity.canonical_bytes == _expected_preimage()
    assert identity.digest == expected_digest
    assert identity.cid == expected_cid
    assert identity.profile == IDENTITY_PROFILE_NAME
    assert identity.domain == GOLDEN_DOMAIN
    assert identity.interface == GUI_CANONICAL_IDENTITY_INTERFACE
    assert identity.identifier == expected_cid
    assert identity.hexdigest == expected_digest.removeprefix("sha256:")
    # Key order independence.
    shuffled = {
        "title": "Café",
        "tags": ["primary", "workspace"],
        "kind": "screen",
        "component": "ConsoleRoot",
    }
    again = canonical_identity(
        shuffled, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )
    assert again.cid == identity.cid
    assert again.digest == identity.digest


def test_domain_separation_changes_identity() -> None:
    left = canonical_identity(
        GOLDEN_PAYLOAD, domain="gui.domain-a", schema_version=GOLDEN_SCHEMA
    )
    right = canonical_identity(
        GOLDEN_PAYLOAD, domain="gui.domain-b", schema_version=GOLDEN_SCHEMA
    )
    assert left.cid != right.cid
    assert left.digest != right.digest
    assert left.canonical_bytes != right.canonical_bytes


def test_schema_version_separation_changes_identity() -> None:
    left = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version="v1"
    )
    right = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version="v2"
    )
    assert left.cid != right.cid


def test_identity_rehashes_from_retained_bytes() -> None:
    identity = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )
    recomputed = identity.rehash()
    assert recomputed.cid == identity.cid
    assert recomputed.digest == identity.digest
    verified = verify_identity(identity, GOLDEN_PAYLOAD)
    assert verified.cid == identity.cid


def test_verify_identity_rejects_tamper() -> None:
    identity = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )
    with pytest.raises(GuiIdentityError):
        verify_identity(identity, {**GOLDEN_PAYLOAD, "kind": "dialog"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile", "forged-profile/v1"),
        ("interface", "ForgedIdentity@1"),
        ("wire_schema_version", "forged-identity/v1"),
        ("domain", "gui.forged-domain"),
        ("schema_version", "forged-schema/v1"),
    ],
)
def test_verify_identity_rejects_forged_claimed_metadata(
    field: str, value: str
) -> None:
    identity = canonical_identity(
        GOLDEN_PAYLOAD, domain=GOLDEN_DOMAIN, schema_version=GOLDEN_SCHEMA
    )
    forged = replace(identity, **{field: value})
    with pytest.raises(GuiIdentityError):
        verify_identity(forged, GOLDEN_PAYLOAD)


# ---------------------------------------------------------------------------
# Stable identity (line movement / unrelated edits)
# ---------------------------------------------------------------------------


def test_stable_identity_ignores_line_numbers() -> None:
    identity = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.ConsoleRoot",
        component_kind="screen",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    # Spans are not fields on the stable identity.
    as_dict = identity.to_dict()
    assert "start_line" not in as_dict
    assert "path" not in as_dict
    assert as_dict["qualified_name"] == "apps.agent-supervisor.ConsoleRoot"
    assert as_dict["schema_version"] == UI_COMPONENT_IDENTITY_SCHEMA

    # Same logical component at different line numbers → same identity.
    moved = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.ConsoleRoot",
        component_kind="screen",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    assert identity.to_dict() == moved.to_dict()
    left = stable_identity_record(identity)
    right = stable_identity_record(moved)
    assert left.cid == right.cid
    assert left.domain == DOMAIN_STABLE_IDENTITY


def test_stable_identity_changes_with_qualified_name() -> None:
    a = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.ConsoleRoot",
        component_kind="screen",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    b = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.GoalForm",
        component_kind="form",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    assert stable_identity_record(a).cid != stable_identity_record(b).cid


# ---------------------------------------------------------------------------
# Material normalization + version compiler
# ---------------------------------------------------------------------------


def _base_material(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "structure": {
            "tag": "form",
            "children": ["input", "button"],
            "start_line": 10,
            "source_path": "/home/user/checkout/web/js/apps/agent-supervisor.js",
        },
        "props": {"name": "goal", "required": True, "comments": "ignore me"},
        "state": {"ready": True},
        "handlers": {"onSubmit": "dispatchGoal"},
        "accessibility": {"role": "form", "label": "Goal form"},
        "styles": {"tokens": ["color.primary"], "start_column": 4},
        "actions": {"dispatch": "agentSupervisor.dispatch"},
        "localization": {"keys": ["agentSupervisor.goal.label"]},
    }
    material.update(overrides)
    return material


def test_normalize_material_drops_source_provenance_and_keeps_paths() -> None:
    raw = {
        "tag": "button",
        "start_line": 42,
        "end_line": 44,
        "source_path": "/abs/checkout/file.tsx",
        "path": "/settings/profile",
        "href": "/help",
        "label": "  Save   now  ",
        "source_span": {"start_line": 42},
    }
    normalized = normalize_material(raw)
    assert "start_line" not in normalized
    assert "end_line" not in normalized
    assert "source_path" not in normalized
    assert "source_span" not in normalized
    assert normalized["path"] == "/settings/profile"
    assert normalized["href"] == "/help"
    assert normalized["label"] == "Save now"
    assert normalized["tag"] == "button"


def test_version_identity_stable_across_line_movement_and_unrelated_noise() -> None:
    identity = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.GoalForm",
        component_kind="form",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    material_a = _base_material()
    material_b = _base_material(
        structure={
            "tag": "form",
            "children": ["input", "button"],
            "start_line": 999,
            "source_path": "/other/checkout/web/js/apps/agent-supervisor.js",
        },
        styles={
            "tokens": ["color.primary"],
            "start_column": 80,
            "absolute_path": "/tmp/styles.css",
        },
    )
    version_a = compile_component_version(
        identity, material_a, extractor_version="gui-static-scanner-1.0.0"
    )
    version_b = compile_component_version(
        identity, material_b, extractor_version="gui-static-scanner-1.0.0"
    )
    assert version_a.structure_digest == version_b.structure_digest
    assert version_a.styles_digest == version_b.styles_digest
    assert version_a.to_dict() == version_b.to_dict()
    assert (
        component_version_identity(version_a).cid
        == component_version_identity(version_b).cid
    )


def test_meaningful_material_change_alters_version_identity() -> None:
    identity = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.GoalForm",
        component_kind="form",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    base = _base_material()
    changed = _base_material(
        handlers={"onSubmit": "dispatchGoal", "onCancel": "cancelGoal"},
    )
    version_base = compile_component_version(
        identity, base, extractor_version="gui-static-scanner-1.0.0"
    )
    version_changed = compile_component_version(
        identity, changed, extractor_version="gui-static-scanner-1.0.0"
    )
    assert version_base.handlers_digest != version_changed.handlers_digest
    assert version_base.structure_digest == version_changed.structure_digest
    assert (
        component_version_identity(version_base).cid
        != component_version_identity(version_changed).cid
    )
    # Stable logical identity is preserved.
    assert version_base.stable_identity.to_dict() == (
        version_changed.stable_identity.to_dict()
    )


@pytest.mark.parametrize(
    "field", ["path", "href", "line", "column", "span", "offset", "comments"]
)
def test_generic_material_fields_remain_identity_bearing(field: str) -> None:
    assert facet_digest({field: "semantic-a"}) != facet_digest(
        {field: "semantic-b"}
    )


def test_explicit_null_facet_differs_from_an_absent_facet() -> None:
    identity = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.GoalForm",
        component_kind="form",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    explicit_null = compile_component_version(
        identity,
        {"props": None},
        extractor_version="gui-static-scanner-1.0.0",
    )
    absent = compile_component_version(
        identity, {}, extractor_version="gui-static-scanner-1.0.0"
    )
    assert explicit_null.props_digest == facet_digest(None)
    assert absent.props_digest == facet_digest({})
    assert explicit_null.props_digest != absent.props_digest


def test_component_version_compiler_facade() -> None:
    compiler = create_component_version_compiler(
        extractor_version="gui-static-scanner-1.0.0"
    )
    assert compiler.INTERFACE == UI_COMPONENT_VERSION_COMPILER_INTERFACE
    identity = build_stable_identity(
        application_id="app:agent-supervisor",
        qualified_name="apps.agent-supervisor.GoalForm",
        component_kind="form",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )
    version = compiler.compile(identity, _base_material())
    assert version.schema_version == UI_COMPONENT_VERSION_SCHEMA
    assert all(
        d.startswith("sha256:") and len(d) == 71
        for d in (
            version.structure_digest,
            version.props_digest,
            version.state_digest,
            version.handlers_digest,
            version.accessibility_digest,
            version.styles_digest,
            version.actions_digest,
            version.localization_digest,
        )
    )
    identity_record = compiler.identity_for(identity, _base_material())
    assert identity_record.domain == DOMAIN_COMPONENT_VERSION
    assert identity_record.rehash().cid == identity_record.cid


def test_artifact_digest_rehash_and_domain() -> None:
    art = artifact_digest({"tokens": ["a", "b"], "start_line": 1})
    assert art.interface == GUI_ARTIFACT_DIGEST_INTERFACE
    assert art.domain == DOMAIN_ARTIFACT
    assert art.digest == facet_digest({"tokens": ["a", "b"]})
    assert art.rehash().cid == art.cid
    assert sha256_digest(art.canonical_bytes) == art.digest
    parsed = parse_cid_v1(art.cid)
    assert parsed["digest_label"] == art.digest


def test_literal_cross_runtime_artifact_domain_null_vector() -> None:
    artifact = artifact_digest(
        ARTIFACT_VECTOR_MATERIAL, domain=ARTIFACT_VECTOR_DOMAIN
    )
    assert artifact.canonical_bytes.decode("utf-8") == ARTIFACT_VECTOR_PREIMAGE
    assert artifact.digest == ARTIFACT_VECTOR_DIGEST
    assert artifact.cid == ARTIFACT_VECTOR_CID
    assert artifact.rehash() == artifact
    domain_a = artifact_digest(ARTIFACT_VECTOR_MATERIAL, domain="gui.domain-a")
    domain_b = artifact_digest(ARTIFACT_VECTOR_MATERIAL, domain="gui.domain-b")
    assert domain_a.digest != domain_b.digest
    assert domain_a.cid != domain_b.cid
    assert domain_a.canonical_bytes != domain_b.canonical_bytes


def test_artifact_rehash_rejects_forged_profile_metadata() -> None:
    artifact = artifact_digest(ARTIFACT_VECTOR_MATERIAL)
    with pytest.raises(GuiIdentityError, match="metadata"):
        replace(artifact, domain="gui.forged").rehash()
    with pytest.raises(GuiIdentityError, match="metadata"):
        replace(artifact, interface="ForgedArtifact@1").rehash()
    with pytest.raises(GuiIdentityError, match="metadata"):
        replace(artifact, schema_version="forged-artifact/v1").rehash()
    with pytest.raises(GuiIdentityError, match="rehash"):
        replace(artifact, digest=f"sha256:{'0' * 64}").rehash()


def test_empty_and_equivalent_facets_share_digest() -> None:
    assert facet_digest({}) == facet_digest(
        {"start_line": 3, "source_path": "/tmp/source.ts"}
    )
    assert facet_digest({"a": 1}) != facet_digest({"a": 2})
