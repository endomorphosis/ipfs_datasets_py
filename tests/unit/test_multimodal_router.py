from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py import multimodal_router


class _FakeChatProvider:
    def __init__(self) -> None:
        self.messages = None

    def chat_completions(self, messages, *, model_name=None, **kwargs):
        self.messages = list(messages)
        return {
            "choices": [
                {
                    "message": {
                        "content": "vision-ok",
                    }
                }
            ]
        }


class _FakeTextProvider:
    def __init__(self) -> None:
        self.prompt = None

    def generate(self, prompt: str, *, model_name=None, **kwargs):
        self.prompt = prompt
        return "text-ok"


def test_build_multimodal_messages_embeds_image_paths_as_data_urls(tmp_path: Path) -> None:
    image_path = tmp_path / "workspace.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    messages = multimodal_router.build_multimodal_messages(
        prompt="Review this dashboard",
        image_paths=[image_path],
        system_prompt="System",
        additional_text_blocks=["Prioritize complaint intake friction."],
    )

    assert messages[0]["role"] == "system"
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "text"
    assert content[2]["type"] == "image_url"
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_generate_multimodal_text_uses_chat_provider_for_image_inputs(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "workspace.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    provider = _FakeChatProvider()

    monkeypatch.setattr(multimodal_router.llm_router, "get_llm_provider", lambda provider=None, deps=None: provider)

    result = multimodal_router.generate_multimodal_text(
        "Review this dashboard",
        provider_instance=provider,
        image_paths=[image_path],
    )

    assert result == "vision-ok"
    assert provider.messages is not None
    user_content = provider.messages[0]["content"]
    assert isinstance(user_content, list)
    assert any(part.get("type") == "image_url" for part in user_content)


def test_generate_multimodal_text_falls_back_to_flattened_prompt_for_text_only_providers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "workspace.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    provider = _FakeTextProvider()

    monkeypatch.setattr(multimodal_router.llm_router, "get_llm_provider", lambda provider=None, deps=None: provider)

    result = multimodal_router.generate_multimodal_text(
        "Review this dashboard",
        provider_instance=provider,
        image_paths=[image_path],
        additional_text_blocks=["Focus on evidence upload clarity."],
    )

    assert result == "text-ok"
    assert provider.prompt is not None
    assert "Review this dashboard" in provider.prompt
    assert "Focus on evidence upload clarity." in provider.prompt
    assert "[image attachment included]" in provider.prompt


def test_generate_text_alias_points_to_multimodal_generation() -> None:
    assert multimodal_router.generate_text is multimodal_router.generate_multimodal_text
