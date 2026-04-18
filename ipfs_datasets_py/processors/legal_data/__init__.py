from __future__ import annotations

"""Legal data processing modules consolidated under ipfs_datasets_py.processors."""

from pathlib import Path

from .analysis_bundle import build_legal_analysis_bundle
from .case_knowledge import (
    analyze_case_graph_gaps,
    build_case_knowledge_graph,
    summarize_case_graph,
)
from .courtlistener_ingestion import (
    COURTLISTENER_API_ROOT,
    COURTLISTENER_RECAP_FETCH_REQUEST_TYPES,
    COURTLISTENER_RECAP_FETCH_URL,
    attach_available_courtlistener_recap_evidence_to_docket,
    attach_public_courtlistener_filing_pdfs_to_docket,
    build_packaged_docket_acquisition_plan,
    execute_packaged_docket_acquisition_plan,
    CourtListenerIngestionError,
    build_courtlistener_recap_fetch_payload,
    extract_courtlistener_public_filing_pdf_texts,
    build_packaged_docket_recap_fetch_preflight,
    fetch_courtlistener_docket,
    fetch_pacer_document_with_browser,
    find_rich_courtlistener_docket,
    fetch_random_courtlistener_docket,
    probe_courtlistener_public_filing_pdfs,
    get_courtlistener_recap_fetch_request,
    probe_courtlistener_document_acquisition_target,
    resolve_pacer_client_code,
    resolve_pacer_password,
    resolve_pacer_username,
    sample_random_courtlistener_dockets_batch,
    resolve_courtlistener_api_token,
    submit_courtlistener_recap_fetch_request,
    submit_packaged_docket_recap_fetch_requests,
)
try:
    from .courtlistener_cache_packaging import (
        CourtListenerCachePackager,
        load_packaged_courtlistener_fetch_cache,
        load_packaged_courtlistener_fetch_cache_components,
        package_courtlistener_fetch_cache,
    )
except Exception:  # pragma: no cover - optional dependency guard
    CourtListenerCachePackager = None
    load_packaged_courtlistener_fetch_cache = None
    load_packaged_courtlistener_fetch_cache_components = None
    package_courtlistener_fetch_cache = None
from .claim_intake import (
    CLAIM_INTAKE_REQUIREMENTS,
    build_claim_element_question_intent,
    build_claim_element_question_text,
    build_proof_lead_question_intent,
    build_proof_lead_question_text,
    match_required_element_id,
    normalize_claim_type,
    refresh_required_elements,
    registry_element_for_claim_type,
    registry_for_claim_type,
    render_question_text_from_intent,
)
try:
    from .bluebook_linker_fuzz_harness import (
        BluebookCitationCandidate as BluebookLinkerFuzzCandidate,
        BluebookCitationFuzzAttempt,
        BluebookCitationFuzzRun,
        build_bluebook_fuzz_generation_prompt,
        collect_seeded_bluebook_fuzz_candidates,
        parse_bluebook_fuzz_candidates,
        run_bluebook_linker_fuzz_harness,
    )
except Exception:  # pragma: no cover - optional dependency guard
    BluebookLinkerFuzzCandidate = None
    BluebookCitationFuzzAttempt = None
    BluebookCitationFuzzRun = None
    build_bluebook_fuzz_generation_prompt = None
    collect_seeded_bluebook_fuzz_candidates = None
    parse_bluebook_fuzz_candidates = None
    run_bluebook_linker_fuzz_harness = None
try:
    from .court_pdf_rendering import (
        DEFAULT_EXHIBIT_CAPTION,
        ExhibitCaptionConfig,
        StateCourtPleadingConfig,
        build_state_court_filing_packet,
        draw_exhibit_caption,
        parse_exhibit_cover_source,
        render_exhibit_cover_from_markdown,
        render_exhibit_tab_from_markdown,
        render_state_court_pdf_batch,
        render_state_court_markdown_to_pdf,
        render_text_lines_pdf,
    )
except Exception:  # pragma: no cover - optional dependency guard
    DEFAULT_EXHIBIT_CAPTION = None
    ExhibitCaptionConfig = None
    StateCourtPleadingConfig = None
    build_state_court_filing_packet = None
    draw_exhibit_caption = None
    parse_exhibit_cover_source = None
    render_exhibit_cover_from_markdown = None
    render_exhibit_tab_from_markdown = None
    render_state_court_pdf_batch = None
    render_state_court_markdown_to_pdf = None
    render_text_lines_pdf = None
try:
    from .courtstyle_packet_export import (
        build_courtstyle_packet_from_config,
        build_default_courtstyle_packet,
    )
