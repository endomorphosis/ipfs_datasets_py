import warnings

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import (
    CriticDimensions,
    CriticScore,
    DimensionScore,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    DataType,
    ExtractionMode,
    ExtractionResult,
    LogicExtractionContext,
    LogicalStatement,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.theorem_session import (
    SessionConfig,
    TheoremSession,
)


class FakeExtractor:
    def __init__(self) -> None:
        self.feedback = []

    def extract(self, context: LogicExtractionContext) -> ExtractionResult:
        statement = LogicalStatement(
            formula="A -> B",
            natural_language="If A then B",
            confidence=0.9,
            formalism="fol",
        )
        return ExtractionResult(
            statements=[statement],
            context=context,
            success=True,
        )

    def improve_from_feedback(self, feedback):
        self.feedback.append(feedback)


class FakeCritic:
    def evaluate(self, extraction_result: ExtractionResult) -> CriticScore:
        dimension_score = DimensionScore(
            dimension=CriticDimensions.SOUNDNESS,
            score=0.9,
            feedback="Looks good",
        )
        return CriticScore(
            overall=0.9,
            dimension_scores=[dimension_score],
            strengths=["sound"],
            weaknesses=[],
            recommendations=[],
        )


def test_theorem_session_smoke():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        extractor = FakeExtractor()
        critic = FakeCritic()
        session = TheoremSession(
            extractor,
            critic,
            config=SessionConfig(max_rounds=1, convergence_threshold=0.8),
        )

    result = session.run(
        data="All employees must complete training",
        context={
            "data_type": DataType.TEXT,
            "extraction_mode": ExtractionMode.FOL,
            "domain": "general",
        },
    )

    assert result.success is True
    assert result.converged is True
    assert result.num_rounds == 1
    assert result.extraction_result is not None
    assert len(result.extraction_result.statements) == 1
