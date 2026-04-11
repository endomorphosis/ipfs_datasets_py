"""Retrieval planning tactics for proof-oriented legal reasoning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Sequence


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


@dataclass
class ProofSearchSource:
    """A candidate evidence source for satisfying a proof obligation."""

    source_id: str
    source_type: str
    label: str
    priority: int
    rationale: str
    query_hints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProofSearchPlan:
    """Ordered search plan for a proof work item."""

    plan_id: str
    work_item_id: str
    party: str
    objective: str
    recommended_route: List[str] = field(default_factory=list)
    selected_starting_source_id: str = ""
    selected_starting_source_type: str = ""
    search_stages: List[Dict[str, Any]] = field(default_factory=list)
    proof_gap_focus: List[str] = field(default_factory=list)
    candidate_sources: List[ProofSearchSource] = field(default_factory=list)
    escalation_policy: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "work_item_id": self.work_item_id,
            "party": self.party,
            "objective": self.objective,
            "recommended_route": list(self.recommended_route),
            "selected_starting_source_id": self.selected_starting_source_id,
            "selected_starting_source_type": self.selected_starting_source_type,
            "search_stages": [dict(stage) for stage in self.search_stages],
            "proof_gap_focus": list(self.proof_gap_focus),
            "candidate_sources": [source.to_dict() for source in self.candidate_sources],
            "escalation_policy": dict(self.escalation_policy),
        }


class ProofTactician:
    """Choose where a proof assistant should search for supporting evidence."""

    def build_search_plan(
        self,
        *,
        dataset_id: str,
        docket_id: str,
        work_item: Dict[str, Any],
        documents: Sequence[Any],
        authorities: Sequence[Dict[str, Any]],
        bm25_index: Dict[str, Any] | None = None,
        vector_index: Dict[str, Any] | None = None,
    ) -> ProofSearchPlan:
        work_item_id = str(work_item.get("work_item_id") or "")
        party = str(work_item.get("party") or "all")
        title = str(work_item.get("title") or work_item.get("action") or "proof task")
        objective = f"Find sources to prove or refute: {title}"
        candidate_sources: List[ProofSearchSource] = []
        authority_summary = self._summarize_authorities(authorities)

        local_query_hints = self._query_hints(work_item)
        if documents:
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:local:docket_documents",
                    source_type="local_docket_documents",
                    label="Local docket documents",
                    priority=1,
                    rationale="Primary record evidence should come from locally imported docket filings first.",
                    query_hints=local_query_hints,
                    metadata={"document_count": len(documents), "docket_id": docket_id},
                )
            )
        if bm25_index and bm25_index.get("document_count"):
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:local:bm25",
                    source_type="local_bm25_index",
                    label="Local BM25 docket index",
                    priority=2,
                    rationale="Use lexical retrieval when the obligation language appears verbatim in filings.",
                    query_hints=local_query_hints,
                    metadata={"document_count": bm25_index.get("document_count")},
                )
            )
        if vector_index and vector_index.get("document_count"):
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:local:vector",
                    source_type="local_vector_index",
                    label="Local vector docket index",
                    priority=3,
                    rationale="Use semantic retrieval when the filing language is paraphrased or distributed across documents.",
                    query_hints=local_query_hints,
                    metadata={"document_count": vector_index.get("document_count")},
                )
            )
        if authorities:
            authority_rationale = "Authorities on the docket often define the controlling duty, prohibition, or deadline."
            if authority_summary["linked_citation_count"]:
                authority_rationale += " Linked citations already tie some authorities to parser-backed legal corpora and official source records."
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:local:authorities",
                    source_type="authority_list",
                    label="Authorities attached to docket dataset",
                    priority=4,
                    rationale=authority_rationale,
                    query_hints=local_query_hints,
                    metadata=authority_summary,
                )
            )

        parser_sources = [
            (
                "legal_dataset_api",
                "Legal dataset parsers",
                "Use legal dataset parsers when the proof requires statutes, rules, or scraped corpora beyond the local docket.",
                5,
                [
                    "ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api",
                    "ipfs_datasets_py.processors.legal_scrapers.knowledge_base_loader",
                    "ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora",
                ],
            ),
            (
                "recap_archive_scraper",
                "RECAP and archive parsers",
                "Use docket-adjacent parsers when a local filing references missing docket entries or archive-backed case materials.",
                6,
                [
                    "ipfs_datasets_py.processors.legal_scrapers.recap_archive_scraper",
                    "ipfs_datasets_py.processors.legal_scrapers.legal_web_archive_search",
                ],
            ),
            (
                "multiengine_legal_search",
                "Legal search orchestration",
                "Use legal search orchestrators when parser-backed corpora do not satisfy the proof burden.",
                7,
                [
                    "ipfs_datasets_py.processors.legal_scrapers.multi_engine_legal_search",
                    "ipfs_datasets_py.processors.legal_scrapers.brave_legal_search",
                    "ipfs_datasets_py.processors.legal_scrapers.query_processor",
                ],
            ),
        ]
        for source_id, label, rationale, priority, modules in parser_sources:
            parser_metadata = {"modules": modules}
            if authority_summary["linked_citation_count"]:
                routing_evidence = list(authority_summary.get("routing_evidence") or [])
                routing_reason = ""
                if routing_evidence:
                    primary = routing_evidence[0]
                    primary_citation = str(primary.get("citation_text") or "a linked citation")
                    primary_corpora = [str(item) for item in list(primary.get("corpus_priority") or []) if str(item).strip()]
                    primary_source_url = str(primary.get("source_url") or "").strip()
                    primary_source_cid = str(primary.get("source_cid") or "").strip()
                    source_fragment = ""
                    if primary_source_url:
                        source_fragment = f" Official source: {primary_source_url}."
                    elif primary_source_cid:
                        source_fragment = f" Source CID: {primary_source_cid}."
                    if primary_corpora:
                        routing_reason = (
                            f"Preferred parser corpora were ranked from linked citation '{primary_citation}', "
                            f"which points first to '{primary_corpora[0]}'.{source_fragment}"
                        )
                parser_metadata.update(
                    {
                        "preferred_corpus_keys": list(authority_summary["linked_corpus_keys"]),
                        "preferred_corpus_priority": list(authority_summary["linked_corpus_priority"]),
                        "preferred_dataset_ids": list(authority_summary["linked_dataset_ids"]),
                        "preferred_dataset_priority": list(authority_summary["linked_dataset_priority"]),
                        "preferred_state_codes": list(authority_summary["preferred_state_codes"]),
                        "routing_evidence": routing_evidence,
                        "routing_reason": routing_reason,
                        "authority_backed": True,
                    }
                )
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:parser:{source_id}",
                    source_type="legal_dataset_parser",
                    label=label,
                    priority=priority,
                    rationale=rationale,
                    query_hints=local_query_hints,
                    metadata=parser_metadata,
                )
            )

        engine_sources = [
            (
                "web_search",
                "Search-engine fallback",
                "Escalate to search engines only after local documents and legal parsers fail to supply enough support.",
                8,
                [
                    "ipfs_datasets_py.processors.web_archiving.search_engines.orchestrator",
                    "ipfs_datasets_py.processors.web_archiving.brave_search_engine",
                    "ipfs_datasets_py.processors.web_archiving.google_search_engine",
                ],
            ),
            (
                "web_archive",
                "Web archive fallback",
                "Use archives when cited authorities or filings have moved or disappeared from primary hosts.",
                9,
                [
                    "ipfs_datasets_py.processors.web_archiving.archive_is_engine",
                    "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine",
                ],
            ),
        ]
        for source_id, label, rationale, priority, modules in engine_sources:
            candidate_sources.append(
                ProofSearchSource(
                    source_id=f"{dataset_id}:engine:{source_id}",
                    source_type="search_engine",
                    label=label,
                    priority=priority,
                    rationale=rationale,
                    query_hints=local_query_hints,
                    metadata={"modules": modules},
                )
            )

        candidate_sources.sort(key=lambda item: item.priority)
        starting_source = self._select_starting_source(candidate_sources, work_item)
        search_stages = self._build_search_stages(candidate_sources)
        proof_gap_focus = self._proof_gap_focus(work_item)
        return ProofSearchPlan(
            plan_id=f"{dataset_id}:plan:{_safe_identifier(work_item_id)}",
            work_item_id=work_item_id,
            party=party,
            objective=objective,
            recommended_route=[source.source_type for source in candidate_sources],
            selected_starting_source_id=starting_source.source_id if starting_source else "",
            selected_starting_source_type=starting_source.source_type if starting_source else "",
            search_stages=search_stages,
            proof_gap_focus=proof_gap_focus,
            candidate_sources=candidate_sources,
            escalation_policy={
                "start_with_local_documents": True,
                "use_parsers_if_local_support_is_insufficient": True,
                "use_search_engines_as_last_resort": True,
                "proof_standard": "prefer local docket evidence, then structured legal corpora, then web search fallback",
            },
        )

    def build_tactician_manifest(
        self,
        *,
        dataset_id: str,
        docket_id: str,
        agenda: Sequence[Dict[str, Any]],
        documents: Sequence[Any],
        authorities: Sequence[Dict[str, Any]],
        bm25_index: Dict[str, Any] | None = None,
        vector_index: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        plans = [
            self.build_search_plan(
                dataset_id=dataset_id,
                docket_id=docket_id,
                work_item=item,
                documents=documents,
                authorities=authorities,
                bm25_index=bm25_index,
                vector_index=vector_index,
            ).to_dict()
            for item in agenda
        ]
        return {
            "dataset_id": dataset_id,
            "docket_id": docket_id,
            "plan_count": len(plans),
            "plans": plans,
            "summary": {
                "local_first": True,
                "parser_stage_enabled": True,
                "search_engine_fallback_enabled": True,
                "work_item_count": len(agenda),
                "starting_source_types": sorted(
                    {
                        str(item.get("selected_starting_source_type") or "")
                        for item in plans
                        if str(item.get("selected_starting_source_type") or "")
                    }
                ),
            },
        }

    def _query_hints(self, work_item: Dict[str, Any]) -> List[str]:
        hints: List[str] = []
        for candidate in (
            work_item.get("title"),
            work_item.get("action"),
            work_item.get("party"),
            work_item.get("modality"),
        ):
            text = str(candidate or "").strip()
            if text and text not in hints:
                hints.append(text)
        return hints

    def _select_starting_source(
        self,
        candidate_sources: Sequence[ProofSearchSource],
        work_item: Dict[str, Any],
    ) -> ProofSearchSource | None:
        source_type = str(work_item.get("source_type") or "").strip().lower()
        modality = str(work_item.get("modality") or "").strip().lower()
        title = str(work_item.get("title") or "").strip().lower()

        preferred_types: List[str] = []
        if source_type == "authority":
            parser_backed_authorities = any(
                source.source_type == "authority_list"
                and bool(source.metadata.get("linked_citation_count"))
                for source in candidate_sources
            )
            preferred_types = (
                ["authority_list", "legal_dataset_parser", "local_docket_documents", "local_bm25_index"]
                if parser_backed_authorities
                else ["authority_list", "local_docket_documents", "local_bm25_index"]
            )
        elif source_type == "party_analysis":
            preferred_types = ["local_bm25_index", "local_vector_index", "authority_list"]
        elif modality in {"prohibition", "obligation"} or "order" in title or "deadline" in title:
            preferred_types = ["local_docket_documents", "local_bm25_index", "authority_list"]
        else:
            preferred_types = ["local_vector_index", "local_docket_documents", "local_bm25_index"]

        for preferred_type in preferred_types:
            for source in candidate_sources:
                if source.source_type == preferred_type:
                    return source
        return candidate_sources[0] if candidate_sources else None

    def _build_search_stages(self, candidate_sources: Sequence[ProofSearchSource]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[str]] = {
            "local": [],
            "parser": [],
            "search_engine": [],
        }
        for source in candidate_sources:
            if source.source_type.startswith("local_") or source.source_type == "authority_list":
                grouped["local"].append(source.source_type)
            elif source.source_type == "legal_dataset_parser":
                grouped["parser"].append(source.source_type)
            elif source.source_type == "search_engine":
                grouped["search_engine"].append(source.source_type)
        stages: List[Dict[str, Any]] = []
        for stage_name in ("local", "parser", "search_engine"):
            routes = grouped[stage_name]
            if not routes:
                continue
            stages.append(
                {
                    "stage": stage_name,
                    "enabled": True,
                    "route_types": routes,
                }
            )
        return stages

    def _proof_gap_focus(self, work_item: Dict[str, Any]) -> List[str]:
        focus: List[str] = []
        source_type = str(work_item.get("source_type") or "").strip().lower()
        modality = str(work_item.get("modality") or "").strip().lower()
        action = str(work_item.get("action") or "").strip().lower()
        title = str(work_item.get("title") or "").strip().lower()

        if source_type == "authority":
            focus.append("governing_authority")
        if modality == "obligation":
            focus.append("mandatory_duty")
        if modality == "prohibition":
            focus.append("forbidden_conduct")
        if modality == "permission":
            focus.append("permitted_conduct")
        if "deadline" in action or "deadline" in title:
            focus.append("temporal_deadline")
        if "discovery" in action or "discovery" in title:
            focus.append("discovery_compliance")
        if source_type == "party_analysis":
            focus.append("support_gap")
        if not focus:
            focus.append("general_proof_support")
        return focus

    def _summarize_authorities(self, authorities: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        linked_citation_count = 0
        linked_corpus_keys: List[str] = []
        linked_corpus_priority: List[str] = []
        linked_dataset_ids: List[str] = []
        linked_dataset_priority: List[str] = []
        linked_source_urls: List[str] = []
        preferred_state_codes: List[str] = []
        routing_evidence: List[Dict[str, Any]] = []

        for authority in authorities:
            if not isinstance(authority, dict):
                continue
            if str(authority.get("authority_type") or "") != "linked_citation":
                continue
            linked_citation_count += 1
            corpus_key = str(authority.get("corpus_key") or "").strip()
            dataset_id = str(authority.get("dataset_id") or "").strip()
            source_url = str(authority.get("source_url") or "").strip()
            metadata = authority.get("metadata") if isinstance(authority.get("metadata"), dict) else {}
            corpus_priority_candidates: List[str] = []
            if corpus_key:
                corpus_priority_candidates.append(corpus_key)
            for candidate_corpus in list(metadata.get("candidate_corpora") or []):
                candidate_text = str(candidate_corpus or "").strip()
                if candidate_text:
                    corpus_priority_candidates.append(candidate_text)
            normalized_corpus_priority: List[str] = []
            for candidate_text in corpus_priority_candidates:
                if candidate_text and candidate_text not in normalized_corpus_priority:
                    normalized_corpus_priority.append(candidate_text)
            for candidate_text in normalized_corpus_priority:
                if candidate_text not in linked_corpus_priority:
                    linked_corpus_priority.append(candidate_text)
            preferred_dataset_candidates: List[str] = []
            if dataset_id:
                preferred_dataset_candidates.append(dataset_id)
            for preferred_dataset_id in list(metadata.get("preferred_dataset_ids") or []):
                preferred_text = str(preferred_dataset_id or "").strip()
                if preferred_text:
                    preferred_dataset_candidates.append(preferred_text)
            normalized_dataset_priority: List[str] = []
            for preferred_text in preferred_dataset_candidates:
                if preferred_text and preferred_text not in normalized_dataset_priority:
                    normalized_dataset_priority.append(preferred_text)
            if not corpus_key:
                for candidate_corpus in list(metadata.get("candidate_corpora") or []):
                    candidate_text = str(candidate_corpus or "").strip()
                    if candidate_text and candidate_text not in linked_corpus_keys:
                        linked_corpus_keys.append(candidate_text)
            if corpus_key and corpus_key not in linked_corpus_keys:
                linked_corpus_keys.append(corpus_key)
            if dataset_id and dataset_id not in linked_dataset_ids:
                linked_dataset_ids.append(dataset_id)
            if dataset_id and dataset_id not in linked_dataset_priority:
                linked_dataset_priority.append(dataset_id)
            if not dataset_id:
                for preferred_text in normalized_dataset_priority:
                    if preferred_text and preferred_text not in linked_dataset_ids:
                        linked_dataset_ids.append(preferred_text)
                    if preferred_text and preferred_text not in linked_dataset_priority:
                        linked_dataset_priority.append(preferred_text)
            if source_url and source_url not in linked_source_urls:
                linked_source_urls.append(source_url)
            source_cid = str(authority.get("source_cid") or "").strip()
            source_ref = str(authority.get("source_ref") or "").strip()
            source_title = str(authority.get("title") or authority.get("label") or "").strip()
            matched = bool(authority.get("matched"))
            state_code = str(
                authority.get("state_code")
                or metadata.get("state_code")
                or ""
            ).strip().upper()
            if state_code and state_code not in preferred_state_codes:
                preferred_state_codes.append(state_code)
            if normalized_corpus_priority:
                routing_evidence.append(
                    {
                        "authority_id": str(authority.get("id") or ""),
                        "citation_text": str(
                            authority.get("citation_text")
                            or authority.get("normalized_citation")
                            or authority.get("title")
                            or authority.get("label")
                            or ""
                        ).strip(),
                        "document_id": str(authority.get("document_id") or ""),
                        "document_title": str(authority.get("document_title") or ""),
                        "state_code": state_code,
                        "corpus_priority": list(normalized_corpus_priority),
                        "dataset_priority": list(normalized_dataset_priority),
                        "matched": matched,
                        "source_title": source_title,
                        "source_url": source_url,
                        "source_cid": source_cid,
                        "source_ref": source_ref,
                    }
                )

        return {
            "authority_count": len(authorities),
            "linked_citation_count": linked_citation_count,
            "linked_corpus_keys": linked_corpus_keys,
            "linked_corpus_priority": linked_corpus_priority,
            "linked_dataset_ids": linked_dataset_ids,
            "linked_dataset_priority": linked_dataset_priority,
            "linked_source_urls": linked_source_urls[:10],
            "preferred_state_codes": preferred_state_codes,
            "routing_evidence": routing_evidence[:20],
            "parser_backed": bool(linked_citation_count),
        }


def build_proof_tactician_manifest(
    *,
    dataset_id: str,
    docket_id: str,
    agenda: Sequence[Dict[str, Any]],
    documents: Sequence[Any],
    authorities: Sequence[Dict[str, Any]],
    bm25_index: Dict[str, Any] | None = None,
    vector_index: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build proof-search tactics for all current proof work items."""

    return ProofTactician().build_tactician_manifest(
        dataset_id=dataset_id,
        docket_id=docket_id,
        agenda=agenda,
        documents=documents,
        authorities=authorities,
        bm25_index=bm25_index,
        vector_index=vector_index,
    )


__all__ = [
    "ProofSearchPlan",
    "ProofSearchSource",
    "ProofTactician",
    "build_proof_tactician_manifest",
]
