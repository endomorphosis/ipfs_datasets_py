"""UIR-082: documentation uses public imports and offline examples."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "ipfs_datasets_py" / "logic" / "ui_ux_ir" / "README.md"
GUIDE = ROOT / "docs" / "logic" / "UI_UX_IR_GUIDE.md"


def test_docs_exist_and_reference_public_api() -> None:
    assert README.is_file()
    assert GUIDE.is_file()
    readme = README.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    for text in (readme, guide):
        assert "decode_ui_ir" in text
        assert "canonicalize_ui_ir" in text
        assert "evaluate_ui_interaction" in text or "UIMediator" in text
        assert "offline" in text.lower() or "side-effect" in text.lower()


def test_docs_distinguish_authority_layers() -> None:
    guide = GUIDE.read_text(encoding="utf-8").lower()
    assert "declaration" in guide
    assert "projection" in guide
    assert "runtime" in guide or "mediation" in guide
    assert "proof" in guide or "formal" in guide
    assert "pixel" in guide or "semantic" in guide


def test_public_import_runs_offline() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir import public_api_manifest

    manifest = public_api_manifest()
    assert manifest["cold_import_side_effects"] is False