except Exception:  # pragma: no cover - optional dependency guard
    build_courtstyle_packet_from_config = None
    build_default_courtstyle_packet = None
try:
    from .court_ready_binder_index_export import (
        build_court_ready_binder_index,
        build_court_ready_binder_index_from_config,
        build_default_court_ready_binder_index,
    )
except Exception:  # pragma: no cover - optional dependency guard
    build_court_ready_binder_index = None
    build_court_ready_binder_index_from_config = None
    build_default_court_ready_binder_index = None
try:
    from .official_form_drafts_export import (
        build_default_official_form_drafts,
        build_official_form_drafts,
        build_official_form_drafts_from_config,
    )
except Exception:  # pragma: no cover - optional dependency guard
    build_official_form_drafts = None
    build_official_form_drafts_from_config = None
    build_default_official_form_drafts = None
try:
    from .filing_specific_binders_export import (
        build_default_filing_specific_binders,
        build_filing_specific_binders,
        build_filing_specific_binders_from_config,
    )
except Exception:  # pragma: no cover - optional dependency guard
    build_filing_specific_binders = None
    build_filing_specific_binders_from_config = None
    build_default_filing_specific_binders = None
try:
    from .exhibit_binder_export import (
        build_exhibit_binder,
        convert_markdown_to_binder_pdf,
        eml_to_pdf,
        family_slug,
        image_to_pdf,
        markdown_or_text_to_pdf,
        merge_pdfs,
        note_pdf,
        render_binder_title_pdf,
        render_family_divider_pdf,
        run_command,
        slugify_exhibit_label,
        source_to_pdf,
        pdf_page_count,
    )
except Exception:  # pragma: no cover - optional dependency guard
    build_exhibit_binder = None
    convert_markdown_to_binder_pdf = None
    eml_to_pdf = None
    family_slug = None
    image_to_pdf = None
    markdown_or_text_to_pdf = None
    merge_pdfs = None
    note_pdf = None
    render_binder_title_pdf = None
    render_family_divider_pdf = None
    run_command = None
    slugify_exhibit_label = None
    source_to_pdf = None
    pdf_page_count = None
try:
    from .exhibit_binder_templates import (
        BinderCourtConfig,
        DEFAULT_BINDER_COURT_CONFIG,
        render_exhibit_binder_front_sheet,
        render_table_of_exhibits_pdf,
    )
    from .legal_pdf_manifest import (
        binder_court_config_from_manifest,
        build_state_court_filing_packet_from_manifest,
        load_json_manifest,
    )
    from .exhibit_binder_manifest import build_exhibit_binder_from_manifest
    from .full_evidence_binder_manifest import build_full_evidence_binder_from_manifest
except Exception:  # pragma: no cover - optional dependency guard
    BinderCourtConfig = None
    DEFAULT_BINDER_COURT_CONFIG = None
    render_exhibit_binder_front_sheet = None
    render_table_of_exhibits_pdf = None
    build_state_court_filing_packet_from_manifest = None
    load_json_manifest = None
    build_exhibit_binder_from_manifest = None
    build_full_evidence_binder_from_manifest = None
    binder_court_config_from_manifest = None
from .dependency_graph import (
    Dependency,
    DependencyGraph,
    DependencyGraphBuilder,
    DependencyNode,
    DependencyType,
    NodeType,
)
try:
    from .docket_dataset import (
        DocketDatasetBuilder,
        DocketDatasetObject,
        DocketDocument,
        audit_docket_dataset_citation_sources,
        audit_docket_dataset_eu_citation_sources,
        audit_packaged_docket_citation_sources,
        build_docket_deontic_artifacts,
        collect_docket_dataset_citation_recovery_candidates,
        collect_packaged_docket_citation_recovery_candidates,
        execute_docket_dataset_missing_authority_follow_up,
        execute_packaged_docket_missing_authority_follow_up,
        plan_docket_dataset_missing_authority_follow_up,
        plan_packaged_docket_missing_authority_follow_up,
        recover_docket_dataset_missing_authorities,
        recover_packaged_docket_missing_authorities,
        search_docket_dataset_bm25,
        search_docket_dataset_vector,
        summarize_docket_dataset,
    )
