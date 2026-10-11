"""Native Lake checks of comment-only Unicode with exact source replay.

The candidates are authored test fixtures. A build checks generated types and
definitions; it does not establish learned accuracy or Python equivalence.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as lake
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression


def test_real_lake_build_preserves_unicode_comment_source_identity(tmp_path):
    executables = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not executables:
        pytest.skip("Installed native Lake unavailable; no download attempted")
    operands = ("expr:left", "expr:right")
    candidate = dict(kind="program_expression", document=ProgramExpression(
        "expr:result", "binary", "integer", operand_ids=operands,
        evaluation_order=operands, operator="+", source_ref_ids=("source",)).to_dict())
    rows = []
    for index, newline in enumerate(("\n", "\r\n", "\r")):
        for temporary in (False, True):
            body = ("    answer = left + right  # somme λ\n    return answer\n" if temporary
                    else "    return left + right  # somme λ\n")
            text = "# café 😀\u2028still a comment\ndef compute(left: int, right: int) -> int:\n" + body
            rows.append(dict(id=f"newline-{index}-temporary-{temporary}",
                             source_text=text.replace("\n", newline), candidate_ir=deepcopy(candidate)))
    saved = deepcopy(rows)
    handle = lake.build_source_program_lake(rows, lake_executable=executables[-1],
                                           output_directory=tmp_path / "native-lake")
    receipt = lake.verify_source_program_lake(handle, rows)
    assert rows == saved
    assert receipt["status"] == "passed", receipt["execution"]
    assert receipt["backend_executed"] and receipt["all_candidates_compiled"]
    assert receipt["supported_count"] == receipt["count"] == 6
    assert receipt["tool_binary_sha256"]
    assert all(receipt[key] is False for key in lake.FALSE)
    assert all(row["source_qualification"]["qualified"] and row["lake_status"] == "passed"
               for row in receipt["rows"])
    changed = deepcopy(rows)
    changed[0]["source_text"] = changed[0]["source_text"].replace("café", "cafe")
    with pytest.raises(ValueError, match="input identity"):
        lake.verify_source_program_lake(handle, changed)
