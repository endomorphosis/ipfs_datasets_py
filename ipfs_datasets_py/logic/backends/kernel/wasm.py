"""WASM and dual-plane capability probing for kernel-checking backends.

Native Lean/Rocq kernels and browser/WASM-compatible runtimes are deliberately
separate capability planes.  A successful native probe must never imply WASM
availability, and a real WASM absence is reported explicitly rather than
omitted or collapsed into a single ``available`` flag.

This module is the shared capability surface used by
:mod:`~ipfs_datasets_py.logic.backends.kernel.lean` and
:mod:`~ipfs_datasets_py.logic.backends.kernel.rocq`.  It does not install
toolchains, download WASM modules, or treat an unprobed plane as ready.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ...ir_core.claims import FrozenMap, stable_digest

WASM_KERNEL_CAPABILITY_VERSION: Final = "WasmKernelCapability@1"
KERNEL_CAPABILITY_STATE_VERSION: Final = "kernel-capability-state/v1"
DUAL_PLANE_CAPABILITY_VERSION: Final = "dual-plane-kernel-capability/v1"
KERNEL_DIAGNOSTIC_VERSION: Final = "kernel-diagnostic/v1"

DEFAULT_MAX_DIAGNOSTIC_CHARS: Final = 512
DEFAULT_MAX_DIAGNOSTICS: Final = 32
DEFAULT_MAX_SOURCE_BYTES: Final = 1_048_576

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class KernelCapabilityError(ValueError):
    """Raised when a capability or diagnostic contract is violated."""


class CapabilityPlane(StrEnum):
    """Execution planes that must not be collapsed into each other."""

    NATIVE = "native"
    WASM = "wasm"
    BROWSER = "browser"


class CapabilityAvailability(StrEnum):
    """Closed availability vocabulary for a single plane."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNPROBED = "unprobed"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise KernelCapabilityError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise KernelCapabilityError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _frozen(value: Mapping[str, Any] | FrozenMap, field_name: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise KernelCapabilityError(
            f"{field_name} must contain immutable JSON-compatible data"
        ) from error


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise KernelCapabilityError(
            f"{field_name} must be one of {choices}"
        ) from error


def content_digest(content: str) -> str:
    """Stable digest for theorem/proof/source text."""

    if not isinstance(content, str) or "\x00" in content:
        raise KernelCapabilityError("content must be text without NUL bytes")
    return stable_digest({"content": content})


