"""UIR-071: responsive web and mobile form pilot."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "pilots"
    / "responsive_form.json"
)


def test_responsive_form_preserves_semantic_fields_across_layouts() -> None:
    pilot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert pilot["pilot_id"] == "responsive-form-v1"
    fields = set(pilot["fields"])
    actions = set(pilot["actions"])
    assert fields == {"email", "name", "consent"}
    assert "submit" in actions

    # Layout may differ; field set, a11y relationships, and actions must not.
    a11y = pilot["accessibility"]
    for field in fields | {"submit"}:
        assert field in a11y
        assert a11y[field]["role"]
        assert a11y[field]["label"]

    assert pilot["web_layout"] != pilot["mobile_layout"]
    # Same validation/error states advertised for both targets.
    assert "error" in pilot["states"] and "success" in pilot["states"]
