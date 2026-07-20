"""Logic Theorem Optimizer System.

This module provides a stochastic gradient descent (SGD) based system for
generating and optimizing logical theorems from arbitrary data types.

Inspired by the adversarial harness pattern from complaint-generator, this
system uses:
- LogicExtractor: Extracts logical statements from arbitrary data
- LogicCritic: Evaluates logical consistency and quality
- LogicOptimizer: SGD-based improvement of extraction quality
- TheoremSession: Single extraction-critique-optimize cycle
- LogicHarness: Batch processing with parallelism

Architecture:
    Data → LogicExtractor → LogicCritic → LogicOptimizer → Verified Theorems
           (AI Models)      (Theorem       (SGD-based)
                            Provers)

Integration:
- Uses ipfs_accelerate_py for AI model inference
- Integrates with Z3, CVC5, Lean, Coq theorem provers
- Uses TDFOL/CEC logic frameworks
- Maintains knowledge graph ontology consistency
"""

from __future__ import annotations

__all__ = [
    # Exceptions
    'LogicTheoremOptimizerError',
    'OptimizerError',
    'ExtractionError',
    'ValidationError',
    'ProvingError',
    'RefinementError',
    'ConfigurationError',
    # Unified Optimizer (NEW - BaseOptimizer implementation)
    'LogicTheoremOptimizer',
    # Extractor
    'LogicExtractor',
    'LogicExtractionContext',
    'ExtractionResult',
    'ExtractionMode',
    'DataType',
    # Deterministic modal legal parser
    'ModalLogicFamily',
    'ModalSystem',
    'ModalOperatorSpec',
    'ModalSemanticsSpec',
    'ModalParseProfile',
    'ModalRegistry',
    'DEFAULT_MODAL_REGISTRY',
    'ModalIRDocument',
    'ModalIRFormula',
    'ModalIRFrame',
    'ModalIRFrameLogic',
    'ModalIRFrameLogicTriple',
    'ModalIROperator',
    'ModalIRPredicate',
    'ModalIRProvenance',
    'LegalModalParser',
    'LegalSegment',
    'ModalCueSpan',
    'BM25FrameSelector',
    'FrameCandidate',
    'FrameSelection',
    'DEFAULT_LEGAL_FRAME_FIXTURE',
    'LegalSample',
    'LegalSampleValidationError',
    'build_us_code_sample',
    'stable_mock_embedding',
    'HF_USCODE_DATASET_ID',
    'USCODE_BM25_PARQUET',
    'USCODE_EMBEDDINGS_PARQUET',
    'USCODE_LAWS_PARQUET',
    'USCODE_LOGIC_PROOF_SAMPLE_PARQUET',
    'USCODE_PARQUET_DIR',
    'USCodeParquetRecord',
    'iter_uscode_records_from_parquet',
    'load_hf_uscode_samples',
    'load_uscode_embeddings_from_parquet',
    'load_uscode_samples_from_parquet',
    'SpaCyLegalEncoder',
    'SpaCyLegalEncoding',
    'SpaCyModalCodec',
    'SpaCyModalCueFeature',
    'SpaCyModalDecoder',
    'SpaCyModalIRCompiler',
    'SpaCySentenceFeature',
    'SpaCyTokenFeature',
    'DecodedModalPhrase',
    'DecodedModalText',
    'DeterministicModalCompiler',
    'DeterministicModalLogicCodec',
    'ModalCompilationAmbiguity',
    'ModalCompilationResult',
    'ModalCompilerConfig',
    'ModalLogicCodecConfig',
    'ModalLogicCodecResult',
    'ModalProgramSynthesisHint',
    'decode_modal_ir_document',
    'decode_modal_ir_text',
    'decoded_modal_phrase_slot_text_map',
    'flogic_ontology_to_dict',
    'flogic_triples_to_graph_data',
    'flogic_triples_to_ontology',
    'import_graph_data_to_graph_engine',
    'import_modal_ir_to_graph_engine',
    'modal_formula_to_text',
    'modal_text_token_similarity',
    'modal_ir_to_flogic_triples',
    'modal_ir_to_neo4j_graph_data',
    'synthesis_hints_from_autoencoder_introspection',
    'synthesis_hints_from_autoencoder_introspections',
    'target_family_distribution_for_modal_ir',
    'target_family_for_modal_ir',
    'AdaptiveModalAutoencoder',
    'AutoencoderFeatureContribution',
    'ModalAutoencoderBaseline',
    'ModalAutoencoderTrainingState',
    'AutoencoderEvaluation',
    'AutoencoderIntrospection',
    'CodexCallCache',
    'CodexCallDecision',
    'CodexCallGateConfig',
    'ProverCompilationSignal',
    'TrustedHammerLeanstralFeatureBus',
    'DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION',
    'build_decompiler_structural_learning_target',
    'build_trusted_hammer_leanstral_feature_bus',
    'trusted_hammer_leanstral_feature_bus',
    'TrustedFeedbackTrainer',
    'TrustedFeedbackTrainerConfig',
    'TrustedFeedbackUpdateReport',
    'apply_trusted_feedback_weight_updates',
    'train_trusted_feedback',
    'cosine_similarity',
    'cosine_loss',
    'mse_loss',
    'cross_entropy_distribution_loss',
    'cross_entropy_loss',
    'evaluate_modal_prover_compilation',
    'frame_ranking_loss',
    'symbolic_validity_penalty',
    'ModalProverRouter',
    'ModalProverRouteResult',
    'ModalProverStatus',
    'ModalParserReport',
    'build_modal_parser_report',
    'LossSnapshot',
    'ModalLossTodoGenerator',
    'ModalOptimizerPolicy',
    'ModalOptimizationRun',
    'ModalOptimizationStep',
    'ModalProgramSynthesisTodoGenerator',
    'ModalTodo',
    'ModalTodoQueue',
    'ModalTodoSupervisor',
    'build_uscode_modal_daemon_arg_parser',
    'run_guarded_uscode_modal_daemon',
    'sample_train_validation_rows',
    # Critic
    'LogicCritic',
    'CriticScore',
    'CriticDimensions',
    # Optimizer
    'LogicOptimizer',
    'OptimizationReport',
    'OptimizationStrategy',
    # Session (DEPRECATED - Use LogicTheoremOptimizer)
    'TheoremSession',
    'SessionResult',
    'SessionConfig',
    # Session Contracts (NEW - Formalized, typed, validated)
    'LogicSessionConfig',
    'LogicSessionResult',
    'RoundResult',
    'ExtractionMetrics',
    'ConvergenceReason',
    # Harness (DEPRECATED - Use LogicTheoremOptimizer)
    'LogicHarness',
    'LogicPipelineHarness',
    'HarnessConfig',
    'HarnessResult',
    # Ontology
    'KnowledgeGraphStabilizer',
    'OntologyConsistencyChecker',
    # Phase 2.1: Prover Integration
    'ProverIntegrationAdapter',
    'ProverVerificationResult',
    'AggregatedProverResult',
    # Phase 2.3: LLM Backend
    'LLMBackendAdapter',
    'LLMRequest',
    'LLMResponse',
    'RouterBackend',
    # Phase 2.5: RAG Integration
    'RAGIntegration',
    'RAGContext',
    'RAGStatistics',
    # Future Enhancement 1: Neural-Symbolic Hybrid Prover
    'NeuralSymbolicHybridProver',
    'HybridStrategy',
    'NeuralResult',
    'SymbolicResult',
    'HybridProverResult',
    # Future Enhancement 2: Prompt Optimization
    'PromptOptimizer',
    'OptimizationStrategy',
    'PromptMetrics',
    'PromptTemplate',
    'OptimizationResult',
    # Future Enhancement 3: Real-time Ontology Evolution
    'OntologyEvolution',
    'UpdateStrategy',
    'EvolutionEvent',
    'OntologyVersion',
    'EvolutionMetrics',
    'UpdateCandidate',
    # Future Enhancement 4: Distributed Processing
    'DistributedProcessor',
    'TaskStatus',
    'WorkerStatus',
    'Task',
    'WorkerInfo',
    'DistributedResult',
    # Future Enhancement 5: Additional Theorem Provers
    'IsabelleProver',
    'VampireProver',
    'EProver',
    'AdditionalProversRegistry',
    'ProverResult',
    'ProverType',
    'ProofFormat',
    # Future Enhancement 6: Conflict Resolution
    'ConflictResolver',
    'ResolutionStrategy',
    'ConflictType',
    'Conflict',
    'Resolution',
    'ResolutionMetrics',
    # Future Enhancement 7: Automated Prompt Engineering
    'PromptEngineer',
    'SelectionMethod',
    'CrossoverMethod',
    'MutationMethod',
    'EvolutionResult',
    # Proof Trace Serialization
    'serialize_aggregated_proof_trace',
    'serialize_prover_result_trace',
    'proof_trace_to_json',
    'write_proof_trace_json',
    'serialize_dataclass_like',
    # Global nested-process resource scheduling
    'ResourceLane',
    'LaneReservation',
    'ResourceSchedulerConfig',
    'ResourceLeaseToken',
    'ResourceLease',
    'GlobalResourceScheduler',
    'get_global_resource_scheduler',
    'configure_global_resource_scheduler',
    'acquire_resource_lease',
    # Asynchronous immutable state evaluation
    'SnapshotVersions',
    'EvaluationSnapshot',
    'SnapshotEvaluationResult',
    'SnapshotBoundary',
    'SnapshotEvaluator',
    'SnapshotBackpressureTimeout',
    'canonical_holdout_version',
    # Semantic-family sharded evaluation
    'LEGAL_IR_EVALUATION_FAMILIES',
    'SharedEvaluationArtifacts',
    'FamilyShardRequest',
    'FamilyShardResult',
    'FamilyEvaluationAggregate',
    'LegalIRFamilyEvaluator',
    'aggregate_family_results',
    # Changed-scope incremental candidate validation
    'ValidationBoundary',
    'TypedASTScope',
    'ValidationScopeCatalog',
    'ChangedScopeRule',
    'ChangedScopeValidationPlan',
    'ChangedScopeValidationPlanner',
    'FrozenBaselineEvidence',
    'IncrementalValidationCheck',
    'IncrementalValidationRequest',
    'IncrementalValidationResult',
    'IncrementalValidationReport',
    'IncrementalCandidateValidator',
    'IncrementalValidationPlan',
    'IncrementalValidationPlanner',
    'IncrementalValidationRunner',
    'ImmutableBaselineEvidence',
    'ASTScope',
    'TransientValidationError',
    'plan_incremental_validation',
    'build_incremental_validation_plan',
    'map_changed_scope',
    'plan_changed_scope_validation',
    'validate_incremental_candidate',
    # Program-synthesis failure classification and recovery
    'FailureCategory',
    'FailureClassification',
    'FailureEvidenceStore',
    'FailureObservation',
    'FailurePolicy',
    'FailureRateReporter',
    'ProgramSynthesisFailureClassifier',
    'ProgramSynthesisFailureRecovery',
    'RecoveryAction',
    'RecoveryContext',
    'RecoveryLedger',
    'RecoveryOperations',
    'RecoveryOutcome',
    'RecoveryStatus',
]

