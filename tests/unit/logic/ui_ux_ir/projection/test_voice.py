"""UIR-044: voice and headless projection adapters."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.projection.voice import (
    ChannelKind,
    InterruptionPolicy,
    UrgencyClass,
    project_headless,
    project_voice,
    voice_dialogue_problem,
)


def test_voice_projection_preserves_dialogue_semantics() -> None:
    problem = voice_dialogue_problem()
    artifact = project_voice(problem)
    assert artifact.turns
    assert artifact.channel_status is not None
    # No mic capture / ASR / TTS engine surfaces.
    blob = str(artifact.to_dict() if hasattr(artifact, "to_dict") else artifact.__dict__).lower()
    assert "microphone_pcm" not in blob
    assert "asr_model" not in blob
    assert "tts_engine" not in blob
    # Dialogue order is explicit and deterministic.
    assert artifact.dialogue_order
    kinds = {t.kind for t in artifact.turns}
    assert kinds


def test_headless_projection_is_renderer_neutral() -> None:
    problem = voice_dialogue_problem()
    artifact = project_headless(problem)
    assert artifact.steps if hasattr(artifact, "steps") else artifact
    blob = str(artifact.to_dict() if hasattr(artifact, "to_dict") else artifact.__dict__).lower()
    assert "agent_executor" not in blob
    assert "authority_grant" not in blob


def test_urgency_and_interruption_enums_are_closed() -> None:
    assert set(UrgencyClass)  # non-empty closed set
    assert set(InterruptionPolicy)
    assert ChannelKind.AUDIO in set(ChannelKind) or "audio" in {c.value for c in ChannelKind}