except Exception:  # pragma: no cover - optional dependency guard
    DocketDatasetBuilder = None
    DocketDatasetObject = None
    DocketDocument = None
    audit_docket_dataset_citation_sources = None
    audit_docket_dataset_eu_citation_sources = None
    audit_packaged_docket_citation_sources = None
    build_docket_deontic_artifacts = None
    collect_docket_dataset_citation_recovery_candidates = None
    collect_packaged_docket_citation_recovery_candidates = None
    execute_docket_dataset_missing_authority_follow_up = None
    execute_packaged_docket_missing_authority_follow_up = None
    plan_docket_dataset_missing_authority_follow_up = None
    plan_packaged_docket_missing_authority_follow_up = None
    recover_docket_dataset_missing_authorities = None
    recover_packaged_docket_missing_authorities = None
    search_docket_dataset_bm25 = None
    search_docket_dataset_vector = None
    summarize_docket_dataset = None


def ingest_docket_dataset(
    source: str | dict,
    *,
    builder: DocketDatasetBuilder | None = None,
    courtlistener_api_token: str | None = None,
    include_recap_documents: bool = True,
    include_document_text: bool = True,
    max_documents: int | None = None,
    docket_id: str | None = None,
    case_name: str | None = None,
    court: str | None = None,
    glob_pattern: str = "*",
    include_knowledge_graph: bool = True,
    include_bm25: bool = True,
    include_vector_index: bool = True,
    include_formal_logic: bool = True,
    include_router_enrichment: bool = True,
) -> DocketDatasetObject:
    """Build a docket dataset from a supported source payload or path."""

    if DocketDatasetBuilder is None:
        raise RuntimeError("Docket dataset support is unavailable in this environment.")

    active_builder = builder or DocketDatasetBuilder()
    common_kwargs = {
        "include_knowledge_graph": include_knowledge_graph,
        "include_bm25": include_bm25,
        "include_vector_index": include_vector_index,
        "include_formal_logic": include_formal_logic,
        "include_router_enrichment": include_router_enrichment,
    }

    if isinstance(source, dict):
        payload = dict(source)
        if docket_id:
            payload["docket_id"] = docket_id
        if case_name:
            payload["case_name"] = case_name
        if court:
            payload["court"] = court
        return active_builder.build_from_docket(payload, **common_kwargs)

    source_text = str(source or "").strip()
    if not source_text:
        raise ValueError("source must be a non-empty path, URL, or docket payload")

    if "courtlistener.com" in source_text:
        payload = fetch_courtlistener_docket(
            source_text,
            api_token=courtlistener_api_token,
            include_recap_documents=include_recap_documents,
            include_document_text=include_document_text,
            max_documents=max_documents,
        )
        if docket_id:
            payload["docket_id"] = docket_id
        if case_name:
            payload["case_name"] = case_name
        if court:
            payload["court"] = court
        return active_builder.build_from_docket(payload, **common_kwargs)

    source_path = Path(source_text)
    if source_path.is_file():
        if source_path.suffix.lower() in {".html", ".htm"}:
            return active_builder.build_from_html_file(
                source_path,
                docket_id=docket_id,
                case_name=case_name,
                court=court,
                **common_kwargs,
            )
        return active_builder.build_from_json_file(source_path, **common_kwargs)
    if source_path.is_dir():
        return active_builder.build_from_directory(
            source_path,
            docket_id=docket_id,
            case_name=case_name,
            court=court or "",
            glob_pattern=glob_pattern,
            **common_kwargs,
        )
    raise FileNotFoundError(f"Unsupported docket dataset source: {source_text}")
try:
    from .workspace_dataset import (
        WorkspaceDatasetBuilder,
        WorkspaceDatasetObject,
        WorkspaceDocument,
        export_workspace_dataset_single_parquet,
        ingest_workspace_pdf_directory,
        inspect_workspace_dataset_single_parquet,
        load_workspace_dataset_single_parquet,
        load_workspace_dataset_single_parquet_summary,
        render_workspace_dataset_single_parquet_report,
        search_workspace_dataset_bm25,
        search_workspace_dataset_vector,
        summarize_workspace_dataset,
    )
except Exception:  # pragma: no cover - optional dependency guard
    WorkspaceDatasetBuilder = None
    WorkspaceDatasetObject = None
    WorkspaceDocument = None
    export_workspace_dataset_single_parquet = None
    ingest_workspace_pdf_directory = None
    inspect_workspace_dataset_single_parquet = None
    load_workspace_dataset_single_parquet = None
    load_workspace_dataset_single_parquet_summary = None
    render_workspace_dataset_single_parquet_report = None
    search_workspace_dataset_bm25 = None
    search_workspace_dataset_vector = None
    summarize_workspace_dataset = None
try:
    from .workspace_packaging import (
        WorkspaceDatasetPackager,
        inspect_packaged_workspace_bundle,
        iter_packaged_workspace_chain,
        load_packaged_workspace_dataset,
        load_packaged_workspace_dataset_components,
        load_packaged_workspace_summary_view,
        package_workspace_dataset,
        render_packaged_workspace_report,
    )
