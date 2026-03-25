"""Provider-agnostic multimodal router built on top of ``llm_router``.

This keeps the same overall routing model as ``ipfs_datasets_py.llm_router``
but adds first-class support for image inputs such as Playwright screenshots.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Optional, Sequence

from . import llm_router
from .router_deps import RouterDeps


DEFAULT_IMAGE_DETAIL = "auto"
LLMRouterError = llm_router.LLMRouterError
get_llm_provider = llm_router.get_llm_provider
clear_llm_router_caches = llm_router.clear_llm_router_caches
chat_completions_create = llm_router.chat_completions_create


def _guess_mime_type(path: str | Path, mime_type: str | None = None) -> str:
    if mime_type and str(mime_type).strip():
        return str(mime_type).strip()
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def encode_image_as_data_url(
    image_path: str | Path,
    *,
    mime_type: str | None = None,
) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{_guess_mime_type(path, mime_type=mime_type)};base64,{encoded}"


def build_text_part(text: str) -> dict[str, str]:
    return {"type": "text", "text": str(text or "")}


def build_image_part(
    *,
    image_path: str | Path | None = None,
    image_url: str | None = None,
    mime_type: str | None = None,
    detail: str | None = DEFAULT_IMAGE_DETAIL,
) -> dict[str, Any]:
    if image_url:
        url = str(image_url).strip()
    elif image_path is not None:
        url = encode_image_as_data_url(image_path, mime_type=mime_type)
    else:
        raise ValueError("build_image_part requires image_path or image_url")

    payload: dict[str, Any] = {"url": url}
    if detail and str(detail).strip():
        payload["detail"] = str(detail).strip()
    return {"type": "image_url", "image_url": payload}


def build_multimodal_messages(
    *,
    prompt: str,
    image_paths: Sequence[str | Path] | None = None,
    image_urls: Sequence[str] | None = None,
    system_prompt: str | None = None,
    additional_text_blocks: Sequence[str] | None = None,
    image_detail: str | None = DEFAULT_IMAGE_DETAIL,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})

    content: list[dict[str, Any]] = [build_text_part(prompt)]
    for block in additional_text_blocks or ():
        if str(block or "").strip():
            content.append(build_text_part(str(block)))
    for path in image_paths or ():
        content.append(build_image_part(image_path=path, detail=image_detail))
    for url in image_urls or ():
        content.append(build_image_part(image_url=url, detail=image_detail))

    messages.append({"role": "user", "content": content})
    return messages


def _flatten_content_part(part: Any) -> str:
    if isinstance(part, dict):
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "text":
            return str(part.get("text") or "").strip()
        if part_type == "image_url":
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
            else:
                url = str(image_url or "").strip()
            if not url:
                return ""
            if url.startswith("data:"):
                return "[image attachment included]"
            return f"[image: {url}]"
    return str(part or "").strip()


def _flatten_messages_to_prompt(messages: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").strip()
        content = message.get("content")
        if isinstance(content, list):
            rendered = "\n".join(filter(None, (_flatten_content_part(part) for part in content)))
        else:
            rendered = str(content or "").strip()
        lines.append(f"{role}: {rendered}")
    return "\n".join(lines).strip()


def generate_multimodal_text(
    prompt: str,
    *,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    provider_instance: Optional[Any] = None,
    deps: Optional[RouterDeps] = None,
    image_paths: Sequence[str | Path] | None = None,
    image_urls: Sequence[str] | None = None,
    system_prompt: str | None = None,
    additional_text_blocks: Sequence[str] | None = None,
    messages: Sequence[dict[str, Any]] | None = None,
    image_detail: str | None = DEFAULT_IMAGE_DETAIL,
    **kwargs: object,
) -> str:
    """Generate text from prompt + images using the shared provider router."""

    resolved_messages = list(messages) if messages is not None else build_multimodal_messages(
        prompt=prompt,
        image_paths=image_paths,
        image_urls=image_urls,
        system_prompt=system_prompt,
        additional_text_blocks=additional_text_blocks,
        image_detail=image_detail,
    )
    backend = provider_instance or llm_router.get_llm_provider(provider, deps=deps)

    if isinstance(backend, llm_router.OpenAIChatCompletionsProvider):
        response = llm_router.chat_completions_create(
            messages=resolved_messages,  # type: ignore[arg-type]
            model=model_name,
            provider=provider,
            provider_instance=backend,
            deps=deps,
            **kwargs,
        )
        return response.choices[0].message.content

    if isinstance(backend, llm_router.NativeMultimodalProvider):
        return backend.generate_multimodal(
            prompt,
            model_name=model_name,
            image_paths=[str(path) for path in image_paths or ()],
            image_urls=[str(url) for url in image_urls or ()],
            system_prompt=system_prompt,
            additional_text_blocks=[str(block) for block in additional_text_blocks or ()],
            messages=resolved_messages,
            **kwargs,
        )

    fallback_prompt = _flatten_messages_to_prompt(resolved_messages)
    return llm_router.generate_text(
        fallback_prompt,
        model_name=model_name,
        provider=provider,
        provider_instance=backend,
        deps=deps,
        **kwargs,
    )


class MultimodalRouter:
    """Thin class wrapper mirroring the ergonomic shape of ``llm_router``."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model_name: str | None = None,
        deps: RouterDeps | None = None,
        **config: object,
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self.deps = deps
        self.config = dict(config)

    def generate(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        image_paths: Sequence[str | Path] | None = None,
        image_urls: Sequence[str] | None = None,
        system_prompt: str | None = None,
        additional_text_blocks: Sequence[str] | None = None,
        messages: Sequence[dict[str, Any]] | None = None,
        **kwargs: object,
    ) -> str:
        effective_config = dict(self.config)
        effective_config.update(kwargs)
        return generate_multimodal_text(
            prompt,
            model_name=model_name or self.model_name,
            provider=self.provider,
            deps=self.deps,
            image_paths=image_paths,
            image_urls=image_urls,
            system_prompt=system_prompt,
            additional_text_blocks=additional_text_blocks,
            messages=messages,
            **effective_config,
        )


generate_text = generate_multimodal_text


__all__ = [
    "DEFAULT_IMAGE_DETAIL",
    "LLMRouterError",
    "MultimodalRouter",
    "build_image_part",
    "build_multimodal_messages",
    "build_text_part",
    "chat_completions_create",
    "clear_llm_router_caches",
    "encode_image_as_data_url",
    "generate_text",
    "generate_multimodal_text",
    "get_llm_provider",
]
