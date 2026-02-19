import pytest

from ipfs_datasets_py.logic.zkp.statement import format_circuit_ref, parse_circuit_ref


U64_MAX = (1 << 64) - 1


def test_parse_circuit_ref_valid_cases():
    assert parse_circuit_ref("knowledge_of_axioms@v0") == ("knowledge_of_axioms", 0)
    assert parse_circuit_ref("knowledge_of_axioms@v1") == ("knowledge_of_axioms", 1)
    assert parse_circuit_ref(f"c@v{U64_MAX}") == ("c", U64_MAX)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "no_version",
        "@v1",
        "c@v",
        "c@v-1",
        "c@v+1",
        "c@v1.0",
        "c@v01x",
        "c@v1@v2",
        f"c@v{U64_MAX + 1}",
        "bad@id@v1",
    ],
)
def test_parse_circuit_ref_rejects_invalid(value: str):
    with pytest.raises((ValueError, TypeError)):
        parse_circuit_ref(value)


def test_format_circuit_ref_round_trip():
    ref = format_circuit_ref("knowledge_of_axioms", 1)
    assert ref == "knowledge_of_axioms@v1"
    assert parse_circuit_ref(ref) == ("knowledge_of_axioms", 1)


@pytest.mark.parametrize(
    "circuit_id,version",
    [
        ("", 1),
        ("bad@id", 1),
        ("ok", -1),
        ("ok", U64_MAX + 1),
        ("ok", 1.5),
        ("ok", True),
    ],
)
def test_format_circuit_ref_rejects_invalid(circuit_id, version):
    with pytest.raises((ValueError, TypeError)):
        format_circuit_ref(circuit_id, version)