except Exception:  # pragma: no cover - optional dependency guard
    WorkspaceDatasetPackager = None
    inspect_packaged_workspace_bundle = None
    iter_packaged_workspace_chain = None
    load_packaged_workspace_dataset = None
    load_packaged_workspace_dataset_components = None
    load_packaged_workspace_summary_view = None
    package_workspace_dataset = None
    render_packaged_workspace_report = None
try:
    from .email_auth import (
        DEFAULT_TOKEN_ROOT,
        GMAIL_IMAP_SCOPE,
        IPFS_VAULT_SECRET_PREFIX,
        KEYRING_SERVICE,
        build_xoauth2_bytes,
        default_token_cache_path,
        load_cached_token,
        read_password_from_ipfs_secrets_vault,
        read_password_from_keyring,
        resolve_gmail_credentials,
        resolve_gmail_oauth_access_token,
        run_local_server_oauth_flow,
        save_cached_token,
        save_password_to_ipfs_secrets_vault,
        save_password_to_keyring,
        token_is_usable,
    )
    from .email_agentic_search import search_email_corpus_agentic
    from .email_authority_enrichment import (
        build_email_authority_query_plan,
        build_seed_authority_catalog,
        build_seed_authority_catalog_with_catalog,
        enrich_email_timeline_authorities,
    )
    from .email_authority_catalog import (
        DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG,
        load_email_authority_enrichment_catalog,
        merge_email_authority_enrichment_catalog,
    )
    from .email_corpus import (
        build_email_duckdb_artifacts,
        build_email_graphrag_artifacts,
        search_email_graphrag_duckdb,
    )
    from .email_import import import_gmail_evidence
    from .email_pipeline import (
        run_gmail_duckdb_pipeline,
        search_email_duckdb_corpus,
    )
    from .email_relevance import (
        DEFAULT_QUERY_TERMS,
        build_complaint_terms,
        collect_email_relevance_text,
        generate_email_search_plan,
        load_keyword_lines,
        score_email_relevance,
        tokenize_relevance_text,
    )
    from .email_seed_planner import build_email_seed_plan
    from .email_timeline_handoff import (
        build_email_timeline_handoff,
        build_email_timeline_handoff_from_file,
    )
    from .email_workspace import (
        EmailCorpusPaths,
        build_email_workspace_corpus,
        canonical_email_corpus_paths,
        import_gmail_workspace_evidence,
        import_local_eml_directory,
        merge_email_manifests,
        run_gmail_workspace_duckdb_pipeline,
        save_email_bundle,
        search_email_workspace_corpus,
    )
except Exception:  # pragma: no cover - optional dependency guard
    DEFAULT_TOKEN_ROOT = None
    GMAIL_IMAP_SCOPE = None
    IPFS_VAULT_SECRET_PREFIX = None
    KEYRING_SERVICE = None
    build_xoauth2_bytes = None
    default_token_cache_path = None
    load_cached_token = None
    read_password_from_ipfs_secrets_vault = None
    read_password_from_keyring = None
    resolve_gmail_credentials = None
    resolve_gmail_oauth_access_token = None
    run_local_server_oauth_flow = None
    save_cached_token = None
    save_password_to_ipfs_secrets_vault = None
    save_password_to_keyring = None
    token_is_usable = None
    search_email_corpus_agentic = None
    build_email_authority_query_plan = None
    build_seed_authority_catalog = None
    build_seed_authority_catalog_with_catalog = None
    enrich_email_timeline_authorities = None
    DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG = None
    load_email_authority_enrichment_catalog = None
    merge_email_authority_enrichment_catalog = None
    build_email_duckdb_artifacts = None
    build_email_graphrag_artifacts = None
    search_email_graphrag_duckdb = None
    import_gmail_evidence = None
    run_gmail_duckdb_pipeline = None
    search_email_duckdb_corpus = None
    DEFAULT_QUERY_TERMS = None
    build_complaint_terms = None
    collect_email_relevance_text = None
    generate_email_search_plan = None
    load_keyword_lines = None
    score_email_relevance = None
    tokenize_relevance_text = None
    build_email_seed_plan = None
    build_email_timeline_handoff = None
    build_email_timeline_handoff_from_file = None
    EmailCorpusPaths = None
    build_email_workspace_corpus = None
    canonical_email_corpus_paths = None
    import_gmail_workspace_evidence = None
    import_local_eml_directory = None
    merge_email_manifests = None
    run_gmail_workspace_duckdb_pipeline = None
    save_email_bundle = None
    search_email_workspace_corpus = None
