"""
Compatibility shim — business logic moved to ipfs_datasets_py.scrapers.medical.biomolecule_engine.

Do not add new code here. Use the canonical package location instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
	from ipfs_datasets_py.scrapers.medical.biomolecule_engine import *  # type: ignore  # noqa: F401,F403
except Exception:
	class BiomoleculeType(Enum):
		PROTEIN = "protein"
		PEPTIDE = "peptide"
		ANTIBODY = "antibody"
		SMALL_MOLECULE = "small_molecule"
		ENZYME = "enzyme"
		UNKNOWN = "unknown"


	class InteractionType(Enum):
		BINDING = "binding"
		INHIBITION = "inhibition"
		ACTIVATION = "activation"
		MODULATION = "modulation"


	@dataclass
	class BiomoleculeCandidate:
		name: str
		biomolecule_type: BiomoleculeType = BiomoleculeType.UNKNOWN
		uniprot_id: Optional[str] = None
		pubchem_id: Optional[str] = None
		sequence: Optional[str] = None
		structure: Optional[str] = None
		function: str = ""
		interactions: List[str] = field(default_factory=list)
		therapeutic_relevance: str = ""
		confidence_score: float = 0.5
		evidence_sources: List[str] = field(default_factory=list)
		metadata: Dict[str, Any] = field(default_factory=dict)


	class BiomoleculeDiscoveryEngine:
		def __init__(self, use_rag: bool = True) -> None:
			self.use_rag = use_rag
			self.discovered_biomolecules: Dict[str, BiomoleculeCandidate] = {}

		def _classify_biomolecule(self, name: str, context: str = "") -> BiomoleculeType:
			text = f"{name} {context}".lower()
			if "antibody" in text or " mab" in f" {text}":
				return BiomoleculeType.ANTIBODY
			if "enzyme" in text:
				return BiomoleculeType.ENZYME
			if "peptide" in text:
				return BiomoleculeType.PEPTIDE
			if "compound" in text or "molecule" in text:
				return BiomoleculeType.SMALL_MOLECULE
			if "protein" in text:
				return BiomoleculeType.PROTEIN
			return BiomoleculeType.UNKNOWN

		def _generate_mock_binders(self, target: str, max_results: int) -> List[BiomoleculeCandidate]:
			count = max(0, int(max_results))
			results: List[BiomoleculeCandidate] = []
			for index in range(count):
				confidence = max(0.0, min(1.0, 0.95 - (index * 0.05)))
				candidate = BiomoleculeCandidate(
					name=f"{target}-candidate-{index + 1}",
					biomolecule_type=BiomoleculeType.ANTIBODY,
					confidence_score=confidence,
					function=f"Candidate binder for {target}",
					interactions=[InteractionType.BINDING.value],
					evidence_sources=["mock"],
					metadata={"rank": index + 1},
				)
				results.append(candidate)
			return results

		def discover_protein_binders(
			self,
			target_protein: str,
			min_confidence: float = 0.5,
			max_results: int = 50,
		) -> List[BiomoleculeCandidate]:
			candidates = self._generate_mock_binders(target_protein, max_results)
			return [candidate for candidate in candidates if candidate.confidence_score >= min_confidence]

		def discover_enzyme_inhibitors(
			self,
			target_enzyme: str,
			min_confidence: float = 0.5,
			max_results: int = 50,
		) -> List[BiomoleculeCandidate]:
			candidates = self._generate_mock_binders(target_enzyme, max_results)
			for candidate in candidates:
				candidate.biomolecule_type = BiomoleculeType.SMALL_MOLECULE
				candidate.interactions = [InteractionType.INHIBITION.value]
				candidate.function = f"Candidate inhibitor for {target_enzyme}"
			return [candidate for candidate in candidates if candidate.confidence_score >= min_confidence]

		def discover_pathway_biomolecules(
			self,
			pathway_name: str,
			min_confidence: float = 0.5,
			max_results: int = 50,
		) -> List[BiomoleculeCandidate]:
			candidates = self._generate_mock_binders(pathway_name, max_results)
			for candidate in candidates:
				candidate.biomolecule_type = BiomoleculeType.PROTEIN
				candidate.interactions = [InteractionType.MODULATION.value]
				candidate.function = f"Candidate pathway modulator for {pathway_name}"
			return [candidate for candidate in candidates if candidate.confidence_score >= min_confidence]


	__all__ = [
		"BiomoleculeType",
		"InteractionType",
		"BiomoleculeCandidate",
		"BiomoleculeDiscoveryEngine",
	]
