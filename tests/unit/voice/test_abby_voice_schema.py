"""Offline acceptance tests for the canonical Abby voice dataset contract."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    HUGGINGFACE_FEATURE_SPECS,
    SCHEMA_REGISTRY,
    SCHEMA_VERSIONS,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceSchemaError,
    AbbyVoiceTemplate,
    get_huggingface_features,
    get_pyarrow_schema,
    migrate_legacy_audio,
    migrate_v1_record,
    parse_abby_voice_record,
    schema_columns,
    sha256_text,
    stable_audio_id,
    stable_provenance_id,
    stable_response_id,
    stable_template_id,
    validate_bundle,
    validate_publishable,
    validate_records,
)

SOURCE_CID = "bafybeigdyrzt4exampleabbyvoicesourcecid"
AUDIO_HASH = "a" * 64


def _response(**overrides):
    values = {
        "response_id": "response-shelter-001",
        "text": "The current shelter line is 211.",
        "spoken_text": "The current shelter line is two one one.",
        "locale": "en-US",
        "template_id": "template-shelter-001",
        "intent": "shelter_referral",
        "utterance": "I need somewhere safe tonight.",
        "slot_names": ("phone",),
        "slot_values": ("211",),
        "slot_source_cids": (SOURCE_CID,),
        "audio_ids": ("audio-shelter-001",),
        "source_cids": (SOURCE_CID,),
        "safety_labels": ("housing",),
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
        "created_at": "2026-07-23T12:00:00Z",
    }
    values.update(overrides)
    return AbbyVoiceResponse(**values)


def _template(**overrides):
    values = {
        "template_id": "template-shelter-001",
        "template_text": "The current shelter line is {phone}.",
        "spoken_template": "The current shelter line is {phone}.",
        "intent": "shelter_referral",
        "locale": "en-US",
        "slot_names": ("phone",),
        "required_slot_names": ("phone",),
        "factual_slot_names": ("phone",),
        "source_cids": (SOURCE_CID,),
        "safety_labels": ("housing",),
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
        "created_at": "2026-07-23T12:00:00+00:00",
    }
    values.update(overrides)
    return AbbyVoiceTemplate(**values)


def _audio(**overrides):
    values = {
        "audio_id": "audio-shelter-001",
        "spoken_text": "The current shelter line is two one one.",
        "content_sha256": AUDIO_HASH,
        "locale": "en-US",
        "uri": "ipfs://bafybeigdyrzt4exampleabbyvoiceaudio",
        "ipfs_cid": "bafybeigdyrzt4exampleabbyvoiceaudio",
        "response_id": "response-shelter-001",
        "segment_kind": "response",
        "mime_type": "audio/mpeg",
        "codec": "mp3",
        "byte_length": 1234,
        "duration_ms": 1250.5,
        "sample_rate_hz": 24000,
        "channels": 1,
        "provider": "IndexTTS",
        "voice": "abby",
        "source_cids": (SOURCE_CID,),
        "license_id": "CC-BY-4.0",
        "consent_status": "granted",
        "created_at": "2026-07-23T12:00:00Z",
    }
    values.update(overrides)
    return AbbyVoiceAudio(**values)


def _provenance(**overrides):
    values = {
        "provenance_id": "provenance-response-shelter-001",
        "subject_id": "response-shelter-001",
        "subject_schema_version": ABBY_VOICE_RESPONSE_V2,
        "transformation_name": "normalize_abby_response",
        "transformation_version": "2.0.0",
        "source_uri": "https://example.org/public-211-record",
        "source_revision": "2026-07-23",
        "source_sha256": "b" * 64,
        "source_cids": (SOURCE_CID,),
        "generated_at": "2026-07-23T12:00:00Z",
        "locale": "en-US",
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
        "safety_labels": ("public_service_record",),
    }
    values.update(overrides)
    return AbbyVoiceProvenance(**values)


def test_registry_exposes_four_exact_separate_v2_schemas():
    assert SCHEMA_VERSIONS == (
        "abby_voice_response_v2",
        "abby_voice_template_v2",
        "abby_voice_audio_v2",
        "abby_voice_provenance_v2",
    )
    assert set(SCHEMA_REGISTRY) == set(SCHEMA_VERSIONS)
    assert len({tuple(schema_columns(name)) for name in SCHEMA_VERSIONS}) == 4


@pytest.mark.parametrize(
    "row",
    [_response(), _template(), _audio(), _provenance()],
)
def test_canonical_rows_are_strict_json_round_trips(row):
    payload = row.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    restored = parse_abby_voice_record(json.loads(encoded))

    assert restored == row
    assert restored.to_dict() == payload
    assert payload["schema_version"] == row.SCHEMA_VERSION


def test_list_columns_emit_lists_and_optional_scalars_emit_null():
    payload = AbbyVoiceResponse(
        response_id="response-empty-lists",
        text="I can help.",
        spoken_text="I can help.",
    ).to_dict()

    assert payload["slot_names"] == []
    assert isinstance(payload["source_cids"], list)
    assert payload["template_id"] is None
    assert payload["utterance"] is None


def test_rows_are_immutable_and_ordered_list_values_are_deduplicated():
    row = _response(
        route_labels=["grounded", "grounded", "safe"],
        source_cids=[SOURCE_CID, SOURCE_CID],
    )

    assert row.route_labels == ("grounded", "safe")
    assert row.source_cids == (SOURCE_CID,)
    with pytest.raises(FrozenInstanceError):
        row.response_id = "changed"


def test_response_hash_defaults_to_full_spoken_text_sha256():
    row = AbbyVoiceResponse(
        response_id="response-hash",
        text="Dial 211.",
        spoken_text="Dial two one one.",
    )

    assert row.content_sha256 == sha256_text("Dial two one one.")
    assert len(row.content_sha256) == 64


def test_response_rejects_incorrect_or_truncated_hash():
    with pytest.raises(AbbyVoiceSchemaError, match="full lower-case SHA-256"):
        _response(content_sha256="0123456789abcdef0123")
    with pytest.raises(AbbyVoiceSchemaError, match=r"SHA-256\(spoken_text"):
        _response(content_sha256="0" * 64)


def test_response_requires_aligned_grounded_slot_columns():
    with pytest.raises(AbbyVoiceSchemaError, match="must have equal lengths"):
        _response(slot_source_cids=())


def test_list_columns_never_accept_a_string_or_null():
    payload = _response().to_dict()
    payload["source_cids"] = SOURCE_CID
    with pytest.raises(AbbyVoiceSchemaError, match="list or tuple"):
        parse_abby_voice_record(payload)

    payload["source_cids"] = None
    with pytest.raises(AbbyVoiceSchemaError, match="not null"):
        parse_abby_voice_record(payload)


def test_template_placeholders_exactly_match_declared_slots():
    with pytest.raises(AbbyVoiceSchemaError, match="exactly match slot_names"):
        _template(slot_names=("phone", "address"))
    with pytest.raises(AbbyVoiceSchemaError, match="subset of slot_names"):
        _template(required_slot_names=("address",))


@pytest.mark.parametrize(
    "unsafe",
    (
        "Call {person.phone}.",
        "Call {phones[0]}.",
        "Call {phone!r}.",
        "Call {phone:>20}.",
    ),
)
def test_template_rejects_unsafe_format_expressions(unsafe):
    with pytest.raises(AbbyVoiceSchemaError, match="unsafe placeholder"):
        _template(template_text=unsafe, spoken_template=unsafe)


def test_audio_requires_external_location_subject_and_audio_media_type():
    with pytest.raises(AbbyVoiceSchemaError, match="uri or ipfs_cid"):
        _audio(uri=None, ipfs_cid=None)
    with pytest.raises(AbbyVoiceSchemaError, match="requires a response_id"):
        _audio(response_id=None, template_id=None, slot_name=None)
    with pytest.raises(AbbyVoiceSchemaError, match=r"audio/\*"):
        _audio(mime_type="application/octet-stream")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("duration_ms", float("nan"), "finite number"),
        ("duration_ms", -0.1, "finite number"),
        ("sample_rate_hz", 0, "positive integer"),
        ("channels", True, "positive integer"),
        ("byte_length", -1, "greater than or equal"),
    ),
)
def test_audio_rejects_invalid_numeric_metadata(field, value, message):
    with pytest.raises(AbbyVoiceSchemaError, match=message):
        _audio(**{field: value})


def test_slot_value_audio_requires_slot_name_and_value():
    with pytest.raises(AbbyVoiceSchemaError, match="both slot_name and slot_value"):
        _audio(
            segment_kind="slot_value",
            response_id=None,
            template_id="template-shelter-001",
            slot_name="phone",
            slot_value=None,
        )


def test_provenance_requires_supported_subject_and_source_locator():
    with pytest.raises(AbbyVoiceSchemaError, match="response, template, or audio"):
        _provenance(subject_schema_version=ABBY_VOICE_PROVENANCE_V2)
    with pytest.raises(AbbyVoiceSchemaError, match="source_uri or at least one source_cid"):
        _provenance(source_uri=None, source_cids=())


def test_rfc3339_timestamps_must_be_timezone_aware():
    with pytest.raises(AbbyVoiceSchemaError, match="timezone-aware"):
        _response(created_at="2026-07-23T12:00:00")
    with pytest.raises(AbbyVoiceSchemaError, match="timezone-aware"):
        _provenance(generated_at="not-a-timestamp")


def test_wrong_schema_and_unknown_columns_are_rejected():
    response = _response().to_dict()
    response["schema_version"] = ABBY_VOICE_AUDIO_V2
    with pytest.raises(AbbyVoiceSchemaError):
        AbbyVoiceResponse.from_dict(response)

    response = _response().to_dict()
    response["manifest"] = {"count": 1}
    with pytest.raises(AbbyVoiceSchemaError, match="unknown columns"):
        parse_abby_voice_record(response)


def test_strict_mapping_requires_every_fixed_column_including_empty_lists():
    response = _response().to_dict()
    del response["location_tags"]

    with pytest.raises(AbbyVoiceSchemaError, match="missing canonical columns"):
        parse_abby_voice_record(response)

    restored = AbbyVoiceResponse.from_dict(response, strict=False)
    assert restored.location_tags == ()


def test_validate_records_rejects_duplicate_ids_per_config():
    with pytest.raises(AbbyVoiceSchemaError, match="duplicate ID"):
        validate_records((_response(), _response()))


def test_bundle_validates_cross_config_references():
    bundle = validate_bundle(
        responses=(_response(),),
        templates=(_template(),),
        audio=(_audio(),),
        provenance=(_provenance(),),
    )

    assert bundle.responses[0].template_id == bundle.templates[0].template_id
    assert bundle.responses[0].audio_ids == (bundle.audio[0].audio_id,)


def test_bundle_reports_missing_template_audio_provenance_and_subjects():
    response = _response(
        template_id="template-missing",
        audio_ids=("audio-missing",),
        provenance_ids=("provenance-missing",),
    )
    orphan = _provenance(subject_id="response-missing")

    with pytest.raises(AbbyVoiceSchemaError) as caught:
        validate_bundle(responses=(response,), provenance=(orphan,))

    message = str(caught.value)
    assert "missing template" in message
    assert "missing audio" in message
    assert "missing provenance" in message
    assert "missing subject" in message


def test_publishability_is_stric_but_structural_migration_can_be_unknown():
    migrated = migrate_v1_record(
        {"text": "I can help.", "routes": ["safe_fallback"]},
        ABBY_VOICE_RESPONSE_V2,
    )

    assert migrated.consent_status == "unknown"
    with pytest.raises(AbbyVoiceSchemaError, match="not publishable"):
        validate_publishable(migrated)
    validate_publishable(_response(template_id=None, audio_ids=()))


def test_stable_id_helpers_are_deterministic_and_content_sensitive():
    assert stable_response_id("A", "A") == stable_response_id("A", "A")
    assert stable_response_id("A", "A") != stable_response_id("B", "B")
    assert stable_template_id("Hi", "Hi") != stable_template_id("Bye", "Bye")
    assert stable_audio_id(AUDIO_HASH) == stable_audio_id(AUDIO_HASH)
    assert stable_provenance_id("subject", "file.json", "normalize") == (
        stable_provenance_id("subject", "file.json", "normalize")
    )


def test_legacy_response_migration_is_deterministic_non_mutating_and_full_hash():
    legacy = {
        "id": "abby-tts-old-id",
        "textHash": "0123456789abcdef0123",
        "text": "Call two one one.",
        "originalTexts": ["Call 211."],
        "routes": ["grounded_211_answer"],
        "sourceIds": ["public-fixture#turn-1"],
        "serviceTags": ["housing"],
    }
    before = json.loads(json.dumps(legacy))

    first = migrate_v1_record(
        legacy,
        ABBY_VOICE_RESPONSE_V2,
        license_id="CC-BY-4.0",
        consent_status="not_required",
    )
    second = migrate_v1_record(
        legacy,
        ABBY_VOICE_RESPONSE_V2,
        license_id="CC-BY-4.0",
        consent_status="not_required",
    )

    assert first == second
    assert legacy == before
    assert first.response_id != legacy["id"]
    assert first.text == "Call 211."
    assert first.spoken_text == "Call two one one."
    assert first.content_sha256 == sha256_text(first.spoken_text)


@pytest.mark.parametrize(
    "wrapper",
    (
        {"responses": [{"id": "one"}], "responseCount": 1},
        {"manifest": {"count": 1}},
        {"index": {"one": 0}},
    ),
)
def test_migration_rejects_manifests_and_indexes(wrapper):
    with pytest.raises(AbbyVoiceSchemaError, match="not rows"):
        migrate_v1_record(wrapper, ABBY_VOICE_RESPONSE_V2)


def test_legacy_audio_requires_real_full_audio_digest_not_text_hash():
    with pytest.raises(AbbyVoiceSchemaError, match="truncated textHash"):
        migrate_legacy_audio(
            {
                "text": "Call two one one.",
                "textHash": "0123456789abcdef0123",
                "preferredAudioPath": "audio/example.mp3",
            },
            response_id="response-1",
        )


def test_legacy_audio_maps_flat_metadata_when_digest_is_available():
    row = migrate_legacy_audio(
        {
            "text": "Call two one one.",
            "content_sha256": AUDIO_HASH,
            "preferredAudioPath": "audio/example.mp3",
            "preferredMimeType": "audio/mpeg",
            "mp3Bytes": 400,
        },
        response_id="response-1",
    )

    assert row.uri == "audio/example.mp3"
    assert row.byte_length == 400
    assert row.text_sha256 == sha256_text(row.spoken_text)


def test_legacy_audio_migration_preserves_valid_zero_lengths_and_durations():
    row = migrate_legacy_audio(
        {
            "text": "Silence.",
            "content_sha256": AUDIO_HASH,
            "preferredAudioPath": "audio/silence.mp3",
            "mp3Bytes": 0,
            "durationMs": 0,
        },
        response_id="response-1",
    )

    assert row.byte_length == 0
    assert row.duration_ms == 0


def test_declarative_hugging_face_specs_are_flat_and_fixed():
    for schema_version, features in HUGGINGFACE_FEATURE_SPECS.items():
        assert tuple(features) == schema_columns(schema_version)
        assert set(features.values()) <= {
            "string",
            "int64",
            "float64",
            "list[string]",
        }
        assert all("struct" not in value for value in features.values())


@pytest.mark.parametrize(
    "row",
    [_response(), _template(), _audio(), _provenance()],
)
def test_arrow_and_parquet_round_trip_preserves_schema_and_empty_lists(row, tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    arrow_schema = get_pyarrow_schema(row.SCHEMA_VERSION)
    table = pa.Table.from_pylist([row.to_dict()], schema=arrow_schema)
    destination = tmp_path / f"{row.SCHEMA_VERSION}.parquet"

    pq.write_table(table, destination)
    restored = pq.read_table(destination).to_pylist()[0]

    assert parse_abby_voice_record(restored) == row
    for field in row.LIST_FIELDS:
        assert isinstance(restored[field], list)


def test_hugging_face_features_are_lazy_and_exact_when_dependency_is_installed():
    datasets = pytest.importorskip("datasets")
    if not hasattr(datasets, "Features"):
        pytest.skip("the importable datasets namespace is not Hugging Face datasets")

    features = get_huggingface_features(ABBY_VOICE_RESPONSE_V2)

    assert isinstance(features, datasets.Features)
    assert tuple(features) == schema_columns(ABBY_VOICE_RESPONSE_V2)