try:
    from .docket_packaging import (
        DocketDatasetPackager,
        PackagedDocketQueryAdapter,
        attach_packaged_docket_proof_assistant_packet,
        PackagedQueryExecutionPlan,
        build_packaged_docket_proof_evidence_bundle,
        build_packaged_docket_proof_assistant_packet,
        execute_packaged_docket_action_candidate,
        execute_packaged_docket_action_candidates,
        enrich_packaged_docket_with_tactician,
        execute_packaged_docket_next_action,
        execute_packaged_docket_proof_revalidation_queue,
        execute_packaged_docket_query,
        execute_packaged_docket_follow_up_job,
        execute_packaged_docket_follow_up_plan,
        get_packaged_docket_operator_dashboard,
        get_packaged_docket_proof_revalidation_queue,
        get_packaged_docket_proof_revalidation_runs,
        get_packaged_docket_proof_revalidation_snapshot,
        iter_packaged_docket_chain,
        load_packaged_docket_dataset,
        load_packaged_docket_dataset_components,
        load_packaged_docket_operator_dashboard_report,
        load_packaged_docket_proof_revalidation_report,
        load_packaged_docket_summary_view,
        load_packaged_docket_inspection_report,
        inspect_packaged_docket_bundle,
        export_docket_dataset_single_pdf,
        export_docket_dataset_single_parquet,
        plan_packaged_docket_query,
        persist_packaged_docket_proof_revalidation_queue,
        prepare_packaged_docket_follow_up_job,
        render_packaged_docket_proof_revalidation_report,
        render_packaged_docket_operator_dashboard,
        package_docket_dataset,
        render_packaged_docket_inspection_report,
        search_packaged_docket_dataset_bm25,
        search_packaged_docket_dataset_vector,
        search_packaged_docket_logic_artifacts,
        search_packaged_docket_proof_tasks,
    )
except Exception:  # pragma: no cover - optional dependency guard
    DocketDatasetPackager = None
    PackagedDocketQueryAdapter = None
    attach_packaged_docket_proof_assistant_packet = None
    PackagedQueryExecutionPlan = None
    build_packaged_docket_proof_evidence_bundle = None
    build_packaged_docket_proof_assistant_packet = None
    execute_packaged_docket_action_candidate = None
    execute_packaged_docket_action_candidates = None
    enrich_packaged_docket_with_tactician = None
    execute_packaged_docket_next_action = None
    execute_packaged_docket_proof_revalidation_queue = None
    execute_packaged_docket_query = None
    execute_packaged_docket_follow_up_job = None
    execute_packaged_docket_follow_up_plan = None
    get_packaged_docket_operator_dashboard = None
    get_packaged_docket_proof_revalidation_queue = None
    get_packaged_docket_proof_revalidation_runs = None
    get_packaged_docket_proof_revalidation_snapshot = None
    iter_packaged_docket_chain = None
    load_packaged_docket_dataset = None
    load_packaged_docket_dataset_components = None
    load_packaged_docket_operator_dashboard_report = None
    load_packaged_docket_proof_revalidation_report = None
    load_packaged_docket_summary_view = None
    load_packaged_docket_inspection_report = None
    inspect_packaged_docket_bundle = None
    export_docket_dataset_single_pdf = None
    export_docket_dataset_single_parquet = None
    plan_packaged_docket_query = None
    persist_packaged_docket_proof_revalidation_queue = None
    prepare_packaged_docket_follow_up_job = None
    render_packaged_docket_proof_revalidation_report = None
    render_packaged_docket_operator_dashboard = None
    package_docket_dataset = None
    render_packaged_docket_inspection_report = None
    search_packaged_docket_dataset_bm25 = None
    search_packaged_docket_dataset_vector = None
    search_packaged_docket_logic_artifacts = None
    search_packaged_docket_proof_tasks = None
