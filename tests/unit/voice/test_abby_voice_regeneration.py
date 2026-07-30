from __future__ import annotations

from ipfs_datasets_py.voice.regeneration import (
    ABBY_VOICE_REGENERATION_POLICY_ID,
    AbbyVoiceRegenerationPlan,
    normalize_regeneration_spoken_text,
    regeneration_text_risks,
    unsafe_spoken_numeric_punctuation_reasons,
    unsafe_spoken_transformation_reasons,
)


def _row(
    *,
    audio_id: str = "abby-tts-old-a",
    response_id: str = "response-a",
    text: str = (
        "Call (503) 771-7914. Address: 11-32 S-East 13th Ave, "
        "Suite J-8, Portland, OR 97205."
    ),
) -> dict[str, object]:
    return {
        "audioId": audio_id,
        "responseId": response_id,
        "selectedDatasetAudioPath": f"audio/{audio_id}.mp3",
        "selectedText": text,
        "normalizedRepairText": text,
        "recommendation": "regenerate_from_normalized_text",
        "riskReasons": [
            "negative_prone_hyphen_digit_run",
            "numeric_address_or_zip_context",
            "raw_phone_number",
        ],
    }


def test_regeneration_normalizer_removes_phone_and_address_tts_traps() -> None:
    normalized = normalize_regeneration_spoken_text(
        "Call (503) 771-7914. Address: 11-32 S-East 13th Ave, "
        "Suite J-8, Portland, OR 97205."
    )

    assert "five zero three, seven seven one, seven nine one four" in normalized
    assert "one one three two Southeast one three" in normalized
    assert "Suite J eight" in normalized
    assert "nine seven two zero five" in normalized
    assert regeneration_text_risks(normalized) == ()


def test_regeneration_normalizer_repairs_historical_direction_contraction() -> None:
    normalized = normalize_regeneration_spoken_text(
        "That’s 503, 228, 6322. She’South 16, Lane County’South office, "
        "and Salem’South program are private."
    )

    assert "That’s" in normalized
    assert "She’s" in normalized
    assert "Lane County’s" in normalized
    assert "Salem’s" in normalized
    assert "South" not in normalized
    assert regeneration_text_risks(normalized) == ()


def test_regeneration_normalizer_repairs_saint_organization_abbreviation() -> None:
    normalized = normalize_regeneration_spoken_text(
        "Call St. Vincent de Paul, St. Mary’s Catholic Church, "
        "or St. Charles."
    )

    assert "Saint Vincent de Paul" in normalized
    assert "Saint Mary’s Catholic Church" in normalized
    assert "Saint Charles" in normalized
    assert "Street." not in normalized
    assert unsafe_spoken_transformation_reasons(normalized) == ()
    assert unsafe_spoken_transformation_reasons(
        "Street. Vincent de Paul and Street. Mary’s"
    ) == ("organization_abbreviation_expansion_corruption",)


def test_publication_numeric_punctuation_gate_covers_unicode_dashes_and_phone_parens() -> None:
    assert unsafe_spoken_numeric_punctuation_reasons(
        "Call five‐zero‐three or 5‑0‑3 from S-East, not negative (503)."
    ) == (
        "literal_negative",
        "number_word_dash",
        "digit_dash",
        "directional_address_dash",
        "parenthesized_area_code",
    )
    assert unsafe_spoken_numeric_punctuation_reasons(
        "Use the trauma-informed, twenty-one-day program."
    ) == ()
    assert unsafe_spoken_transformation_reasons(
        "Lane County’South office"
    ) == ("apostrophe_direction_corruption",)


def test_plan_and_workset_are_order_independent_and_preserve_supersession() -> None:
    rows = [
        _row(audio_id="abby-tts-old-b", response_id="response-b"),
        _row(audio_id="abby-tts-old-a", response_id="response-a"),
    ]

    forward = AbbyVoiceRegenerationPlan.from_records(rows)
    reverse = AbbyVoiceRegenerationPlan.from_records(reversed(rows))

    assert forward.plan_id == reverse.plan_id
    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert forward.policy_id == ABBY_VOICE_REGENERATION_POLICY_ID
    assert [item["superseded_audio_id"] for item in forward.supersession_map] == [
        "abby-tts-old-a",
        "abby-tts-old-b",
    ]

    workset = forward.to_voice_workset()
    assert len(workset.tts_manifest.items) == 2
    assert len(workset.asr_manifest.items) == 2
    assert len(workset.validation_manifest.items) == 2
    assert all(
        regeneration_text_risks(item.spoken_text) == ()
        for item in workset.tts_manifest.items
    )


def test_canary_selection_is_hash_distributed_and_deterministic() -> None:
    rows = [
        _row(audio_id=f"abby-tts-old-{index}", response_id=f"response-{index}")
        for index in range(20)
    ]
    plan = AbbyVoiceRegenerationPlan.from_records(rows)

    canary = plan.canary(12)

    assert len(canary.items) == 12
    assert canary.plan_id == plan.canary(12).plan_id
    assert {item.response_id for item in canary.items} != {
        f"response-{index}" for index in range(12)
    }
