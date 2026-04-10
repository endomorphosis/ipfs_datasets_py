"""Canonical legal-corpus registry for published HF datasets and local roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class CanonicalLegalCorpus:
    key: str
    display_name: str
    hf_dataset_id: str
    local_root_name: str
    jsonld_dir_name: str
    parquet_dir_name: str
    combined_parquet_filename: str
    combined_embeddings_filename: str
    cid_field: str = "ipfs_cid"
    state_field: str = "state_code"

    def default_local_root(self) -> Path:
        return (Path.home() / ".ipfs_datasets" / self.local_root_name).resolve()

    def jsonld_dir(self, output_dir: str | None = None) -> Path:
        root = Path(output_dir).expanduser().resolve() if output_dir else self.default_local_root()
        return root / self.jsonld_dir_name

    def parquet_dir(self, output_dir: str | None = None) -> Path:
        root = Path(output_dir).expanduser().resolve() if output_dir else self.default_local_root()
        return root / self.parquet_dir_name

    def state_parquet_filename(self, state_code: str) -> str:
        return f"STATE-{str(state_code).strip().upper()}.parquet"

    def preferred_parquet_names(self, state_code: str | None = None) -> List[str]:
        names: List[str] = []
        if state_code:
            names.append(self.state_parquet_filename(state_code))
        names.append(self.combined_parquet_filename)
        return names


_CORPORA: Dict[str, CanonicalLegalCorpus] = {
    "federal_register": CanonicalLegalCorpus(
        key="federal_register",
        display_name="Federal Register",
        hf_dataset_id="justicedao/ipfs_federal_register",
        local_root_name="federal_register",
        jsonld_dir_name="federal_register_jsonld",
        parquet_dir_name="federal_register_parquet",
        combined_parquet_filename="laws.parquet",
        combined_embeddings_filename="laws_embeddings.parquet",
    ),
    "state_laws": CanonicalLegalCorpus(
        key="state_laws",
        display_name="State Laws",
        hf_dataset_id="justicedao/ipfs_state_laws",
        local_root_name="state_laws",
        jsonld_dir_name="state_laws_jsonld",
        parquet_dir_name="state_laws_parquet_cid",
        combined_parquet_filename="state_laws_all_states.parquet",
        combined_embeddings_filename="state_laws_all_states_embeddings.parquet",
    ),
    "state_admin_rules": CanonicalLegalCorpus(
        key="state_admin_rules",
        display_name="State Administrative Rules",
        hf_dataset_id="justicedao/ipfs_state_admin_rules",
        local_root_name="state_admin_rules",
        jsonld_dir_name="state_admin_rules_jsonld",
        parquet_dir_name="US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid",
        combined_parquet_filename="state_admin_rules_all_states.parquet",
        combined_embeddings_filename="state_admin_rules_all_states_embeddings.parquet",
    ),
    "state_court_rules": CanonicalLegalCorpus(
        key="state_court_rules",
        display_name="State Court Rules",
        hf_dataset_id="justicedao/ipfs_court_rules",
        local_root_name="state_court_rules",
        jsonld_dir_name="state_court_rules_jsonld",
        parquet_dir_name="state_court_rules_parquet_cid",
        combined_parquet_filename="state_court_rules_all_states.parquet",
        combined_embeddings_filename="state_court_rules_all_states_embeddings.parquet",
    ),
    "netherlands_laws": CanonicalLegalCorpus(
        key="netherlands_laws",
        display_name="Netherlands Laws",
        hf_dataset_id="justicedao/ipfs_netherlands_laws",
        local_root_name="netherlands_laws",
        jsonld_dir_name="netherlands_laws_jsonld",
        parquet_dir_name="netherlands_laws_parquet_cid",
        combined_parquet_filename="netherlands_laws.parquet",
        combined_embeddings_filename="netherlands_laws_embeddings.parquet",
    ),
}


def get_canonical_legal_corpus(key: str) -> CanonicalLegalCorpus:
    normalized = str(key or "").strip().lower()
    if normalized not in _CORPORA:
        raise KeyError(f"Unknown canonical legal corpus: {key}")
    return _CORPORA[normalized]


def list_canonical_legal_corpora() -> List[CanonicalLegalCorpus]:
    return [value for _, value in sorted(_CORPORA.items())]
