"""Projection capability inventory for UI/UX IR targets.

Full web/glasses renderers remain in SwissKnife TypeScript. This module
exposes a Python-side capability inventory and loss-reporting contract so the
supervisor can discover peers without claiming projection authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

UI_UX_IR_PROJECTION_INTERFACE: Final = "UIProjection@1"

# Relative to monorepo root (lift_coding) when present.
TYPESCRIPT_PEER_RELATIVE: Final[tuple[tuple[str, str], ...]] = (
    ("codec", "swissknife/src/services/mcp/ui-ux-ir-codec.ts"),
    ("web_renderer", "swissknife/src/services/mcp/ui-ux-ir-web-renderer.ts"),
    ("glasses_adapter", "swissknife/src/services/glasses/ui-ux-ir-glasses-adapter.ts"),
    ("cross_language_test", "swissknife/test/mcp-plus-plus/ui-ux-ir-cross-language.test.ts"),
    ("codec_test", "swissknife/test/mcp-plus-plus/ui-ux-ir-codec.test.ts"),
    ("orb_mediation_test", "swissknife/test/mcp-plus-plus/ui-ux-ir-orb-mediation.test.ts"),
    ("e2e_pilots", "swissknife/test/e2e/ui-ux-ir-pilots.spec.ts"),
)

SUPPORTED_TARGET_KINDS: Final[tuple[str, ...]] = (
    "web",
    "mobile",
    "glasses",
    "voice_headless",
)


@dataclass(frozen=True, slots=True)
class ProjectionLoss:
    path: str
    reason: str
    source_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "reason": self.reason,
            "source_value": self.source_value,
        }


@dataclass(frozen=True, slots=True)
class ProjectionCapability:
    target_kind: str
    available: bool
    authority: str
    module_or_path: str = ""
    language: str = "python"
    preserves_mandatory_semantics: bool = False
    notes: tuple[str, ...] = ()
    losses: tuple[ProjectionLoss, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_kind": self.target_kind,
            "available": self.available,
            "authority": self.authority,
            "module_or_path": self.module_or_path,
            "language": self.language,
            "preserves_mandatory_semantics": self.preserves_mandatory_semantics,
            "notes": list(self.notes),
            "losses": [item.to_dict() for item in self.losses],
            "grants_execution_authority": False,
        }


def discover_typescript_peers(
    *,
    monorepo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Locate SwissKnife TS codec/renderer peers on disk when available."""
    root = Path(monorepo_root) if monorepo_root else _guess_monorepo_root()
    peers: dict[str, Any] = {}
    found = 0
    for name, rel in TYPESCRIPT_PEER_RELATIVE:
        path = root / rel if root else Path(rel)
        exists = path.is_file()
        if exists:
            found += 1
        peers[name] = {
            "path": str(path if exists else rel),
            "available": exists,
            "relative": rel,
        }
    return {
        "available": found > 0,
        "found_count": found,
        "expected_count": len(TYPESCRIPT_PEER_RELATIVE),
        "monorepo_root": str(root) if root else "",
        "peers": peers,
        "authority": "typescript_peer",
        "grants_execution_authority": False,
        "notes": [
            "SwissKnife holds browser/web/glasses projection implementations.",
            "Python remains declaration identity authority (ui-ux-ir/v1).",
        ],
    }


def _hallucinate_mediator_available() -> bool:
    try:
        import importlib

        importlib.import_module("hallucinate_app.control_surface_mediator")
        return True
    except Exception:  # noqa: BLE001
        # Also accept source layout without installed package.
        root = _guess_monorepo_root()
        if root is None:
            return False
        candidate = (
            root
            / "hallucinate_app"
            / "python"
            / "hallucinate_app"
            / "control_surface_mediator.py"
        )
        return candidate.is_file()


def _guess_monorepo_root() -> Path | None:
    # Do not rely on a fixed parent offset: this package is used both from the
    # lift_coding checkout and from standalone ipfs_datasets worktrees.
    here = Path(__file__).resolve()
    candidates = [Path.cwd(), *here.parents]
    seen: set[Path] = set()
    for root in candidates:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        if (root / "swissknife" / "src" / "services" / "mcp" / "ui-ux-ir-codec.ts").is_file():
            return root
        if (root / "external" / "ipfs_datasets").is_dir() and (
            root / "swissknife"
        ).is_dir():
            return root
    return None