__version__ = '0.1.0'


_DEPRECATED_EXPORT_REMOVAL_POLICY = {
    # Symbol: (deprecated_in, remove_in, migration_hint)
    "TheoremSession": (
        "0.2.0",
        "0.4.0",
        "Use LogicTheoremOptimizer from logic_theorem_optimizer.unified_optimizer.",
    ),
    "SessionConfig": (
        "0.2.0",
        "0.4.0",
        "Use OptimizerConfig from ipfs_datasets_py.optimizers.common.base_optimizer.",
    ),
    "SessionResult": (
        "0.2.0",
        "0.4.0",
        "Use standardized result dictionaries returned by LogicTheoremOptimizer.",
    ),
    # Kept for compatibility while unified optimizer adoption completes.
    "LogicExtractor": (
        "0.2.0",
        "0.4.0",
        "Use LogicTheoremOptimizer for end-to-end extraction/optimization workflows.",
    ),
}


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse semantic version strings like ``X.Y.Z`` (suffixes ignored)."""
    core = (version or "0.0.0").split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    padded = (parts + ["0", "0", "0"])[:3]
    try:
        return tuple(int(p) for p in padded)  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)


def _version_gte(left: str, right: str) -> bool:
    """Return ``True`` when semantic version ``left`` is >= ``right``."""
    return _parse_semver(left) >= _parse_semver(right)


def _enforce_export_version_gate(name: str, current_version: str | None = None) -> None:
    """Raise ImportError if a deprecated symbol has reached its removal version."""
    policy = _DEPRECATED_EXPORT_REMOVAL_POLICY.get(name)
    if policy is None:
        return

    deprecated_in, remove_in, migration_hint = policy
    effective_version = current_version or __version__
    if _version_gte(effective_version, remove_in):
        raise ImportError(
            f"{name} was deprecated in {deprecated_in} and removed in {remove_in}. "
            f"Current version is {effective_version}. {migration_hint}"
        )


def __getattr__(name):
    """Lazy imports to avoid circular dependencies."""
    if name in (
        'FailureCategory',
        'FailureClassification',
        'FailureEvidenceStore',
        'FailureObservation',
        'FailurePolicy',
        'FailureRateReporter',
        'ProgramSynthesisFailureClassifier',
        'ProgramSynthesisFailureRecovery',
        'RecoveryAction',
        'RecoveryContext',
        'RecoveryLedger',
        'RecoveryOperations',
        'RecoveryOutcome',
        'RecoveryStatus',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            program_synthesis_failures,
        )

        return getattr(program_synthesis_failures, name)
    if name in (
        'ValidationBoundary',
        'TypedASTScope',
        'ValidationScopeCatalog',
        'ChangedScopeRule',
        'ChangedScopeValidationPlan',
        'ChangedScopeValidationPlanner',
        'FrozenBaselineEvidence',
        'IncrementalValidationCheck',
        'IncrementalValidationRequest',
        'IncrementalValidationResult',
        'IncrementalValidationReport',
        'IncrementalCandidateValidator',
        'IncrementalValidationPlan',
        'IncrementalValidationPlanner',
        'IncrementalValidationRunner',
        'ImmutableBaselineEvidence',
        'ASTScope',
        'TransientValidationError',
        'plan_incremental_validation',
        'build_incremental_validation_plan',
        'map_changed_scope',
        'plan_changed_scope_validation',
        'validate_incremental_candidate',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            incremental_validation,
        )

        return getattr(incremental_validation, name)
    if name in (
        'SnapshotVersions',
        'EvaluationSnapshot',
        'SnapshotEvaluationResult',
        'SnapshotBoundary',
        'SnapshotEvaluator',
        'SnapshotBackpressureTimeout',
        'canonical_holdout_version',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import snapshot_evaluator

        return getattr(snapshot_evaluator, name)
    if name in (
        'LEGAL_IR_EVALUATION_FAMILIES',
        'SharedEvaluationArtifacts',
        'FamilyShardRequest',
        'FamilyShardResult',
        'FamilyEvaluationAggregate',
        'LegalIRFamilyEvaluator',
        'aggregate_family_results',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            legal_ir_family_evaluator,
        )

        return getattr(legal_ir_family_evaluator, name)
    if name in (
        'ResourceLane',
        'LaneReservation',
        'ResourceSchedulerConfig',
        'ResourceLeaseToken',
        'ResourceLease',
        'GlobalResourceScheduler',
        'get_global_resource_scheduler',
        'configure_global_resource_scheduler',
        'acquire_resource_lease',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler

        return getattr(resource_scheduler, name)
    if name in (
        'LogicTheoremOptimizerError',
        'OptimizerError',
        'ExtractionError',
        'ValidationError',
        'ProvingError',
        'RefinementError',
        'ConfigurationError',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.exceptions import (
            LogicTheoremOptimizerError,
            OptimizerError,
            ExtractionError,
            ValidationError,
            ProvingError,
            RefinementError,
            ConfigurationError,
        )
        return {
            'LogicTheoremOptimizerError': LogicTheoremOptimizerError,
            'OptimizerError': OptimizerError,
            'ExtractionError': ExtractionError,
            'ValidationError': ValidationError,
            'ProvingError': ProvingError,
            'RefinementError': RefinementError,
            'ConfigurationError': ConfigurationError,
        }[name]
    elif name == 'LogicTheoremOptimizer':
        # NEW: Unified optimizer using BaseOptimizer
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import LogicTheoremOptimizer
        return LogicTheoremOptimizer
    elif name in ('LogicExtractor', 'LogicExtractionContext', 'ExtractionResult', 'ExtractionMode', 'DataType'):
        if name == 'LogicExtractor':
            _enforce_export_version_gate(name)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
            LogicExtractor, LogicExtractionContext, ExtractionResult, ExtractionMode, DataType
        )
        if name == 'LogicExtractor':
            return LogicExtractor
        elif name == 'LogicExtractionContext':
            return LogicExtractionContext
        elif name == 'ExtractionMode':
            return ExtractionMode
        elif name == 'DataType':
            return DataType
        else:
            return ExtractionResult
    elif name in (
        'ModalLogicFamily',
        'ModalSystem',
        'ModalOperatorSpec',
        'ModalSemanticsSpec',
        'ModalParseProfile',
        'ModalRegistry',
        'DEFAULT_MODAL_REGISTRY',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
            DEFAULT_MODAL_REGISTRY,
            ModalLogicFamily,
            ModalOperatorSpec,
            ModalParseProfile,
            ModalRegistry,
            ModalSemanticsSpec,
            ModalSystem,
        )
        return {
            'DEFAULT_MODAL_REGISTRY': DEFAULT_MODAL_REGISTRY,
            'ModalLogicFamily': ModalLogicFamily,
            'ModalOperatorSpec': ModalOperatorSpec,
            'ModalParseProfile': ModalParseProfile,
            'ModalRegistry': ModalRegistry,
            'ModalSemanticsSpec': ModalSemanticsSpec,
            'ModalSystem': ModalSystem,
        }[name]
    elif name in (
        'ModalIRDocument',
        'ModalIRFormula',
        'ModalIRFrame',
        'ModalIRFrameLogic',
        'ModalIRFrameLogicTriple',
        'ModalIROperator',
        'ModalIRPredicate',
        'ModalIRProvenance',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
            ModalIRDocument,
            ModalIRFormula,
            ModalIRFrame,
            ModalIRFrameLogic,
            ModalIRFrameLogicTriple,
            ModalIROperator,
            ModalIRPredicate,
            ModalIRProvenance,
        )
        return {
            'ModalIRDocument': ModalIRDocument,
            'ModalIRFormula': ModalIRFormula,
            'ModalIRFrame': ModalIRFrame,
            'ModalIRFrameLogic': ModalIRFrameLogic,
            'ModalIRFrameLogicTriple': ModalIRFrameLogicTriple,
            'ModalIROperator': ModalIROperator,
            'ModalIRPredicate': ModalIRPredicate,
            'ModalIRProvenance': ModalIRProvenance,
        }[name]
    elif name in ('LegalModalParser', 'LegalSegment', 'ModalCueSpan'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (
            LegalModalParser,
            LegalSegment,
            ModalCueSpan,
        )
        return {
            'LegalModalParser': LegalModalParser,
            'LegalSegment': LegalSegment,
            'ModalCueSpan': ModalCueSpan,
        }[name]
    elif name in ('BM25FrameSelector', 'FrameCandidate', 'FrameSelection', 'DEFAULT_LEGAL_FRAME_FIXTURE'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
            BM25FrameSelector,
            DEFAULT_LEGAL_FRAME_FIXTURE,
            FrameCandidate,
            FrameSelection,
        )
        return {
            'BM25FrameSelector': BM25FrameSelector,
            'DEFAULT_LEGAL_FRAME_FIXTURE': DEFAULT_LEGAL_FRAME_FIXTURE,
            'FrameCandidate': FrameCandidate,
            'FrameSelection': FrameSelection,
        }[name]
    elif name in ('LegalSample', 'LegalSampleValidationError', 'build_us_code_sample', 'stable_mock_embedding'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
            LegalSample,
            LegalSampleValidationError,
            build_us_code_sample,
            stable_mock_embedding,
        )
        return {
            'LegalSample': LegalSample,
            'LegalSampleValidationError': LegalSampleValidationError,
            'build_us_code_sample': build_us_code_sample,
            'stable_mock_embedding': stable_mock_embedding,
        }[name]
    elif name in (
        'HF_USCODE_DATASET_ID',
        'USCODE_BM25_PARQUET',
        'USCODE_EMBEDDINGS_PARQUET',
        'USCODE_LAWS_PARQUET',
        'USCODE_LOGIC_PROOF_SAMPLE_PARQUET',
        'USCODE_PARQUET_DIR',
        'USCodeParquetRecord',
        'iter_uscode_records_from_parquet',
        'load_hf_uscode_samples',
        'load_uscode_embeddings_from_parquet',
        'load_uscode_samples_from_parquet',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
            HF_USCODE_DATASET_ID,
            USCODE_BM25_PARQUET,
            USCODE_EMBEDDINGS_PARQUET,
            USCODE_LAWS_PARQUET,
            USCODE_LOGIC_PROOF_SAMPLE_PARQUET,
            USCODE_PARQUET_DIR,
            USCodeParquetRecord,
            iter_uscode_records_from_parquet,
            load_hf_uscode_samples,
            load_uscode_embeddings_from_parquet,
            load_uscode_samples_from_parquet,
        )
        return {
            'HF_USCODE_DATASET_ID': HF_USCODE_DATASET_ID,
            'USCODE_BM25_PARQUET': USCODE_BM25_PARQUET,
            'USCODE_EMBEDDINGS_PARQUET': USCODE_EMBEDDINGS_PARQUET,
            'USCODE_LAWS_PARQUET': USCODE_LAWS_PARQUET,
            'USCODE_LOGIC_PROOF_SAMPLE_PARQUET': USCODE_LOGIC_PROOF_SAMPLE_PARQUET,
            'USCODE_PARQUET_DIR': USCODE_PARQUET_DIR,
            'USCodeParquetRecord': USCodeParquetRecord,
            'iter_uscode_records_from_parquet': iter_uscode_records_from_parquet,
            'load_hf_uscode_samples': load_hf_uscode_samples,
            'load_uscode_embeddings_from_parquet': load_uscode_embeddings_from_parquet,
            'load_uscode_samples_from_parquet': load_uscode_samples_from_parquet,
        }[name]
    elif name in (
        'SpaCyLegalEncoder',
        'SpaCyLegalEncoding',
        'SpaCyModalCodec',
        'SpaCyModalCueFeature',
        'SpaCyModalDecoder',
        'SpaCyModalIRCompiler',
        'SpaCySentenceFeature',
        'SpaCyTokenFeature',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
            SpaCyLegalEncoder,
            SpaCyLegalEncoding,
            SpaCyModalCodec,
            SpaCyModalCueFeature,
            SpaCyModalDecoder,
            SpaCyModalIRCompiler,
            SpaCySentenceFeature,
            SpaCyTokenFeature,
        )
        return {
            'SpaCyLegalEncoder': SpaCyLegalEncoder,
            'SpaCyLegalEncoding': SpaCyLegalEncoding,
            'SpaCyModalCodec': SpaCyModalCodec,
            'SpaCyModalCueFeature': SpaCyModalCueFeature,
            'SpaCyModalDecoder': SpaCyModalDecoder,
            'SpaCyModalIRCompiler': SpaCyModalIRCompiler,
            'SpaCySentenceFeature': SpaCySentenceFeature,
            'SpaCyTokenFeature': SpaCyTokenFeature,
        }[name]
    elif name in (
        'DeterministicModalLogicCodec',
        'DecodedModalPhrase',
        'DecodedModalText',
        'DeterministicModalCompiler',
        'ModalCompilationAmbiguity',
        'ModalCompilationResult',
        'ModalCompilerConfig',
        'ModalLogicCodecConfig',
        'ModalLogicCodecResult',
        'ModalProgramSynthesisHint',
        'decode_modal_ir_document',
        'decode_modal_ir_text',
        'decoded_modal_phrase_slot_text_map',
        'flogic_ontology_to_dict',
        'flogic_triples_to_graph_data',
        'flogic_triples_to_ontology',
        'import_graph_data_to_graph_engine',
        'import_modal_ir_to_graph_engine',
        'modal_formula_to_text',
        'modal_text_token_similarity',
        'modal_ir_to_flogic_triples',
        'modal_ir_to_neo4j_graph_data',
        'synthesis_hints_from_autoencoder_introspection',
        'synthesis_hints_from_autoencoder_introspections',
        'target_family_distribution_for_modal_ir',
        'target_family_for_modal_ir',
    ):
        from ipfs_datasets_py.logic.modal import (
            DecodedModalPhrase,
            DecodedModalText,
            DeterministicModalCompiler,
            DeterministicModalLogicCodec,
            ModalCompilationAmbiguity,
            ModalCompilationResult,
            ModalCompilerConfig,
            ModalLogicCodecConfig,
            ModalLogicCodecResult,
            ModalProgramSynthesisHint,
            decode_modal_ir_document,
            decode_modal_ir_text,
            decoded_modal_phrase_slot_text_map,
            flogic_ontology_to_dict,
            flogic_triples_to_graph_data,
            flogic_triples_to_ontology,
            import_graph_data_to_graph_engine,
            import_modal_ir_to_graph_engine,
            modal_formula_to_text,
            modal_text_token_similarity,
            modal_ir_to_flogic_triples,
            modal_ir_to_neo4j_graph_data,
            synthesis_hints_from_autoencoder_introspection,
            synthesis_hints_from_autoencoder_introspections,
            target_family_distribution_for_modal_ir,
            target_family_for_modal_ir,
        )
        return {
            'DecodedModalPhrase': DecodedModalPhrase,
            'DecodedModalText': DecodedModalText,
            'DeterministicModalCompiler': DeterministicModalCompiler,
            'DeterministicModalLogicCodec': DeterministicModalLogicCodec,
            'ModalCompilationAmbiguity': ModalCompilationAmbiguity,
            'ModalCompilationResult': ModalCompilationResult,
            'ModalCompilerConfig': ModalCompilerConfig,
            'ModalLogicCodecConfig': ModalLogicCodecConfig,
            'ModalLogicCodecResult': ModalLogicCodecResult,
            'ModalProgramSynthesisHint': ModalProgramSynthesisHint,
            'decode_modal_ir_document': decode_modal_ir_document,
            'decode_modal_ir_text': decode_modal_ir_text,
            'decoded_modal_phrase_slot_text_map': decoded_modal_phrase_slot_text_map,
            'flogic_ontology_to_dict': flogic_ontology_to_dict,
            'flogic_triples_to_graph_data': flogic_triples_to_graph_data,
            'flogic_triples_to_ontology': flogic_triples_to_ontology,
            'import_graph_data_to_graph_engine': import_graph_data_to_graph_engine,
            'import_modal_ir_to_graph_engine': import_modal_ir_to_graph_engine,
            'modal_formula_to_text': modal_formula_to_text,
            'modal_text_token_similarity': modal_text_token_similarity,
            'modal_ir_to_flogic_triples': modal_ir_to_flogic_triples,
            'modal_ir_to_neo4j_graph_data': modal_ir_to_neo4j_graph_data,
            'synthesis_hints_from_autoencoder_introspection': synthesis_hints_from_autoencoder_introspection,
            'synthesis_hints_from_autoencoder_introspections': synthesis_hints_from_autoencoder_introspections,
            'target_family_distribution_for_modal_ir': target_family_distribution_for_modal_ir,
            'target_family_for_modal_ir': target_family_for_modal_ir,
        }[name]
    elif name in (
        'AutoencoderEvaluation',
        'AdaptiveModalAutoencoder',
        'AutoencoderFeatureContribution',
        'AutoencoderIntrospection',
        'CodexCallCache',
        'CodexCallDecision',
        'CodexCallGateConfig',
        'ModalAutoencoderBaseline',
        'ModalAutoencoderTrainingState',
        'ProverCompilationSignal',
        'TrustedHammerLeanstralFeatureBus',
        'DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION',
        'build_decompiler_structural_learning_target',
        'build_trusted_hammer_leanstral_feature_bus',
        'trusted_hammer_leanstral_feature_bus',
        'cosine_similarity',
        'cosine_loss',
        'mse_loss',
        'cross_entropy_distribution_loss',
        'cross_entropy_loss',
        'evaluate_modal_prover_compilation',
        'frame_ranking_loss',
        'symbolic_validity_penalty',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
            AdaptiveModalAutoencoder,
            AutoencoderFeatureContribution,
            AutoencoderEvaluation,
            AutoencoderIntrospection,
            CodexCallCache,
            CodexCallDecision,
            CodexCallGateConfig,
            DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION,
            ModalAutoencoderBaseline,
            ModalAutoencoderTrainingState,
            ProverCompilationSignal,
            TrustedHammerLeanstralFeatureBus,
            build_decompiler_structural_learning_target,
            build_trusted_hammer_leanstral_feature_bus,
            cross_entropy_distribution_loss,
            cosine_loss,
            cosine_similarity,
            cross_entropy_loss,
            evaluate_modal_prover_compilation,
            frame_ranking_loss,
            mse_loss,
            symbolic_validity_penalty,
            trusted_hammer_leanstral_feature_bus,
        )
        return {
            'AdaptiveModalAutoencoder': AdaptiveModalAutoencoder,
            'AutoencoderFeatureContribution': AutoencoderFeatureContribution,
            'AutoencoderEvaluation': AutoencoderEvaluation,
            'AutoencoderIntrospection': AutoencoderIntrospection,
            'CodexCallCache': CodexCallCache,
            'CodexCallDecision': CodexCallDecision,
            'CodexCallGateConfig': CodexCallGateConfig,
            'ModalAutoencoderBaseline': ModalAutoencoderBaseline,
            'ModalAutoencoderTrainingState': ModalAutoencoderTrainingState,
            'ProverCompilationSignal': ProverCompilationSignal,
            'TrustedHammerLeanstralFeatureBus': TrustedHammerLeanstralFeatureBus,
            'DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION': DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION,
            'build_decompiler_structural_learning_target': build_decompiler_structural_learning_target,
            'build_trusted_hammer_leanstral_feature_bus': build_trusted_hammer_leanstral_feature_bus,
            'cosine_loss': cosine_loss,
            'cosine_similarity': cosine_similarity,
            'cross_entropy_distribution_loss': cross_entropy_distribution_loss,
            'cross_entropy_loss': cross_entropy_loss,
            'evaluate_modal_prover_compilation': evaluate_modal_prover_compilation,
            'frame_ranking_loss': frame_ranking_loss,
            'mse_loss': mse_loss,
            'symbolic_validity_penalty': symbolic_validity_penalty,
            'trusted_hammer_leanstral_feature_bus': trusted_hammer_leanstral_feature_bus,
        }[name]
    elif name in (
        'TrustedFeedbackTrainer',
        'TrustedFeedbackTrainerConfig',
        'TrustedFeedbackUpdateReport',
        'apply_trusted_feedback_weight_updates',
        'train_trusted_feedback',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            trusted_feedback_trainer,
        )

        return getattr(trusted_feedback_trainer, name)
    elif name in ('ModalProverRouter', 'ModalProverRouteResult', 'ModalProverStatus'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_prover_router import (
            ModalProverRouteResult,
            ModalProverRouter,
            ModalProverStatus,
        )
        return {
            'ModalProverRouteResult': ModalProverRouteResult,
            'ModalProverRouter': ModalProverRouter,
            'ModalProverStatus': ModalProverStatus,
        }[name]
    elif name in ('ModalParserReport', 'build_modal_parser_report'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_reporting import (
            ModalParserReport,
            build_modal_parser_report,
        )
        return {
            'ModalParserReport': ModalParserReport,
            'build_modal_parser_report': build_modal_parser_report,
        }[name]
    elif name in (
        'LossSnapshot',
        'ModalLossTodoGenerator',
        'ModalOptimizerPolicy',
        'ModalOptimizationRun',
        'ModalOptimizationStep',
        'ModalProgramSynthesisTodoGenerator',
        'ModalTodo',
        'ModalTodoQueue',
        'ModalTodoSupervisor',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
            LossSnapshot,
            ModalLossTodoGenerator,
            ModalOptimizerPolicy,
            ModalOptimizationRun,
            ModalOptimizationStep,
            ModalProgramSynthesisTodoGenerator,
            ModalTodo,
            ModalTodoQueue,
            ModalTodoSupervisor,
        )
        return {
            'LossSnapshot': LossSnapshot,
            'ModalLossTodoGenerator': ModalLossTodoGenerator,
            'ModalOptimizerPolicy': ModalOptimizerPolicy,
            'ModalOptimizationRun': ModalOptimizationRun,
            'ModalOptimizationStep': ModalOptimizationStep,
            'ModalProgramSynthesisTodoGenerator': ModalProgramSynthesisTodoGenerator,
            'ModalTodo': ModalTodo,
            'ModalTodoQueue': ModalTodoQueue,
            'ModalTodoSupervisor': ModalTodoSupervisor,
        }[name]
    elif name in (
        'build_uscode_modal_daemon_arg_parser',
        'run_guarded_uscode_modal_daemon',
        'sample_train_validation_rows',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
            build_uscode_modal_daemon_arg_parser,
            run_guarded_uscode_modal_daemon,
            sample_train_validation_rows,
        )
        return {
            'build_uscode_modal_daemon_arg_parser': build_uscode_modal_daemon_arg_parser,
            'run_guarded_uscode_modal_daemon': run_guarded_uscode_modal_daemon,
            'sample_train_validation_rows': sample_train_validation_rows,
        }[name]
    elif name == 'LogicCritic' or name == 'CriticScore' or name == 'CriticDimensions':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import (
            LogicCritic, CriticScore, CriticDimensions
        )
        if name == 'LogicCritic':
            return LogicCritic
        elif name == 'CriticScore':
            return CriticScore
        else:
            return CriticDimensions
    elif name == 'LogicOptimizer' or name == 'OptimizationReport':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer import (
            LogicOptimizer, OptimizationReport
        )
        if name == 'LogicOptimizer':
            return LogicOptimizer
        else:
            return OptimizationReport
    elif name == 'OptimizationStrategy':
        # Import from BaseOptimizer (no longer duplicated in logic_optimizer)
        from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationStrategy
        return OptimizationStrategy
    elif name in (
        'serialize_aggregated_proof_trace',
        'serialize_prover_result_trace',
        'proof_trace_to_json',
        'write_proof_trace_json',
        'serialize_dataclass_like',
    ):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_trace import (
            serialize_aggregated_proof_trace,
            serialize_prover_result_trace,
            proof_trace_to_json,
            write_proof_trace_json,
            serialize_dataclass_like,
        )
        return {
            'serialize_aggregated_proof_trace': serialize_aggregated_proof_trace,
            'serialize_prover_result_trace': serialize_prover_result_trace,
            'proof_trace_to_json': proof_trace_to_json,
            'write_proof_trace_json': write_proof_trace_json,
            'serialize_dataclass_like': serialize_dataclass_like,
        }[name]
    elif name == 'TheoremSession' or name == 'SessionResult' or name == 'SessionConfig':
        _enforce_export_version_gate(name)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.theorem_session import (
            TheoremSession, SessionResult, SessionConfig
        )
        if name == 'TheoremSession':
            return TheoremSession
        elif name == 'SessionResult':
            return SessionResult
        else:
            return SessionConfig
    elif name in ('LogicSessionConfig', 'LogicSessionResult', 'RoundResult', 'ExtractionMetrics', 'ConvergenceReason'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_session_contracts import (
            LogicSessionConfig, LogicSessionResult, RoundResult, ExtractionMetrics, ConvergenceReason
        )
        if name == 'LogicSessionConfig':
            return LogicSessionConfig
        elif name == 'LogicSessionResult':
            return LogicSessionResult
        elif name == 'RoundResult':
            return RoundResult
        elif name == 'ExtractionMetrics':
            return ExtractionMetrics
        else:
            return ConvergenceReason
    elif name == 'LogicHarness' or name == 'LogicPipelineHarness' or name == 'HarnessConfig' or name == 'HarnessResult':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_harness import (
            LogicHarness, LogicPipelineHarness, HarnessConfig, HarnessResult
        )
        if name == 'LogicHarness':
            return LogicHarness
        elif name == 'LogicPipelineHarness':
            return LogicPipelineHarness
        elif name == 'HarnessConfig':
            return HarnessConfig
        else:
            return HarnessResult
    elif name == 'KnowledgeGraphStabilizer' or name == 'OntologyConsistencyChecker':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.ontology_stabilizer import (
            KnowledgeGraphStabilizer, OntologyConsistencyChecker
        )
        if name == 'KnowledgeGraphStabilizer':
            return KnowledgeGraphStabilizer
        else:
            return OntologyConsistencyChecker
    elif name == 'ProverIntegrationAdapter' or name == 'ProverVerificationResult' or name == 'AggregatedProverResult':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
            ProverIntegrationAdapter, ProverVerificationResult, AggregatedProverResult
        )
        if name == 'ProverIntegrationAdapter':
            return ProverIntegrationAdapter
        elif name == 'ProverVerificationResult':
            return ProverVerificationResult
        else:
            return AggregatedProverResult
    elif name in {'LLMBackendAdapter', 'LLMRequest', 'LLMResponse', 'RouterBackend'}:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend import (
            LLMBackendAdapter, LLMRequest, LLMResponse, RouterBackend
        )
        if name == 'LLMBackendAdapter':
            return LLMBackendAdapter
        elif name == 'LLMRequest':
            return LLMRequest
        elif name == 'LLMResponse':
            return LLMResponse
        else:
            return RouterBackend
    elif name == 'RAGIntegration' or name == 'RAGContext' or name == 'RAGStatistics':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.rag_integration import (
            RAGIntegration, RAGContext, RAGStatistics
        )
        if name == 'RAGIntegration':
            return RAGIntegration
        elif name == 'RAGContext':
            return RAGContext
        else:
            return RAGStatistics
    elif name in ('NeuralSymbolicHybridProver', 'HybridStrategy', 'NeuralResult', 'SymbolicResult', 'HybridProverResult'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover import (
            NeuralSymbolicHybridProver, HybridStrategy, NeuralResult, SymbolicResult, HybridProverResult
        )
        if name == 'NeuralSymbolicHybridProver':
            return NeuralSymbolicHybridProver
        elif name == 'HybridStrategy':
            return HybridStrategy
        elif name == 'NeuralResult':
            return NeuralResult
        elif name == 'SymbolicResult':
            return SymbolicResult
        else:
            return HybridProverResult
    elif name in ('PromptOptimizer', 'OptimizationStrategy', 'PromptMetrics', 'PromptTemplate', 'OptimizationResult'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prompt_optimizer import (
            PromptOptimizer, OptimizationStrategy, PromptMetrics, PromptTemplate, OptimizationResult
        )
        if name == 'PromptOptimizer':
            return PromptOptimizer
        elif name == 'OptimizationStrategy':
            return OptimizationStrategy
        elif name == 'PromptMetrics':
            return PromptMetrics
        elif name == 'PromptTemplate':
            return PromptTemplate
        else:
            return OptimizationResult
    elif name in ('OntologyEvolution', 'UpdateStrategy', 'EvolutionEvent', 'OntologyVersion', 'EvolutionMetrics', 'UpdateCandidate'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.ontology_evolution import (
            OntologyEvolution, UpdateStrategy, EvolutionEvent, OntologyVersion, EvolutionMetrics, UpdateCandidate
        )
        if name == 'OntologyEvolution':
            return OntologyEvolution
        elif name == 'UpdateStrategy':
            return UpdateStrategy
        elif name == 'EvolutionEvent':
            return EvolutionEvent
        elif name == 'OntologyVersion':
            return OntologyVersion
        elif name == 'EvolutionMetrics':
            return EvolutionMetrics
        else:
            return UpdateCandidate
    elif name in ('DistributedProcessor', 'TaskStatus', 'WorkerStatus', 'Task', 'WorkerInfo', 'DistributedResult'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.distributed_processor import (
            DistributedProcessor, TaskStatus, WorkerStatus, Task, WorkerInfo, DistributedResult
        )
        if name == 'DistributedProcessor':
            return DistributedProcessor
        elif name == 'TaskStatus':
            return TaskStatus
        elif name == 'WorkerStatus':
            return WorkerStatus
        elif name == 'Task':
            return Task
        elif name == 'WorkerInfo':
            return WorkerInfo
        else:
            return DistributedResult
    elif name in ('IsabelleProver', 'VampireProver', 'EProver', 'AdditionalProversRegistry', 'ProverResult', 'ProverType', 'ProofFormat'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.additional_provers import (
            IsabelleProver, VampireProver, EProver, AdditionalProversRegistry, ProverResult, ProverType, ProofFormat
        )
        if name == 'IsabelleProver':
            return IsabelleProver
        elif name == 'VampireProver':
            return VampireProver
        elif name == 'EProver':
            return EProver
        elif name == 'AdditionalProversRegistry':
            return AdditionalProversRegistry
        elif name == 'ProverResult':
            return ProverResult
        elif name == 'ProverType':
            return ProverType
        else:
            return ProofFormat
    elif name in ('ConflictResolver', 'ResolutionStrategy', 'ConflictType', 'Conflict', 'Resolution', 'ResolutionMetrics'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.conflict_resolver import (
            ConflictResolver, ResolutionStrategy, ConflictType, Conflict, Resolution, ResolutionMetrics
        )
        if name == 'ConflictResolver':
            return ConflictResolver
        elif name == 'ResolutionStrategy':
            return ResolutionStrategy
        elif name == 'ConflictType':
            return ConflictType
        elif name == 'Conflict':
            return Conflict
        elif name == 'Resolution':
            return Resolution
        else:
            return ResolutionMetrics
    elif name in ('PromptEngineer', 'SelectionMethod', 'CrossoverMethod', 'MutationMethod', 'EvolutionResult'):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prompt_engineer import (
            PromptEngineer, SelectionMethod, CrossoverMethod, MutationMethod, EvolutionResult
        )
        if name == 'PromptEngineer':
            return PromptEngineer
        elif name == 'SelectionMethod':
            return SelectionMethod
        elif name == 'CrossoverMethod':
            return CrossoverMethod
        elif name == 'MutationMethod':
            return MutationMethod
        else:
            return EvolutionResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