def sanitize_diagnostic(
    value: object,
    *,
    max_chars: int = DEFAULT_MAX_DIAGNOSTIC_CHARS,
) -> str:
    """Return an inert, bounded diagnostic string.

    Diagnostics are for humans and auditors.  They never carry shell
    metacharacters that would be unsafe to re-emit into logs or receipts, and
    they are truncated so an adversarial kernel cannot flood the result.
    """

    if not isinstance(value, str):
        value = str(value)
    cleaned = _CONTROL.sub(" ", value)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return ""
    if max_chars < 16:
        raise KernelCapabilityError("max_chars must be at least 16")
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def bound_diagnostics(
    values: Sequence[object] | object,
    *,
    max_items: int = DEFAULT_MAX_DIAGNOSTICS,
    max_chars: int = DEFAULT_MAX_DIAGNOSTIC_CHARS,
) -> tuple[str, ...]:
    """Normalize a diagnostic sequence into a unique, ordered, bounded tuple."""

    if isinstance(values, (str, bytes, bytearray)):
        values = (values,)
    if not isinstance(values, Sequence):
        raise KernelCapabilityError("diagnostics must be a sequence")
    if max_items < 1:
        raise KernelCapabilityError("max_items must be positive")
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = sanitize_diagnostic(item, max_chars=max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return tuple(result)


@dataclass(frozen=True, slots=True)
class KernelCapabilityState:
    """Capability facts for exactly one execution plane."""

    plane: CapabilityPlane
    availability: CapabilityAvailability
    kernel_id: str
    reason: str = ""
    executable: str = ""
    module_id: str = ""
    version: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = KERNEL_CAPABILITY_STATE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "plane", _enum(self.plane, CapabilityPlane, "plane"))
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, CapabilityAvailability, "availability"),
        )
        object.__setattr__(self, "kernel_id", _text(self.kernel_id, "kernel_id"))
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self, "executable", _text(self.executable, "executable", optional=True)
        )
        object.__setattr__(
            self, "module_id", _text(self.module_id, "module_id", optional=True)
        )
        object.__setattr__(
            self, "version", _text(self.version, "version", optional=True)
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != KERNEL_CAPABILITY_STATE_VERSION:
            raise KernelCapabilityError(
                f"unsupported capability state schema: {self.schema_version!r}"
            )
        if self.availability is CapabilityAvailability.AVAILABLE:
            if self.plane is CapabilityPlane.NATIVE and not self.executable:
                raise KernelCapabilityError(
                    "native available state requires an executable path or name"
                )
            if self.plane in {CapabilityPlane.WASM, CapabilityPlane.BROWSER} and (
                not self.module_id and not self.executable
            ):
                raise KernelCapabilityError(
                    "wasm/browser available state requires module_id or executable"
                )
            if self.reason:
                raise KernelCapabilityError(
                    "available capability state must not carry an unavailability reason"
                )
        elif self.availability is CapabilityAvailability.UNPROBED:
            if self.reason:
                raise KernelCapabilityError(
                    "unprobed capability state must not invent an unavailability reason"
                )
        else:
            if not self.reason:
                raise KernelCapabilityError(
                    f"{self.availability.value} capability state requires an explicit reason"
                )

    @property
    def available(self) -> bool:
        return self.availability is CapabilityAvailability.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "available": self.available,
            "executable": self.executable,
            "kernel_id": self.kernel_id,
            "metadata": self.metadata.to_dict(),
            "module_id": self.module_id,
            "plane": self.plane.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def available_native(
        cls,
        *,
        kernel_id: str,
        executable: str,
        version: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> KernelCapabilityState:
        return cls(
            plane=CapabilityPlane.NATIVE,
            availability=CapabilityAvailability.AVAILABLE,
            kernel_id=kernel_id,
            executable=executable,
            version=version,
            metadata=FrozenMap(metadata or {}),
        )

    @classmethod
    def unavailable(
        cls,
        *,
        plane: CapabilityPlane | str,
        kernel_id: str,
        reason: str,
        executable: str = "",
        module_id: str = "",
        version: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> KernelCapabilityState:
        return cls(
            plane=plane,
            availability=CapabilityAvailability.UNAVAILABLE,
            kernel_id=kernel_id,
            reason=sanitize_diagnostic(reason) or "unavailable",
            executable=executable,
            module_id=module_id,
            version=version,
            metadata=FrozenMap(metadata or {}),
        )

    @classmethod
    def unsupported(
        cls,
        *,
        plane: CapabilityPlane | str,
        kernel_id: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> KernelCapabilityState:
        return cls(
            plane=plane,
            availability=CapabilityAvailability.UNSUPPORTED,
            kernel_id=kernel_id,
            reason=sanitize_diagnostic(reason) or "unsupported",
            metadata=FrozenMap(metadata or {}),
        )

    @classmethod
    def unprobed(
        cls,
        *,
        plane: CapabilityPlane | str,
        kernel_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> KernelCapabilityState:
        return cls(
            plane=plane,
            availability=CapabilityAvailability.UNPROBED,
            kernel_id=kernel_id,
            metadata=FrozenMap(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class DualPlaneCapability:
    """Native and WASM/browser capability states kept strictly separate."""

    kernel_id: str
    native: KernelCapabilityState
    wasm: KernelCapabilityState
    browser: KernelCapabilityState | None = None
    interface_version: str = DUAL_PLANE_CAPABILITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kernel_id", _text(self.kernel_id, "kernel_id"))
        if not isinstance(self.native, KernelCapabilityState):
            raise KernelCapabilityError("native must be a KernelCapabilityState")
        if not isinstance(self.wasm, KernelCapabilityState):
            raise KernelCapabilityError("wasm must be a KernelCapabilityState")
        if self.native.plane is not CapabilityPlane.NATIVE:
            raise KernelCapabilityError("native plane state must use plane=native")
        if self.wasm.plane is not CapabilityPlane.WASM:
            raise KernelCapabilityError("wasm plane state must use plane=wasm")
        if self.native.kernel_id != self.kernel_id or self.wasm.kernel_id != self.kernel_id:
            raise KernelCapabilityError("capability plane kernel_id must match dual-plane kernel_id")
        if self.browser is not None:
            if not isinstance(self.browser, KernelCapabilityState):
                raise KernelCapabilityError("browser must be a KernelCapabilityState")
            if self.browser.plane is not CapabilityPlane.BROWSER:
                raise KernelCapabilityError(
                    "browser plane state must use plane=browser"
                )
            if self.browser.kernel_id != self.kernel_id:
                raise KernelCapabilityError(
                    "browser plane kernel_id must match dual-plane kernel_id"
                )
        if self.interface_version != DUAL_PLANE_CAPABILITY_VERSION:
            raise KernelCapabilityError(
                f"unsupported dual-plane capability interface: {self.interface_version!r}"
            )

    @property
    def native_available(self) -> bool:
        return self.native.available

    @property
    def wasm_available(self) -> bool:
        return self.wasm.available

    @property
    def any_available(self) -> bool:
        return self.native_available or self.wasm_available or (
            self.browser is not None and self.browser.available
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "browser": self.browser.to_dict() if self.browser is not None else None,
            "interface_version": self.interface_version,
            "kernel_id": self.kernel_id,
            "native": self.native.to_dict(),
            "native_available": self.native_available,
            "wasm": self.wasm.to_dict(),
            "wasm_available": self.wasm_available,
        }


WasmModuleLocator = Callable[[str], str | None]


def default_wasm_module_locator(module_id: str) -> str | None:
    """Default locator: no bundled WASM modules are shipped with this package.

    Real absence is explicit.  Callers that embed browser runtimes must inject
    a locator that returns a resolvable module path or URL.
    """

    _ = module_id
    return None


@dataclass(frozen=True, slots=True)
class WasmCapabilityProbe:
    """Side-effect-free probe for WASM/browser-compatible kernel modules."""

    interface_version: str = WASM_KERNEL_CAPABILITY_VERSION
    module_locator: WasmModuleLocator | None = None
    supported_module_ids: tuple[str, ...] = (
        "lean4-wasm",
        "rocq-wasm",
        "coq-wasm",
    )

    def __post_init__(self) -> None:
        if self.interface_version != WASM_KERNEL_CAPABILITY_VERSION:
            raise KernelCapabilityError(
                f"unsupported WASM capability interface: {self.interface_version!r}"
            )
        if self.module_locator is not None and not callable(self.module_locator):
            raise KernelCapabilityError("module_locator must be callable")
        modules = tuple(
            _text(item, "supported_module_ids item") for item in self.supported_module_ids
        )
        if len(modules) != len(set(modules)):
            raise KernelCapabilityError("supported_module_ids must not contain duplicates")
        object.__setattr__(self, "supported_module_ids", modules)

    def _locate(self, module_id: str) -> str | None:
        locator = self.module_locator or default_wasm_module_locator
        try:
            located = locator(module_id)
        except Exception as error:  # noqa: BLE001 - probe is fail-closed
            raise KernelCapabilityError(
                f"WASM module locator failed for {module_id!r}: {error}"
            ) from error
        if located is None:
            return None
        if not isinstance(located, str) or not located.strip() or "\x00" in located:
            raise KernelCapabilityError(
                f"WASM module locator returned an invalid path for {module_id!r}"
            )
        return located.strip()

    def probe(
        self,
        *,
        kernel_id: str,
        module_id: str,
        plane: CapabilityPlane | str = CapabilityPlane.WASM,
    ) -> KernelCapabilityState:
        """Probe one WASM/browser module without installing or executing it."""

        resolved_plane = _enum(plane, CapabilityPlane, "plane")
        if resolved_plane is CapabilityPlane.NATIVE:
            raise KernelCapabilityError(
                "WasmCapabilityProbe cannot report native plane availability"
            )
        kernel = _text(kernel_id, "kernel_id")
        module = _text(module_id, "module_id")
        if module not in self.supported_module_ids:
            return KernelCapabilityState.unsupported(
                plane=resolved_plane,
                kernel_id=kernel,
                reason=(
                    f"WASM module {module!r} is not in the reviewed support set "
                    f"({', '.join(self.supported_module_ids)})"
                ),
                metadata={"requested_module_id": module},
            )
        located = self._locate(module)
        if located is None:
            return KernelCapabilityState.unavailable(
                plane=resolved_plane,
                kernel_id=kernel,
                reason=(
                    f"WASM module {module!r} is explicitly absent: no bundled or "
                    "injected module was resolvable for this runtime"
                ),
                module_id=module,
                metadata={
                    "explicit_absence": True,
                    "requested_module_id": module,
                },
            )
        return KernelCapabilityState(
            plane=resolved_plane,
            availability=CapabilityAvailability.AVAILABLE,
            kernel_id=kernel,
            module_id=module,
            executable=located,
            metadata=FrozenMap(
                {
                    "explicit_absence": False,
                    "located_module": located,
                    "requested_module_id": module,
                }
            ),
        )

    def probe_kernel(
        self,
        *,
        kernel_id: str,
        preferred_module_ids: Sequence[str],
        plane: CapabilityPlane | str = CapabilityPlane.WASM,
    ) -> KernelCapabilityState:
        """Probe preferred modules in order; report explicit absence if none resolve."""

        last: KernelCapabilityState | None = None
        for module_id in preferred_module_ids:
            state = self.probe(
                kernel_id=kernel_id, module_id=module_id, plane=plane
            )
            if state.available:
                return state
            last = state
        if last is not None:
            return last
        return KernelCapabilityState.unavailable(
            plane=plane,
            kernel_id=kernel_id,
            reason="no WASM modules were requested for probing",
            metadata={"explicit_absence": True},
        )


@dataclass(frozen=True, slots=True)
class KernelTranslationBinding:
    """Loss-aware binding from a software-verification translation to a kernel source."""

    translation_id: str
    translation_digest: str
    source_family: str
    target_family: str
    fidelity: str = "exact"
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "translation_id", _text(self.translation_id, "translation_id")
        )
        object.__setattr__(
            self,
            "translation_digest",
            _digest(self.translation_digest, "translation_digest"),
        )
        object.__setattr__(
            self, "source_family", _text(self.source_family, "source_family")
        )
        object.__setattr__(
            self, "target_family", _text(self.target_family, "target_family")
        )
        object.__setattr__(self, "fidelity", _text(self.fidelity, "fidelity"))
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fidelity": self.fidelity,
            "metadata": self.metadata.to_dict(),
            "source_family": self.source_family,
            "target_family": self.target_family,
            "translation_digest": self.translation_digest,
            "translation_id": self.translation_id,
        }


@dataclass(frozen=True, slots=True)
class KernelSourceTreeBinding:
    """Identity of the exact source tree used for one kernel check."""

    tree_id: str
    root_digest: str
    files: FrozenMap
    primary_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _text(self.tree_id, "tree_id"))
        object.__setattr__(
            self, "root_digest", _digest(self.root_digest, "root_digest")
        )
        object.__setattr__(self, "files", _frozen(self.files, "files"))
        if not self.files:
            raise KernelCapabilityError("source tree must list at least one file digest")
        for path, digest in self.files.to_dict().items():
            _text(path, "source tree path")
            _digest(digest, f"source tree digest for {path}")
        object.__setattr__(
            self, "primary_path", _text(self.primary_path, "primary_path")
        )
        if self.primary_path not in self.files:
            raise KernelCapabilityError(
                "primary_path must be present in the source tree file map"
            )

    @classmethod
    def from_files(
        cls,
        files: Mapping[str, str],
        *,
        primary_path: str,
        tree_id: str = "",
    ) -> KernelSourceTreeBinding:
        normalized = {
            _text(path, "source tree path"): content_digest(content)
            for path, content in files.items()
        }
        root = stable_digest({"files": normalized, "primary_path": primary_path})
        return cls(
            tree_id=tree_id or f"source-tree:{root[:24]}",
            root_digest=root,
            files=FrozenMap(normalized),
            primary_path=primary_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files.to_dict(),
            "primary_path": self.primary_path,
            "root_digest": self.root_digest,
            "tree_id": self.tree_id,
        }


@dataclass(frozen=True, slots=True)
class KernelToolchainBinding:
    """Pinned toolchain identity used for one kernel check."""

    toolchain_id: str
    kernel_id: str
    plane: CapabilityPlane
    executable: str = ""
    module_id: str = ""
    version: str = ""
    command_template: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "toolchain_id", _text(self.toolchain_id, "toolchain_id")
        )
        object.__setattr__(self, "kernel_id", _text(self.kernel_id, "kernel_id"))
        object.__setattr__(self, "plane", _enum(self.plane, CapabilityPlane, "plane"))
        object.__setattr__(
            self, "executable", _text(self.executable, "executable", optional=True)
        )
        object.__setattr__(
            self, "module_id", _text(self.module_id, "module_id", optional=True)
        )
        object.__setattr__(
            self, "version", _text(self.version, "version", optional=True)
        )
        object.__setattr__(
            self,
            "command_template",
            _text(self.command_template, "command_template", optional=True),
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.plane is CapabilityPlane.NATIVE and not self.executable:
            raise KernelCapabilityError(
                "native toolchain binding requires an executable"
            )
        if self.plane is not CapabilityPlane.NATIVE and not (
            self.module_id or self.executable
        ):
            raise KernelCapabilityError(
                "non-native toolchain binding requires module_id or executable"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_template": self.command_template,
            "executable": self.executable,
            "kernel_id": self.kernel_id,
            "metadata": self.metadata.to_dict(),
            "module_id": self.module_id,
            "plane": self.plane.value,
            "toolchain_id": self.toolchain_id,
            "version": self.version,
        }


__all__ = [
    "CapabilityAvailability",
    "CapabilityPlane",
    "DEFAULT_MAX_DIAGNOSTIC_CHARS",
    "DEFAULT_MAX_DIAGNOSTICS",
    "DEFAULT_MAX_SOURCE_BYTES",
    "DUAL_PLANE_CAPABILITY_VERSION",
    "DualPlaneCapability",
    "KERNEL_CAPABILITY_STATE_VERSION",
    "KERNEL_DIAGNOSTIC_VERSION",
    "KernelCapabilityError",
    "KernelCapabilityState",
    "KernelSourceTreeBinding",
    "KernelToolchainBinding",
    "KernelTranslationBinding",
    "WASM_KERNEL_CAPABILITY_VERSION",
    "WasmCapabilityProbe",
    "bound_diagnostics",
    "content_digest",
    "default_wasm_module_locator",
    "sanitize_diagnostic",
]
