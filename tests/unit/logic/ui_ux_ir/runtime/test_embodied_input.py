"""UIR-052: hand/gaze/head and Neural Band/captouch normalization."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    EventKind,
    EventProvenance,
    assert_not_authority,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.input.embodied import (
    CAPABILITY_DPAD_CAPTOUCH,
    CAPABILITY_GAZE,
    CAPABILITY_HAND_GESTURE,
    CAPABILITY_HEAD_POSE,
    CAPABILITY_MOTION,
    CAPABILITY_NEURAL_BAND,
    DEFAULT_DEBOUNCE_MS,
    DEFAULT_FALLBACKS,
    DEFAULT_GAZE_DWELL_MS,
    DEFAULT_HIGH_RISK_GAZE_DWELL_MS,
    EMBODIED_ADAPTER_ID,
    EMBODIED_INPUT_ADAPTER_INTERFACE,
    NEURAL_BAND_ADAPTER_ID,
    NEURAL_BAND_INTENT_ADAPTER_INTERFACE,
    EmbodiedCapabilityStatus,
    EmbodiedGateReason,
    EmbodiedInputAdapter,
    EmbodiedPhase,
    NeuralBandIntentAdapter,
    normalize_embodied_input,
    normalize_embodied_input_detailed,
    normalize_neural_band_intent,
    normalize_neural_band_intent_detailed,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def _base_hand(**overrides: object) -> dict:
    payload: dict = {
        "channel": "hand",
        "recognized": "pinch",
        "confidence": 0.92,
        "consent": True,
        "purpose": "ui-gesture-command",
        "target_component_id": "component:primary-action",
        "risk_class": "low",
        "calibrated": True,
        "age_ms": 40,
        "phase": "intention",
        "evidence_ref": "ref:gesture:redacted-1",
    }
    payload.update(overrides)
    return payload


def _base_gaze(**overrides: object) -> dict:
    payload: dict = {
        "channel": "gaze",
        "recognized": "dwell",
        "confidence": 0.9,
        "consent": True,
        "purpose": "ui-gaze-select",
        "target_component_id": "component:menu-item",
        "risk_class": "low",
        "calibrated": True,
        "dwell_ms": DEFAULT_GAZE_DWELL_MS + 50,
        "age_ms": 20,
        "phase": "intention",
    }
    payload.update(overrides)
    return payload


def _base_neural(**overrides: object) -> dict:
    payload: dict = {
        "channel": "neural_band",
        "recognized": "enter",
        "consent": True,
        "purpose": "ui-neural-nav",
        "target_component_id": "component:hud-action",
        "risk_class": "low",
        "age_ms": 10,
    }
    payload.update(overrides)
    return payload


def test_hand_gesture_maps_to_canonical_intention() -> None:
    event = normalize_embodied_input(
        _base_hand(recognized="pinch"),
        event_id="evt:hand-pinch",
        timestamp_ms=1000,
    )
    assert event.kind is EventKind.ACTIVATE
    assert event.capability_id == CAPABILITY_HAND_GESTURE
    assert event.source_adapter == EMBODIED_ADAPTER_ID
    assert event.raw_payload["phase"] == EmbodiedPhase.INTENTION.value
    assert event.raw_payload["normalized_intent_only"] is True
    assert event.raw_payload["raw_emg_retained"] is False
    assert event.raw_payload["raw_visual_retained"] is False
    assert_not_authority(event)

    confirm = normalize_embodied_input(
        _base_hand(recognized="thumbs_up"),
        event_id="evt:hand-confirm",
        timestamp_ms=1001,
    )
    assert confirm.kind is EventKind.CONFIRM

    cancel = normalize_embodied_input(
        _base_hand(recognized="open_palm"),
        event_id="evt:hand-cancel",
        timestamp_ms=1002,
    )
    assert cancel.kind is EventKind.CANCEL


def test_perception_is_not_intention() -> None:
    result = normalize_embodied_input_detailed(
        _base_hand(recognized="hand_visible", phase="perception", confidence=0.99),
        event_id="evt:hand-visible",
        timestamp_ms=2000,
    )
    assert result.phase is EmbodiedPhase.PERCEPTION
    assert result.is_intention is False
    assert result.event is not None
    assert result.event.kind in {EventKind.HOVER, EventKind.FOCUS}
    assert EmbodiedGateReason.PERCEPTION_ONLY in {g.reason for g in result.gates}
    assert result.event.raw_payload["phase"] == "perception"

    gaze_enter = normalize_embodied_input_detailed(
        _base_gaze(recognized="gaze_enter", phase="perception", dwell_ms=0),
        event_id="evt:gaze-enter",
        timestamp_ms=2001,
    )
    assert gaze_enter.phase is EmbodiedPhase.PERCEPTION
    assert gaze_enter.event is not None
    assert gaze_enter.event.kind is not EventKind.ACTIVATE


def test_gaze_requires_dwell_appropriate_to_risk() -> None:
    # Missing dwell fails the dwell gate / demotes intention.
    missing = normalize_embodied_input_detailed(
        {k: v for k, v in _base_gaze().items() if k != "dwell_ms"},
        event_id="evt:gaze-no-dwell",
        timestamp_ms=3000,
    )
    assert missing.requires_dwell is True
    assert EmbodiedGateReason.INSUFFICIENT_DWELL in {g.reason for g in missing.gates}

    short = normalize_embodied_input_detailed(
        _base_gaze(dwell_ms=100, risk_class="low"),
        event_id="evt:gaze-short",
        timestamp_ms=3001,
    )
    assert short.requires_dwell is True
    assert short.phase is EmbodiedPhase.PERCEPTION
    assert short.event is not None
    assert short.event.kind is EventKind.HOVER

    ok = normalize_embodied_input(
        _base_gaze(dwell_ms=DEFAULT_GAZE_DWELL_MS, risk_class="low"),
        event_id="evt:gaze-ok",
        timestamp_ms=3002,
    )
    assert ok.kind is EventKind.ACTIVATE
    assert ok.raw_payload["dwell_ms"] == DEFAULT_GAZE_DWELL_MS

    high_short = normalize_embodied_input_detailed(
        _base_gaze(
            dwell_ms=DEFAULT_HIGH_RISK_GAZE_DWELL_MS - 1,
            risk_class="destructive",
        ),
        event_id="evt:gaze-high-short",
        timestamp_ms=3003,
    )
    assert high_short.requires_dwell is True
    assert high_short.phase is EmbodiedPhase.PERCEPTION

    high_ok = normalize_embodied_input_detailed(
        _base_gaze(
            dwell_ms=DEFAULT_HIGH_RISK_GAZE_DWELL_MS,
            risk_class="destructive",
        ),
        event_id="evt:gaze-high-ok",
        timestamp_ms=3004,
    )
    assert high_ok.requires_dwell is False
    assert high_ok.requires_confirmation is True
    assert EmbodiedGateReason.HIGH_RISK_CONFIRMATION in {
        g.reason for g in high_ok.gates
    }


def test_high_risk_hand_requires_confirmation() -> None:
    result = normalize_embodied_input_detailed(
        _base_hand(recognized="pinch", risk_class="high", confidence=0.99),
        event_id="evt:hand-high",
        timestamp_ms=4000,
    )
    assert result.requires_confirmation is True
    assert result.event is not None
    assert result.event.raw_payload["requires_confirmation"] is True
    assert EmbodiedGateReason.HIGH_RISK_CONFIRMATION in {
        g.reason for g in result.gates
    }

    # Cancel remains a safety action without high-risk confirmation gate.
    cancel = normalize_embodied_input_detailed(
        _base_hand(recognized="open_palm", risk_class="destructive"),
        event_id="evt:hand-cancel-high",
        timestamp_ms=4001,
    )
    assert cancel.event is not None
    assert cancel.event.kind is EventKind.CANCEL
    assert cancel.requires_confirmation is False


def test_debounce_prevents_accidental_duplicate_activation() -> None:
    adapter = EmbodiedInputAdapter()
    first = adapter.normalize_detailed(
        _base_hand(recognized="pinch"),
        event_id="evt:dup-1",
        timestamp_ms=5000,
    )
    assert first.duplicate_suppressed is False
    assert first.event is not None
    assert first.event.kind is EventKind.ACTIVATE

    second = adapter.normalize_detailed(
        _base_hand(recognized="pinch"),
        event_id="evt:dup-2",
        timestamp_ms=5000 + DEFAULT_DEBOUNCE_MS - 1,
    )
    assert second.duplicate_suppressed is True
    assert second.event is not None
    assert second.event.raw_payload["activation_suppressed"] is True
    assert second.event.kind is EventKind.CUSTOM
    assert EmbodiedGateReason.DEBOUNCE_DUPLICATE in {
        g.reason for g in second.gates
    }

    # Outside debounce window is allowed again.
    third = adapter.normalize_detailed(
        _base_hand(recognized="pinch"),
        event_id="evt:dup-3",
        timestamp_ms=5000 + DEFAULT_DEBOUNCE_MS + 10,
    )
    assert third.duplicate_suppressed is False
    assert third.event is not None
    assert third.event.kind is EventKind.ACTIVATE


def test_unavailable_capability_expresses_conventional_mobile_fallback() -> None:
    result = normalize_embodied_input_detailed(
        {
            "channel": "gaze",
            "capability_status": "unavailable",
            "unavailable_reason": "eye tracking not present on this device",
            "fallback_modalities": [
                "pointer_mouse",
                "keyboard",
                "touchscreen",
                "mobile_companion",
            ],
            "purpose": "ui-gaze-select",
        },
        event_id="evt:gaze-unavail",
        timestamp_ms=6000,
    )
    assert result.event is None
    assert result.unavailable is not None
    assert result.unavailable.capability_id == CAPABILITY_GAZE
    assert result.unavailable.status is EmbodiedCapabilityStatus.UNAVAILABLE
    assert "mobile_companion" in result.unavailable.fallback_modalities
    assert "pointer_mouse" in result.unavailable.fallback_modalities
    assert EmbodiedGateReason.CAPABILITY_UNAVAILABLE in {
        g.reason for g in result.gates
    }

    with pytest.raises(UIIRValidationError, match="unavailable|fallback"):
        normalize_embodied_input(
            {
                "channel": "hand",
                "status": "unsupported",
                "reason": "no depth camera",
            },
            event_id="evt:hand-unavail",
            timestamp_ms=6001,
        )

    adapter = EmbodiedInputAdapter()
    report = adapter.report_unavailable(
        capability_id="neural_band",
        reason="Neural Band not paired",
        status=EmbodiedCapabilityStatus.UNAVAILABLE,
    )
    assert report.capability_id == CAPABILITY_NEURAL_BAND
    assert set(DEFAULT_FALLBACKS).issubset(set(report.fallback_modalities)) or set(
        report.fallback_modalities
    ).issubset(set(DEFAULT_FALLBACKS) | set(report.fallback_modalities))


def test_never_claim_or_retain_raw_emg_or_visual_sensor_data() -> None:
    with pytest.raises(UIIRValidationError, match="EMG|visual|Raw"):
        normalize_embodied_input(
            _base_hand(raw_emg=[0.1, 0.2, 0.3]),
            event_id="evt:emg",
            timestamp_ms=7000,
        )
    with pytest.raises(UIIRValidationError, match="EMG|visual|Raw"):
        normalize_embodied_input(
            _base_gaze(camera_frame="base64:abc"),
            event_id="evt:frame",
            timestamp_ms=7001,
        )
    with pytest.raises(UIIRValidationError, match="EMG|visual|Raw"):
        normalize_embodied_input(
            _base_hand(nested={"gaze_stream": "continuous"}),
            event_id="evt:nested-stream",
            timestamp_ms=7002,
        )
    with pytest.raises(UIIRValidationError, match="authority|grant"):
        normalize_embodied_input(
            _base_hand(grant="ucan:admin"),
            event_id="evt:grant",
            timestamp_ms=7003,
        )

    # Successful events explicitly deny retaining raw streams.
    event = normalize_embodied_input(
        _base_hand(),
        event_id="evt:clean",
        timestamp_ms=7004,
    )
    assert event.raw_payload["raw_emg_retained"] is False
    assert event.raw_payload["raw_visual_retained"] is False
    assert "raw_emg" not in event.raw_payload
    assert "camera_frame" not in event.raw_payload


def test_neural_band_arrow_enter_mapping_no_emg() -> None:
    enter = normalize_neural_band_intent(
        _base_neural(recognized="Enter"),
        event_id="evt:nb-enter",
        timestamp_ms=8000,
    )
    assert enter.kind is EventKind.ACTIVATE
    assert enter.capability_id == CAPABILITY_NEURAL_BAND
    assert enter.source_adapter == NEURAL_BAND_ADAPTER_ID
    assert enter.raw_payload["emg_access"] is False
    assert enter.raw_payload["neural_band_representation"] == "arrow_enter_normalized"

    for key, direction in (
        ("ArrowUp", "up"),
        ("ArrowDown", "down"),
        ("ArrowLeft", "left"),
        ("ArrowRight", "right"),
    ):
        nav = normalize_neural_band_intent(
            _base_neural(recognized=key),
            event_id=f"evt:nb-{key}",
            timestamp_ms=8001,
        )
        assert nav.kind is EventKind.NAVIGATE
        assert nav.raw_payload["direction"] == direction

    with pytest.raises(UIIRValidationError, match="EMG|raw"):
        normalize_neural_band_intent(
            _base_neural(emg_access=True),
            event_id="evt:nb-emg-claim",
            timestamp_ms=8002,
        )

    with pytest.raises(UIIRValidationError, match="Arrow/Enter|Unsupported"):
        normalize_neural_band_intent(
            _base_neural(recognized="flex_index_raw"),
            event_id="evt:nb-bad-token",
            timestamp_ms=8003,
        )


def test_captouch_dpad_maps_like_neural_band() -> None:
    event = normalize_embodied_input(
        {
            "channel": "captouch",
            "recognized": "swipe_forward",
            "consent": True,
            "purpose": "ui-captouch",
            "target_component_id": "component:list",
            "risk_class": "low",
        },
        event_id="evt:cap-swipe",
        timestamp_ms=9000,
    )
    assert event.capability_id == CAPABILITY_DPAD_CAPTOUCH
    assert event.kind is EventKind.NAVIGATE
    assert event.raw_payload["dpad_mapping"] == "arrow_enter_style"

    select = normalize_embodied_input(
        {
            "channel": "dpad",
            "recognized": "enter",
            "consent": True,
            "purpose": "ui-dpad",
            "target_component_id": "component:list-item",
            "risk_class": "low",
        },
        event_id="evt:dpad-enter",
        timestamp_ms=9001,
    )
    assert select.kind is EventKind.ACTIVATE


def test_head_pose_and_motion_tokens() -> None:
    nod = normalize_embodied_input(
        {
            "channel": "head",
            "recognized": "nod",
            "confidence": 0.88,
            "consent": True,
            "purpose": "ui-head",
            "target_component_id": "component:confirm",
            "risk_class": "low",
            "calibrated": True,
            "phase": "intention",
        },
        event_id="evt:head-nod",
        timestamp_ms=10000,
    )
    assert nod.capability_id == CAPABILITY_HEAD_POSE
    assert nod.kind is EventKind.CONFIRM

    shake = normalize_embodied_input(
        {
            "channel": "motion",
            "recognized": "shake",
            "confidence": 0.8,
            "consent": True,
            "purpose": "ui-motion",
            "target_component_id": "component:dialog",
            "risk_class": "low",
            "calibrated": True,
            "phase": "intention",
        },
        event_id="evt:motion-shake",
        timestamp_ms=10001,
    )
    assert shake.capability_id == CAPABILITY_MOTION
    assert shake.kind is EventKind.CANCEL


def test_gesture_ambiguity_and_low_confidence_gates() -> None:
    low = normalize_embodied_input_detailed(
        _base_hand(confidence=0.2),
        event_id="evt:low-conf",
        timestamp_ms=11000,
    )
    assert EmbodiedGateReason.LOW_CONFIDENCE in {g.reason for g in low.gates}
    assert low.requires_clarification is True

    amb = normalize_embodied_input_detailed(
        _base_hand(
            confidence=0.7,
            alternatives=[
                {"recognized": "pinch", "confidence": 0.7},
                {"recognized": "grab", "confidence": 0.68},
            ],
        ),
        event_id="evt:amb",
        timestamp_ms=11001,
    )
    assert EmbodiedGateReason.GESTURE_AMBIGUITY in {g.reason for g in amb.gates}


def test_consent_purpose_and_stale_fail_closed() -> None:
    with pytest.raises(UIIRValidationError, match="purpose"):
        normalize_embodied_input(
            _base_hand(purpose=""),
            event_id="evt:no-purpose",
            timestamp_ms=12000,
        )
    missing_consent = _base_hand()
    del missing_consent["consent"]
    with pytest.raises(UIIRValidationError, match="consent"):
        normalize_embodied_input(
            missing_consent,
            event_id="evt:no-consent",
            timestamp_ms=12001,
        )
    with pytest.raises(UIIRValidationError, match="consent"):
        normalize_embodied_input(
            _base_hand(consent=False),
            event_id="evt:consent-false",
            timestamp_ms=12002,
        )
    with pytest.raises(UIIRValidationError, match="stale"):
        normalize_embodied_input(
            _base_hand(age_ms=60_000),
            event_id="evt:stale",
            timestamp_ms=12003,
        )


def test_adapter_interfaces_and_neural_band_class() -> None:
    embodied = EmbodiedInputAdapter()
    assert embodied.interface_id == EMBODIED_INPUT_ADAPTER_INTERFACE
    assert embodied.adapter_id == EMBODIED_ADAPTER_ID
    event = embodied.normalize(
        _base_hand(),
        event_id="evt:adapter",
        timestamp_ms=13000,
    )
    assert event.provenance is EventProvenance.HUMAN

    neural = NeuralBandIntentAdapter()
    assert neural.interface_id == NEURAL_BAND_INTENT_ADAPTER_INTERFACE
    assert neural.adapter_id == NEURAL_BAND_ADAPTER_ID
    assert neural.capability_id == CAPABILITY_NEURAL_BAND
    nb = neural.normalize(
        _base_neural(recognized="arrowup"),
        event_id="evt:nb-adapter",
        timestamp_ms=13001,
    )
    assert nb.kind is EventKind.NAVIGATE

    detailed = normalize_neural_band_intent_detailed(
        _base_neural(recognized="enter"),
        event_id="evt:nb-detail",
        timestamp_ms=13002,
    )
    assert detailed.capability_id == CAPABILITY_NEURAL_BAND
    assert detailed.event is not None
    assert detailed.phase is EmbodiedPhase.INTENTION


def test_uncalibrated_intention_is_gated() -> None:
    result = normalize_embodied_input_detailed(
        _base_hand(calibrated=False),
        event_id="evt:uncal",
        timestamp_ms=14000,
    )
    assert EmbodiedGateReason.UNCALIBRATED in {g.reason for g in result.gates}
    assert result.calibrated is False


def test_evidence_ref_rejects_inline_sensor_media() -> None:
    with pytest.raises(UIIRValidationError, match="evidence_ref|inline|media"):
        normalize_embodied_input(
            _base_hand(evidence_ref="data:image/png;base64,AAAA"),
            event_id="evt:bad-ref",
            timestamp_ms=15000,
        )
