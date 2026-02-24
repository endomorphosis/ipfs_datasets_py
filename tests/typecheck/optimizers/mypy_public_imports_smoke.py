"""Mypy smoke check for optimizer public imports.

Run:
    mypy --config-file mypy.ini ipfs_datasets_py/optimizers/tests/typecheck/mypy_public_imports_smoke.py
"""

from ipfs_datasets_py.optimizers.common.base_optimizer import BaseOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer import (
    LogicTheoremOptimizer,
)


def _typed_imports_smoke() -> tuple[type[BaseOptimizer], OntologyGenerator, OntologyCritic, LogicTheoremOptimizer]:
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    logic = LogicTheoremOptimizer()
    return BaseOptimizer, gen, critic, logic
