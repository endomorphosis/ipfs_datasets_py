"""Batch 311: API reference generator tests."""

from __future__ import annotations

from pathlib import Path

from scripts.documentation.generate_optimizer_api_reference import generate_api_reference


def test_generate_api_reference_from_type_hints_and_docstrings(tmp_path: Path) -> None:
    module_path = tmp_path / "sample_module.py"
    module_path.write_text(
        "\n".join(
            [
                '"""Sample module summary."""',
                "",
                "def public_fn(name: str, count: int = 1) -> str:",
                '    """Public function summary."""',
                "    return name * count",
                "",
                "class Example:",
                '    """Example class summary."""',
                "",
                "    def method(self, value: float) -> float:",
                '        """Method summary."""',
                "        return value",
            ]
        ),
        encoding="utf-8",
    )

    output = tmp_path / "API.md"
    markdown = generate_api_reference([module_path], output, tmp_path)

    assert output.exists()
    assert "# Optimizers API Reference (Auto-generated)" in markdown
    assert "## sample_module.py" in markdown
    assert "`public_fn(name: str, count: int = 1) -> str`" in markdown
    assert "Public function summary." in markdown
    assert "#### `Example`" in markdown
    assert "`method(value: float) -> float`" in markdown
    assert "Method summary." in markdown
