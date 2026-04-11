"""Canonical legal-corpus registry for published HF datasets and local roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional


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

    def combined_parquet_path(self) -> str:
        prefix = self.parquet_dir_name.strip("/")
        if not prefix:
            return self.combined_parquet_filename
        return f"{prefix}/{self.combined_parquet_filename}"

    def combined_embeddings_path(self) -> str:
        prefix = self.parquet_dir_name.strip("/")
        if not prefix:
            return self.combined_embeddings_filename
        return f"{prefix}/{self.combined_embeddings_filename}"


_CORPORA: Dict[str, CanonicalLegalCorpus] = {
    "caselaw_access_project": CanonicalLegalCorpus(
        key="caselaw_access_project",
        display_name="Caselaw Access Project",
        hf_dataset_id="justicedao/ipfs_caselaw_access_project",
        local_root_name="caselaw_access_project",
        jsonld_dir_name="caselaw_access_project_jsonld",
        parquet_dir_name="embeddings",
        combined_parquet_filename="ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
        combined_embeddings_filename="sparse_chunks.parquet",
        cid_field="id",
        state_field="jurisdiction",
    ),
    "us_code": CanonicalLegalCorpus(
        key="us_code",
        display_name="United States Code",
        hf_dataset_id="justicedao/ipfs_uscode",
        local_root_name="uscode",
        jsonld_dir_name="uscode_jsonld",
        parquet_dir_name="uscode_parquet",
        combined_parquet_filename="uscode.parquet",
        combined_embeddings_filename="uscode_embeddings.parquet",
        cid_field="cid",
        state_field="jurisdiction",
    ),
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


def get_canonical_legal_corpus_for_dataset_id(dataset_id: str) -> CanonicalLegalCorpus:
    normalized = str(dataset_id or "").strip().lower()
    for corpus in _CORPORA.values():
        if corpus.hf_dataset_id.lower() == normalized:
            return corpus
    raise KeyError(f"Unknown canonical legal corpus dataset id: {dataset_id}")


def list_canonical_legal_corpora() -> List[CanonicalLegalCorpus]:
    return [value for _, value in sorted(_CORPORA.items())]


def build_canonical_corpus_local_root_overrides(
    *,
    env: Optional[Mapping[str, str]] = None,
    env_var_by_corpus_key: Optional[Mapping[str, str]] = None,
    prefix: str = "IPFS_DATASETS_",
    suffix: str = "_ROOT",
    data_root_env_name: Optional[str] = None,
) -> Dict[str, str]:
    source = env or {}
    overrides: MutableMapping[str, str] = {}
    shared_data_root = str(source.get(data_root_env_name or "", "")).strip() if data_root_env_name else ""
    shared_data_root_path = Path(shared_data_root).expanduser().resolve() if shared_data_root else None

    for corpus in list_canonical_legal_corpora():
        env_name = None
        if env_var_by_corpus_key is not None:
            env_name = env_var_by_corpus_key.get(corpus.key)
        if not env_name:
            env_name = f"{prefix}{corpus.key.upper()}{suffix}"
        value = str(source.get(env_name, "")).strip()
        if value:
            overrides[corpus.key] = value
            continue
        if shared_data_root_path is not None:
            overrides[corpus.key] = str((shared_data_root_path / corpus.local_root_name / corpus.parquet_dir_name).resolve())

    return dict(overrides)
