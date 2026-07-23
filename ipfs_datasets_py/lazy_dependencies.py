"""Shared on-demand dependency proxy.

This module deliberately performs no dependency imports at module import time.
The first attribute access delegates to :mod:`ipfs_datasets_py.auto_installer`,
which first tries a normal import and only then performs a configured lazy
installation.
"""

from __future__ import annotations

import threading
from types import ModuleType
from typing import Iterable, Iterator, Mapping

from .auto_installer import ensure_module


DEFAULT_DEPENDENCY_MODULES: tuple[str, ...] = (
    "anthropic",
    "aiohttp",
    "aiohttp_cache",
    "bs4",
    "chardet",
    "cv2",
    "docx",
    "duckdb",
    "geopandas",
    "httpx",
    "httpx_cache",
    "intel_extension_for_pytorch",
    "ipfshttpclient",
    "ipld_car",
    "jinja2",
    "llama_cpp",
    "lxml",
    "magic",
    "markitdown",
    "multiformats",
    "nltk",
    "numpy",
    "openai",
    "openpyxl",
    "pandas",
    "PIL",
    "playsound3",
    "psutil",
    "pydantic",
    "pydocx",
    "pydub",
    "pymediainfo",
    "PyPDF2",
    "pytesseract",
    "rasterio",
    "reportlab",
    "requests",
    "requests_cache",
    "rouge",
    "selenium",
    "tiktoken",
    "torch",
    "torch.mps",
    "torch_directml",
    "tqdm",
    "whisper",
    "xformers",
    "xformers.ops",
    "yaml",
)

DEFAULT_ATTRIBUTE_ALIASES: dict[str, str] = {
    "pil": "PIL",
    "playsound": "playsound3",
    "python_docx": "docx",
}

DEFAULT_CRITICAL_DEPENDENCIES: tuple[str, ...] = (
    "tqdm",
    "yaml",
    "psutil",
    "pydantic",
)

_UNLOADED = object()


class LazyDependencyProxy:
    """Thread-safe cache that resolves third-party modules on first access."""

    def __init__(
        self,
        module_names: Iterable[str] = DEFAULT_DEPENDENCY_MODULES,
        *,
        aliases: Mapping[str, str] | None = None,
        critical_dependencies: Iterable[str] = DEFAULT_CRITICAL_DEPENDENCIES,
    ) -> None:
        names = tuple(dict.fromkeys(str(name) for name in module_names))
        self._cache: dict[str, ModuleType | None | object] = {
            name: _UNLOADED for name in names
        }
        self._aliases = dict(DEFAULT_ATTRIBUTE_ALIASES)
        if aliases:
            self._aliases.update(aliases)
        self._critical_dependencies = tuple(critical_dependencies)
        self._locks: dict[str, threading.Lock] = {
            name: threading.Lock() for name in names
        }

    def _canonical_module_name(self, name: str) -> str:
        module_name = self._aliases.get(name, name)
        if module_name not in self._cache:
            raise KeyError(f"Module '{name}' is not registered in this dependency proxy")
        return module_name

    def _load_module(self, module_name: str) -> ModuleType | None:
        module_name = self._canonical_module_name(module_name)
        cached = self._cache[module_name]
        if cached is not _UNLOADED:
            return cached  # type: ignore[return-value]

        lock = self._locks[module_name]
        with lock:
            cached = self._cache[module_name]
            if cached is _UNLOADED:
                resolved = ensure_module(module_name, required=False)
                if isinstance(resolved, ModuleType):
                    self._cache[module_name] = resolved
            cached = self._cache[module_name]
        return cached if isinstance(cached, ModuleType) else None

    def __getattr__(self, name: str) -> ModuleType | None:
        try:
            return self._load_module(name)
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, name: str) -> ModuleType | None:
        return self._load_module(name)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            module_name = self._canonical_module_name(name)
        except KeyError:
            return False
        return isinstance(self._cache[module_name], ModuleType)

    def __iter__(self) -> Iterator[tuple[str, ModuleType]]:
        for name, module in self._cache.items():
            if isinstance(module, ModuleType):
                yield name, module

    def __repr__(self) -> str:
        loaded = [name for name, module in self._cache.items() if isinstance(module, ModuleType)]
        return f"<LazyDependencyProxy loaded={loaded!r}>"

    def __str__(self) -> str:
        return "LazyDependencyProxy"

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(self._cache) | set(self._aliases))

    def keys(self) -> list[str]:
        return list(self._cache)

    def values(self) -> list[ModuleType | None]:
        return [
            module if isinstance(module, ModuleType) else None
            for module in self._cache.values()
        ]

    def items(self) -> list[tuple[str, ModuleType | None]]:
        return list(zip(self.keys(), self.values()))

    def is_loaded(self, module_name: str) -> bool:
        module_name = self._canonical_module_name(module_name)
        return isinstance(self._cache[module_name], ModuleType)

    def is_available(self, module_name: str) -> bool:
        return self._load_module(module_name) is not None

    def clear_module(self, module_name: str) -> None:
        module_name = self._canonical_module_name(module_name)
        with self._locks[module_name]:
            self._cache[module_name] = _UNLOADED

    def clear_cache(self) -> None:
        for module_name in self._cache:
            self.clear_module(module_name)

    def load_all_modules(self) -> dict[str, bool]:
        """Explicitly resolve every registered module and return availability."""

        return {
            module_name: self._load_module(module_name) is not None
            for module_name in self._cache
        }

    def check_critical_dependencies(self) -> None:
        """Resolve critical modules and raise one actionable aggregate error."""

        missing = [
            module_name
            for module_name in self._critical_dependencies
            if self._load_module(module_name) is None
        ]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ImportError(f"Critical dependencies are unavailable: {joined}")


def create_dependency_proxy(
    module_names: Iterable[str] = DEFAULT_DEPENDENCY_MODULES,
    *,
    aliases: Mapping[str, str] | None = None,
    critical_dependencies: Iterable[str] = DEFAULT_CRITICAL_DEPENDENCIES,
) -> LazyDependencyProxy:
    """Create an unloaded proxy for a subsystem."""

    return LazyDependencyProxy(
        module_names,
        aliases=aliases,
        critical_dependencies=critical_dependencies,
    )