def inventory_projection_capabilities(
    *,
    monorepo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return target projection inventory (Python inventory + TS peers)."""
    peers = discover_typescript_peers(monorepo_root=monorepo_root)
    peer_map = peers.get("peers") or {}

    capabilities = [
        ProjectionCapability(
            target_kind="web",
            available=True,
            authority="python+typescript",
            module_or_path="ipfs_datasets_py.logic.ui_ux_ir.projection.web",
            language="python",
            preserves_mandatory_semantics=True,
            notes=(
                "Python project_to_web emits accessible semantic models.",
                "SwissKnife ui-ux-ir-web-renderer remains browser DOM peer.",
                f"ts_peer_available={(peer_map.get('web_renderer') or {}).get('available')}",
            ),
        ),
        ProjectionCapability(
            target_kind="glasses",
            available=True,
            authority="python+typescript",
            module_or_path="ipfs_datasets_py.logic.ui_ux_ir.projection.glasses",
            language="python",
            preserves_mandatory_semantics=True,
            notes=(
                "Python project_to_glasses enforces budgets + mobile fallback.",
                "SwissKnife glasses adapter remains device peer.",
                f"ts_peer_available={(peer_map.get('glasses_adapter') or {}).get('available')}",
            ),
        ),
        ProjectionCapability(
            target_kind="mobile",
            available=True,
            authority="ipfs_datasets_py.logic.ui_ux_ir.projection.mobile",
            module_or_path="ipfs_datasets_py.logic.ui_ux_ir.projection.mobile",
            language="python",
            preserves_mandatory_semantics=True,
            notes=(
                "Mobile companion is first-class; absorbs glasses overflow.",
                "Supports text input, touch targets ≥44pt, confirmation sheets.",
            ),
        ),
        ProjectionCapability(
            target_kind="voice_headless",
            available=_hallucinate_mediator_available(),
            authority="hallucinate_app_control_surface_mediator",
            module_or_path="hallucinate_app.control_surface_mediator",
            language="python",
            preserves_mandatory_semantics=False,
            notes=(
                "Voice/headless mediation is owned by control-surface mediators,",
                "not the UIIRDocument declaration package.",
                "Parity tests: hallucinate_app/test/test_ui_ux_ir_policy_parity.py",
            ),
            losses=(
                ()
                if _hallucinate_mediator_available()
                else (
                    ProjectionLoss(
                        path="voice_headless",
                        reason="mediation_module_unavailable",
                    ),
                )
            ),
        ),
        ProjectionCapability(
            target_kind="declaration_identity",
            available=True,
            authority="ipfs_datasets_py.logic.ui_ux_ir",
            module_or_path="ipfs_datasets_py.logic.ui_ux_ir",
            language="python",
            preserves_mandatory_semantics=True,
            notes=(
                "Python owns decode/canonicalize/identity for ui-ux-ir/v1.",
                "Does not project pixels or grant execution.",
            ),
        ),
    ]

    return {
        "interface": UI_UX_IR_PROJECTION_INTERFACE,
        "schema": "ipfs_datasets_py/logic/ui_ux_ir/projection-inventory@1",
        "supported_target_kinds": list(SUPPORTED_TARGET_KINDS),
        "capabilities": [item.to_dict() for item in capabilities],
        "typescript_peers": peers,
        "available": True,
        "grants_execution_authority": False,
        "notes": [
            "Projection inventory is non-authoritative discovery.",
            "Cross-language identity uses tests/fixtures/ui_ux_ir/v1/golden_vectors.json.",
        ],
    }


__all__ = [
    "SUPPORTED_TARGET_KINDS",
    "TYPESCRIPT_PEER_RELATIVE",
    "UI_UX_IR_PROJECTION_INTERFACE",
    "ProjectionCapability",
    "ProjectionLoss",
    "discover_typescript_peers",
    "inventory_projection_capabilities",
]
