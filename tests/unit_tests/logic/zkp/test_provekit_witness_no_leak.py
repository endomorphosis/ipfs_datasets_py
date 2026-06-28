import json
import stat
import tomllib

from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    build_provekit_public_input_record,
)
from ipfs_datasets_py.logic.zkp.provekit.witness import (
    KNOWLEDGE_OF_AXIOMS_FIELD_ORDER,
    PRIVATE_WITNESS_REDACTION,
    build_knowledge_of_axioms_witness_values,
    private_witness_digest,
    provekit_witness_workspace,
    redact_private_witness_text,
    render_knowledge_of_axioms_prover_toml,
)


def test_rendered_prover_toml_contains_scalar_fields_not_private_axioms():
    private_axioms = ["private_rule(alpha)", "private_rule(alpha) -> Q"]
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=private_axioms,
    )

    toml_text = render_knowledge_of_axioms_prover_toml(record)
    parsed = tomllib.loads(toml_text)

    expected = build_knowledge_of_axioms_witness_values(record)
    assert set(parsed) == set(expected)
    for key, value in expected.items():
        assert parsed[key] == str(value)

    for axiom in private_axioms:
        assert axiom not in toml_text


def test_witness_workspace_is_private_and_cleaned_up(tmp_path):
    private_axioms = ["secret fact", "secret fact -> Q"]
    with provekit_witness_workspace(
        theorem="Q",
        private_axioms=private_axioms,
        base_dir=tmp_path,
    ) as workspace:
        workspace_dir = workspace.directory
        prover_toml_path = workspace.prover_toml_path

        assert stat.S_IMODE(tmp_path.joinpath(workspace_dir).stat().st_mode) == 0o700
        assert stat.S_IMODE(tmp_path.joinpath(prover_toml_path).stat().st_mode) == 0o600

        toml_text = tmp_path.joinpath(prover_toml_path).read_text(encoding="utf-8")
        assert "secret fact" not in toml_text
        assert workspace.private_witness_digest

    assert not tmp_path.joinpath(workspace_dir).exists()


def test_workspace_paths_and_backend_metadata_do_not_contain_private_axioms(tmp_path):
    private_axioms = ["top secret legal axiom", "top secret legal axiom -> Q"]
    with provekit_witness_workspace(
        theorem="Q",
        private_axioms=private_axioms,
        derivation_witness={"step": "top secret proof step"},
        base_dir=tmp_path,
    ) as workspace:
        metadata = workspace.to_backend_artifacts(
            prover_key_path=tmp_path / "circuit.pkp",
            verifier_key_path=tmp_path / "circuit.pkv",
            proof_path=tmp_path / "proof.np",
        )
        payload = json.dumps(metadata, sort_keys=True)
        public_payload = json.dumps(
            {
                "public_inputs": workspace.public_input_record.to_zkp_public_inputs(),
                "digest": workspace.private_witness_digest,
            },
            sort_keys=True,
        )

    for secret in [
        "top secret legal axiom",
        "top secret proof step",
    ]:
        assert secret not in payload
        assert secret not in public_payload


def test_private_witness_digest_is_deterministic_and_private_text_free():
    first = private_witness_digest(
        private_axioms=["secret alpha", "secret beta"],
        derivation_witness={"trace": ["secret alpha", "secret beta"]},
    )
    second = private_witness_digest(
        private_axioms=["secret alpha", "secret beta"],
        derivation_witness={"trace": ["secret alpha", "secret beta"]},
    )
    changed = private_witness_digest(
        private_axioms=["secret alpha", "secret gamma"],
        derivation_witness={"trace": ["secret alpha", "secret gamma"]},
    )

    assert first == second
    assert first != changed
    assert len(first) == 64
    assert "secret alpha" not in first
    assert "secret beta" not in first


def test_redact_private_witness_text_removes_axioms_and_trace_terms():
    message = "failed while handling private_rule(alpha) and trace step beta"

    redacted = redact_private_witness_text(
        message,
        ["private_rule(alpha)", "trace step beta"],
    )

    assert "private_rule(alpha)" not in redacted
    assert "trace step beta" not in redacted
    assert PRIVATE_WITNESS_REDACTION in redacted


def test_workspace_fields_match_circuit_field_order(tmp_path):
    with provekit_witness_workspace(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        base_dir=tmp_path,
    ) as workspace:
        parsed = tomllib.loads(
            tmp_path.joinpath(workspace.prover_toml_path).read_text(encoding="utf-8")
        )

    for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
        assert key in parsed
        assert f"witness_{key}" in parsed
        assert parsed[key] == parsed[f"witness_{key}"]
