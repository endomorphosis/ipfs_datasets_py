from __future__ import annotations

import pytest

from benchmarks.logic_pipeline import runtime


def test_execute_help_identifies_revision_one_diagnostic_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        runtime.main(["--help"])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "revision-1 diagnostic matrix" in output
    assert "does not produce G201/G212 revision-2 evidence" in output