_LAZY_EXPORTS = {
    "DocketProofAssistant": (".proof_assistant", "DocketProofAssistant"),
    "DocketProofAssistantBuilder": (".proof_assistant", "DocketProofAssistantBuilder"),
    "ProofAssistantWorkItem": (".proof_assistant", "ProofAssistantWorkItem"),
    "build_docket_proof_assistant": (".proof_assistant", "build_docket_proof_assistant"),
    "ProofSearchPlan": (".proof_tactician", "ProofSearchPlan"),
    "ProofSearchSource": (".proof_tactician", "ProofSearchSource"),
    "ProofTactician": (".proof_tactician", "ProofTactician"),
    "build_proof_tactician_manifest": (".proof_tactician", "build_proof_tactician_manifest"),
    "DocumentSection": (".document_structure", "DocumentSection"),
    "ParsedLegalDocument": (".document_structure", "ParsedLegalDocument"),
    "PleadingCaption": (".document_structure", "PleadingCaption"),
    "PleadingHeader": (".document_structure", "PleadingHeader"),
    "build_pleading_caption": (".document_structure", "build_pleading_caption"),
    "build_document_knowledge_graph": (".document_structure", "build_document_knowledge_graph"),
    "extract_pleading_header": (".document_structure", "extract_pleading_header"),
    "forbidden_formal_document_meta_phrases": (".document_structure", "forbidden_formal_document_meta_phrases"),
    "paginate_pleading_lines": (".document_structure", "paginate_pleading_lines"),
    "parse_legal_document": (".document_structure", "parse_legal_document"),
    "parse_legal_document_to_graph": (".document_structure", "parse_legal_document_to_graph"),
    "render_pleading_caption_block": (".document_structure", "render_pleading_caption_block"),
    "required_formal_document_markers": (".document_structure", "required_formal_document_markers"),
    "summarize_formal_document": (".document_structure", "summarize_formal_document"),
    "validate_formal_document": (".document_structure", "validate_formal_document"),
    "Frame": (".frames", "Frame"),
    "FrameKnowledgeBase": (".frames", "FrameKnowledgeBase"),
    "FrameSlotEvidence": (".frames", "FrameSlotEvidence"),
    "enrich_docket_documents_with_formal_logic": (".formal_docket_enrichment", "enrich_docket_documents_with_formal_logic"),
    "NeurosymbolicMatcher": (".neurosymbolic", "NeurosymbolicMatcher"),
    "LegalElement": (".requirements_graph", "LegalElement"),
    "LegalRelation": (".requirements_graph", "LegalRelation"),
    "LegalRequirementsGraph": (".requirements_graph", "LegalRequirementsGraph"),
    "LegalRequirementsGraphBuilder": (".requirements_graph", "LegalRequirementsGraphBuilder"),
    "HybridLawReasoner": (".reasoner", "HybridLawReasoner"),
    "IRReference": (".reasoner", "IRReference"),
    "ProofObject": (".reasoner", "ProofObject"),
    "ProofStep": (".reasoner", "ProofStep"),
    "SourceProvenance": (".reasoner", "SourceProvenance"),
    "append_proof_to_store": (".reasoner", "append_proof_to_store"),
    "load_legal_ir_from_json": (".reasoner", "load_legal_ir_from_json"),
    "load_proof_store": (".reasoner", "load_proof_store"),
    "proof_from_dict": (".reasoner", "proof_from_dict"),
    "proof_to_dict": (".reasoner", "proof_to_dict"),
    "write_proof_store": (".reasoner", "write_proof_store"),
    "analyze_document_with_routers": (".rich_docket_enrichment", "analyze_document_with_routers"),
    "enrich_docket_documents_with_routers": (".rich_docket_enrichment", "enrich_docket_documents_with_routers"),
    "build_bm25_index": ("..retrieval", "build_bm25_index"),
    "search_bm25_index": ("..retrieval", "search_bm25_index"),
    "bm25_search_documents": ("..retrieval", "bm25_search_documents"),
    "FilingSupportReference": (".support_map", "FilingSupportReference"),
    "MotionSupportMap": (".support_map", "MotionSupportMap"),
    "SupportFact": (".support_map", "SupportFact"),
    "SupportMapBuilder": (".support_map", "SupportMapBuilder"),
    "SupportMapEntry": (".support_map", "SupportMapEntry"),
}


