"""Canonical legal-corpus registry for published HF datasets and local roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Mapping, MutableMapping, Optional, Tuple

from .eu_legal_citation_bridge import get_eu_jurisdiction_profiles


@dataclass(frozen=True)
class CanonicalLegalCorpus:
    key: str
    display_name: str
    hf_dataset_id: str
    legal_branch: str
    country_codes: Tuple[str, ...]
    local_root_name: str
    jsonld_dir_name: str
    parquet_dir_name: str
    combined_parquet_filename: str
    combined_embeddings_filename: str
    cid_field: str = "ipfs_cid"
    state_field: str = "state_code"

    def normalized_branch(self) -> str:
        return str(self.legal_branch or "").strip().lower()

    def matches_branch(self, branch: str) -> bool:
        return self.normalized_branch() == str(branch or "").strip().lower()

    def matches_country(self, country_code: str) -> bool:
        normalized = str(country_code or "").strip().upper()
        return bool(normalized) and normalized in {value.upper() for value in self.country_codes}

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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="us",
        country_codes=("US",),
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
        legal_branch="eu",
        country_codes=("NL",),
        local_root_name="netherlands_laws",
        jsonld_dir_name="netherlands_laws_jsonld",
        parquet_dir_name="netherlands_laws_parquet_cid",
        combined_parquet_filename="netherlands_laws.parquet",
        combined_embeddings_filename="netherlands_laws_embeddings.parquet",
    ),
    "germany_laws": CanonicalLegalCorpus(
        key="germany_laws",
        display_name="Germany Laws",
        hf_dataset_id="justicedao/ipfs_germany_laws",
        legal_branch="eu",
        country_codes=("DE",),
        local_root_name="germany_laws",
        jsonld_dir_name="germany_laws_jsonld",
        parquet_dir_name="germany_laws_parquet_cid",
        combined_parquet_filename="germany_laws.parquet",
        combined_embeddings_filename="germany_laws_embeddings.parquet",
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


def infer_canonical_legal_corpus_for_dataset_id(dataset_id: str) -> CanonicalLegalCorpus:
    normalized = str(dataset_id or "").strip().lower()
    if not normalized:
        raise KeyError("Unknown canonical legal corpus dataset id: ")

    try:
        return get_canonical_legal_corpus_for_dataset_id(normalized)
    except KeyError:
        pass

    if normalized in {
        "justicedao/caselaw_access_project",
        "justicedao/dedup_ipfs_caselaw_access_project",
        "justicedao/caselaw_access_project_embeddings",
    }:
        return get_canonical_legal_corpus("caselaw_access_project")
    if normalized == "justicedao/american_municipal_law":
        return get_canonical_legal_corpus("state_laws")
    if normalized.startswith("justicedao/ipfs_germany_laws"):
        return get_canonical_legal_corpus("germany_laws")
    if normalized.startswith("justicedao/ipfs_netherlands_laws"):
        return get_canonical_legal_corpus("netherlands_laws")

    raise KeyError(f"Unknown canonical legal corpus dataset id: {dataset_id}")


def list_canonical_legal_corpora() -> List[CanonicalLegalCorpus]:
    return [value for _, value in sorted(_CORPORA.items())]


def list_canonical_legal_corpora_by_branch(branch: str) -> List[CanonicalLegalCorpus]:
    normalized = str(branch or "").strip().lower()
    return [corpus for corpus in list_canonical_legal_corpora() if corpus.matches_branch(normalized)]


def list_canonical_legal_corpora_by_country(country_code: str) -> List[CanonicalLegalCorpus]:
    normalized = str(country_code or "").strip().upper()
    return [corpus for corpus in list_canonical_legal_corpora() if corpus.matches_country(normalized)]


def build_canonical_corpus_branch_map() -> Dict[str, List[str]]:
    branch_map: Dict[str, List[str]] = {}
    for corpus in list_canonical_legal_corpora():
        branch_map.setdefault(corpus.normalized_branch(), []).append(corpus.key)
    return {branch: sorted(keys) for branch, keys in sorted(branch_map.items())}


def _slug_country_label(label: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")
    return value or "country"


def build_missing_eu_corpus_proposals(
    expected_country_codes: Optional[List[str]] = None,
) -> Dict[str, CanonicalLegalCorpus]:
    proposals: Dict[str, CanonicalLegalCorpus] = {}
    eu_profiles = get_eu_jurisdiction_profiles()
    supported_country_codes = sorted(
        str(code).strip().upper()
        for code in list(expected_country_codes or eu_profiles.keys())
        if str(code).strip() and str(code).strip().upper() != "EU"
    )
    for country_code in supported_country_codes:
        existing = [corpus for corpus in list_canonical_legal_corpora_by_country(country_code) if corpus.matches_branch("eu")]
        if existing:
            continue
        profile = dict(eu_profiles.get(country_code) or {})
        label = str(profile.get("label") or country_code)
        slug = _slug_country_label(label)
        key = f"{slug}_laws"
        proposals[country_code] = CanonicalLegalCorpus(
            key=key,
            display_name=f"{label} Laws",
            hf_dataset_id=f"justicedao/ipfs_{key}",
            legal_branch="eu",
            country_codes=(country_code,),
            local_root_name=key,
            jsonld_dir_name=f"{key}_jsonld",
            parquet_dir_name=f"{key}_parquet_cid",
            combined_parquet_filename=f"{key}.parquet",
            combined_embeddings_filename=f"{key}_embeddings.parquet",
        )
    return proposals


def infer_proposed_eu_corpus_for_dataset_id(dataset_id: str) -> CanonicalLegalCorpus:
    normalized = str(dataset_id or "").strip().lower()
    if not normalized:
        raise KeyError("Unknown proposed EU corpus dataset id: ")
    for corpus in build_missing_eu_corpus_proposals().values():
        base_dataset_id = corpus.hf_dataset_id.lower()
        if normalized == base_dataset_id or normalized.startswith(f"{base_dataset_id}_"):
            return corpus
    raise KeyError(f"Unknown proposed EU corpus dataset id: {dataset_id}")


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
