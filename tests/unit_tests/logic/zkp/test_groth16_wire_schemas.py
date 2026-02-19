import json
from pathlib import Path


def _find_groth16_backend_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[5]
    candidates = [
        # Canonical monorepo location
        repo_root / "ipfs_datasets_py" / "ipfs_datasets_py" / "processors" / "groth16_backend",
        # Legacy/alternate location
        repo_root / "ipfs_datasets_py" / "processors" / "groth16_backend",
        # Older docs/scripts sometimes referenced this
        repo_root / "groth16_backend",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"groth16_backend directory not found (checked: {candidates})")


def test_groth16_schema_files_are_valid_json():
    schema_dir = _find_groth16_backend_dir() / "schemas"

    for name in (
        "witness_v1.schema.json",
        "proof_v1.schema.json",
        "error_envelope_v1.schema.json",
    ):
        path = schema_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "$schema" in data


def test_groth16_wire_format_doc_exists():
    doc = _find_groth16_backend_dir() / "WIRE_FORMAT.md"
    text = doc.read_text(encoding="utf-8")
    assert "wire format" in text.lower()