def __getattr__(name: str):
    """Resolve expensive optional legal-data exports on first use."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attribute_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
__all__ = [
    "DocumentSection",
    "Dependency",
    "DependencyGraph",
    "DependencyGraphBuilder",
    "DependencyNode",
    "DependencyType",
    "COURTLISTENER_API_ROOT",
    "COURTLISTENER_RECAP_FETCH_REQUEST_TYPES",
    "COURTLISTENER_RECAP_FETCH_URL",
    "attach_available_courtlistener_recap_evidence_to_docket",
    "attach_public_courtlistener_filing_pdfs_to_docket",
    "build_packaged_docket_acquisition_plan",
    "execute_packaged_docket_acquisition_plan",
    "CourtListenerIngestionError",
    "CourtListenerCachePackager",
    "DocketDatasetBuilder",
    "DocketDatasetPackager",
    "PackagedDocketQueryAdapter",
    "attach_packaged_docket_proof_assistant_packet",
    "PackagedQueryExecutionPlan",
    "build_packaged_docket_proof_evidence_bundle",
    "build_packaged_docket_proof_assistant_packet",
    "enrich_packaged_docket_with_tactician",
    "DocketDatasetObject",
    "DocketDocument",
    "audit_docket_dataset_citation_sources",
    "audit_docket_dataset_eu_citation_sources",
    "audit_packaged_docket_citation_sources",
    "build_docket_deontic_artifacts",
    "collect_docket_dataset_citation_recovery_candidates",
    "collect_packaged_docket_citation_recovery_candidates",
    "execute_docket_dataset_missing_authority_follow_up",
    "execute_packaged_docket_missing_authority_follow_up",
    "plan_docket_dataset_missing_authority_follow_up",
    "plan_packaged_docket_missing_authority_follow_up",
    "execute_packaged_docket_action_candidate",
    "execute_packaged_docket_next_action",
    "export_docket_dataset_single_pdf",
    "export_docket_dataset_single_parquet",
    "execute_packaged_docket_proof_revalidation_queue",
    "execute_packaged_docket_query",
    "execute_packaged_docket_follow_up_job",
    "execute_packaged_docket_follow_up_plan",
    "get_packaged_docket_operator_dashboard",
    "get_packaged_docket_proof_revalidation_queue",
    "get_packaged_docket_proof_revalidation_runs",
    "get_packaged_docket_proof_revalidation_snapshot",
    "iter_packaged_docket_chain",
    "package_docket_dataset",
    "load_packaged_docket_dataset",
    "load_packaged_docket_dataset_components",
    "load_packaged_docket_operator_dashboard_report",
    "load_packaged_docket_proof_revalidation_report",
    "load_packaged_docket_summary_view",
    "load_packaged_docket_inspection_report",
    "inspect_packaged_docket_bundle",
    "plan_packaged_docket_query",
    "persist_packaged_docket_proof_revalidation_queue",
    "prepare_packaged_docket_follow_up_job",
    "render_packaged_docket_proof_revalidation_report",
    "render_packaged_docket_operator_dashboard",
    "render_packaged_docket_inspection_report",
    "search_packaged_docket_dataset_bm25",
    "search_packaged_docket_dataset_vector",
    "search_packaged_docket_logic_artifacts",
    "search_packaged_docket_proof_tasks",
    "build_docket_proof_assistant",
    "build_proof_tactician_manifest",
    "FilingSupportReference",
    "Frame",
    "FrameKnowledgeBase",
    "FrameSlotEvidence",
    "HybridLawReasoner",
    "IRReference",
    "LegalElement",
    "LegalRelation",
    "LegalRequirementsGraph",
    "LegalRequirementsGraphBuilder",
    "MotionSupportMap",
    "NeurosymbolicMatcher",
    "NodeType",
    "ParsedLegalDocument",
    "PleadingCaption",
    "PleadingHeader",
    "ProofObject",
    "ProofAssistantWorkItem",
    "ProofSearchPlan",
    "ProofSearchSource",
    "ProofTactician",
    "ProofStep",
    "SourceProvenance",
    "DocketProofAssistant",
    "DocketProofAssistantBuilder",
    "load_legal_ir_from_json",
    "load_proof_store",
    "write_proof_store",
    "append_proof_to_store",
    "proof_from_dict",
    "proof_to_dict",
    "recover_docket_dataset_missing_authorities",
    "recover_packaged_docket_missing_authorities",
    "extract_pleading_header",
    "build_pleading_caption",
    "parse_legal_document",
    "build_document_knowledge_graph",
    "parse_legal_document_to_graph",
    "render_pleading_caption_block",
    "paginate_pleading_lines",
    "required_formal_document_markers",
    "forbidden_formal_document_meta_phrases",
    "validate_formal_document",
    "summarize_formal_document",
    "SupportFact",
    "SupportMapBuilder",
    "SupportMapEntry",
    "build_legal_analysis_bundle",
    "BluebookLinkerFuzzCandidate",
    "BluebookCitationFuzzAttempt",
    "BluebookCitationFuzzRun",
    "build_bluebook_fuzz_generation_prompt",
    "collect_seeded_bluebook_fuzz_candidates",
    "parse_bluebook_fuzz_candidates",
    "run_bluebook_linker_fuzz_harness",
    "CLAIM_INTAKE_REQUIREMENTS",
    "DEFAULT_EXHIBIT_CAPTION",
    "ExhibitCaptionConfig",
    "StateCourtPleadingConfig",
    "convert_markdown_to_binder_pdf",
    "build_exhibit_binder",
    "build_state_court_filing_packet",
    "build_state_court_filing_packet_from_manifest",
    "build_exhibit_binder_from_manifest",
    "build_full_evidence_binder_from_manifest",
    "build_default_courtstyle_packet",
    "build_courtstyle_packet_from_config",
    "build_court_ready_binder_index",
    "build_court_ready_binder_index_from_config",
    "build_default_court_ready_binder_index",
    "build_official_form_drafts",
    "build_official_form_drafts_from_config",
    "build_default_official_form_drafts",
    "build_filing_specific_binders",
    "build_filing_specific_binders_from_config",
    "build_default_filing_specific_binders",
    "binder_court_config_from_manifest",
    "BinderCourtConfig",
    "DEFAULT_BINDER_COURT_CONFIG",
    "eml_to_pdf",
    "analyze_case_graph_gaps",
    "build_claim_element_question_intent",
    "build_claim_element_question_text",
    "build_case_knowledge_graph",
    "build_bm25_index",
    "bm25_search_documents",
    "analyze_document_with_routers",
    "build_courtlistener_recap_fetch_payload",
    "extract_courtlistener_public_filing_pdf_texts",
    "build_packaged_docket_recap_fetch_preflight",
    "enrich_docket_documents_with_formal_logic",
    "fetch_courtlistener_docket",
    "fetch_pacer_document_with_browser",
    "find_rich_courtlistener_docket",
    "fetch_random_courtlistener_docket",
    "probe_courtlistener_public_filing_pdfs",
    "get_courtlistener_recap_fetch_request",
    "probe_courtlistener_document_acquisition_target",
    "draw_exhibit_caption",
    "family_slug",
    "image_to_pdf",
    "markdown_or_text_to_pdf",
    "merge_pdfs",
    "note_pdf",
    "parse_exhibit_cover_source",
    "pdf_page_count",
    "render_binder_title_pdf",
    "render_exhibit_binder_front_sheet",
    "render_exhibit_cover_from_markdown",
    "render_family_divider_pdf",
    "render_exhibit_tab_from_markdown",
    "render_state_court_pdf_batch",
    "render_state_court_markdown_to_pdf",
    "render_table_of_exhibits_pdf",
    "load_json_manifest",
    "render_text_lines_pdf",
    "run_command",
    "sample_random_courtlistener_dockets_batch",
    "slugify_exhibit_label",
    "source_to_pdf",
    "load_packaged_courtlistener_fetch_cache",
    "load_packaged_courtlistener_fetch_cache_components",
    "package_courtlistener_fetch_cache",
    "build_proof_lead_question_intent",
    "build_proof_lead_question_text",
    "match_required_element_id",
    "normalize_claim_type",
    "refresh_required_elements",
    "registry_element_for_claim_type",
    "registry_for_claim_type",
    "resolve_courtlistener_api_token",
    "resolve_pacer_client_code",
    "resolve_pacer_password",
    "resolve_pacer_username",
    "enrich_docket_documents_with_routers",
    "render_question_text_from_intent",
    "search_bm25_index",
    "search_docket_dataset_bm25",
    "search_docket_dataset_vector",
    "submit_courtlistener_recap_fetch_request",
    "submit_packaged_docket_recap_fetch_requests",
    "summarize_docket_dataset",
    "ingest_docket_dataset",
    "WorkspaceDatasetBuilder",
    "WorkspaceDatasetObject",
    "WorkspaceDocument",
    "export_workspace_dataset_single_parquet",
    "ingest_workspace_pdf_directory",
    "inspect_workspace_dataset_single_parquet",
    "load_workspace_dataset_single_parquet",
    "load_workspace_dataset_single_parquet_summary",
    "render_workspace_dataset_single_parquet_report",
    "search_workspace_dataset_bm25",
    "search_workspace_dataset_vector",
    "summarize_workspace_dataset",
    "WorkspaceDatasetPackager",
    "inspect_packaged_workspace_bundle",
    "iter_packaged_workspace_chain",
    "load_packaged_workspace_dataset",
    "load_packaged_workspace_dataset_components",
    "load_packaged_workspace_summary_view",
    "package_workspace_dataset",
    "render_packaged_workspace_report",
    "build_email_authority_query_plan",
    "build_seed_authority_catalog",
    "build_seed_authority_catalog_with_catalog",
    "enrich_email_timeline_authorities",
    "DEFAULT_EMAIL_AUTHORITY_ENRICHMENT_CATALOG",
    "load_email_authority_enrichment_catalog",
    "merge_email_authority_enrichment_catalog",
    "summarize_case_graph",
]
