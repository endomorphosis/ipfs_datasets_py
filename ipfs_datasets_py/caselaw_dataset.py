"""
Caselaw Access Project Dataset Integration

This module provides functionality to import and process the HuggingFace dataset
"justicedao/Caselaw_Access_Project_embeddings" and integrate it with the existing
GraphRAG pipeline for legal document search and analysis.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
import tempfile

try:
    import datasets
    from huggingface_hub import snapshot_download
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

logger = logging.getLogger(__name__)


class CaselawDatasetLoader:
    """
    Loader for the Caselaw Access Project dataset with fallback mechanisms
    for when network access is limited.
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.dataset_name = "justicedao/Caselaw_Access_Project_embeddings"
        self.cache_dir = cache_dir or os.path.expanduser("~/.cache/ipfs_datasets_py/caselaw")
        os.makedirs(self.cache_dir, exist_ok=True)
        
    def load_dataset(self, split: str = "train", max_samples: Optional[int] = None) -> Dict[str, Any]:
        """
        Load the Caselaw Access Project dataset with fallback to mock data.
        
        Args:
            split: Dataset split to load (train, test, validation)
            max_samples: Maximum number of samples to load (None for all)
            
        Returns:
            Dictionary containing dataset information and data
        """
        # Try to load from HuggingFace first
        if HF_AVAILABLE:
            try:
                dataset = self._load_from_huggingface(split, max_samples)
                if dataset:
                    return {
                        "status": "success",
                        "source": "huggingface",
                        "dataset": dataset,
                        "count": len(dataset)
                    }
            except Exception as e:
                logger.warning(f"Failed to load from HuggingFace: {e}")
        
        # Fallback to mock data
        logger.info("Using mock caselaw data for demonstration")
        mock_dataset = self._create_mock_dataset(max_samples or 100)
        return {
            "status": "success",
            "source": "mock",
            "dataset": mock_dataset,
            "count": len(mock_dataset)
        }
    
    def _load_from_huggingface(self, split: str, max_samples: Optional[int]) -> Optional[Any]:
        """Load dataset from HuggingFace Hub"""
        try:
            if max_samples:
                dataset = datasets.load_dataset(
                    self.dataset_name, 
                    split=f"{split}[:{max_samples}]"
                )
            else:
                dataset = datasets.load_dataset(self.dataset_name, split=split)
            
            logger.info(f"Successfully loaded {len(dataset)} samples from HuggingFace")
            return dataset
            
        except Exception as e:
            logger.error(f"HuggingFace loading failed: {e}")
            return None
    
    def _create_mock_dataset(self, count: int) -> List[Dict[str, Any]]:
        """Create mock caselaw dataset for testing and demonstration"""
        
        # Sample legal cases with realistic structure
        sample_cases = [
            {
                "id": "1954-brown-v-board",
                "title": "Brown v. Board of Education of Topeka",
                "court": "Supreme Court of the United States",
                "year": 1954,
                "citation": "347 U.S. 483",
                "topic": "civil rights",
                "jurisdiction": "federal",
                "text": """The Supreme Court held that racial segregation of children in public schools violated the Equal Protection Clause of the Fourteenth Amendment. The Court declared that separate educational facilities are inherently unequal, overturning the 'separate but equal' doctrine established in Plessy v. Ferguson (1896). This landmark decision marked a significant victory for the civil rights movement.""",
                "summary": "Landmark case declaring racial segregation in public schools unconstitutional",
                "legal_concepts": ["equal protection", "civil rights", "segregation", "education"],
                "precedent_value": "high",
                "embedding": [0.1] * 768  # Mock embedding vector
            },
            {
                "id": "1966-miranda-v-arizona", 
                "title": "Miranda v. Arizona",
                "court": "Supreme Court of the United States",
                "year": 1966,
                "citation": "384 U.S. 436",
                "topic": "criminal procedure",
                "jurisdiction": "federal",
                "text": """The Court ruled that detained criminal suspects must be informed of their constitutional right to an attorney and against self-incrimination prior to police questioning. The decision established the famous 'Miranda rights' that must be read to suspects during arrest. This ruling significantly impacted police procedures and criminal justice practices.""",
                "summary": "Established requirement for Miranda warnings during police custody",
                "legal_concepts": ["criminal procedure", "constitutional rights", "self-incrimination", "due process"],
                "precedent_value": "high",
                "embedding": [0.2] * 768
            },
            {
                "id": "1973-roe-v-wade",
                "title": "Roe v. Wade", 
                "court": "Supreme Court of the United States",
                "year": 1973,
                "citation": "410 U.S. 113",
                "topic": "privacy rights",
                "jurisdiction": "federal",
                "text": """The Court held that the Constitution protects a woman's liberty to choose to have an abortion without excessive government restriction. The decision was based on the Due Process Clause of the Fourteenth Amendment, which the Court said protected the right to privacy. The ruling established a framework for evaluating restrictions on abortion.""",
                "summary": "Established constitutional right to abortion under privacy doctrine",
                "legal_concepts": ["privacy rights", "due process", "reproductive rights", "constitutional law"],
                "precedent_value": "high",
                "embedding": [0.3] * 768
            },
            {
                "id": "1978-regents-v-bakke",
                "title": "Regents of the University of California v. Bakke",
                "court": "Supreme Court of the United States", 
                "year": 1978,
                "citation": "438 U.S. 265",
                "topic": "affirmative action",
                "jurisdiction": "federal",
                "text": """The Court held that while racial quotas in university admissions were unconstitutional, race could be considered as one factor among many in admissions decisions. The decision allowed affirmative action programs to continue but placed limits on their implementation. This case became a key precedent for subsequent affirmative action cases.""",
                "summary": "Allowed race as factor in university admissions while prohibiting quotas",
                "legal_concepts": ["affirmative action", "equal protection", "education", "racial discrimination"],
                "precedent_value": "high",
                "embedding": [0.4] * 768
            }
        ]
        
        # Generate additional mock cases by varying the sample cases
        mock_data = []
        base_cases = sample_cases.copy()
        
        for i in range(count):
            # Cycle through base cases and modify them
            base_case = base_cases[i % len(base_cases)].copy()
            
            if i >= len(base_cases):
                # Create variations for additional cases
                base_case["id"] = f"mock-case-{i}"
                base_case["year"] = 1950 + (i % 70)  # Years from 1950-2020
                base_case["citation"] = f"{300 + i} U.S. {100 + i}"
                
                # Vary some fields
                courts = ["Supreme Court", "Circuit Court", "District Court", "State Supreme Court"]
                topics = ["civil rights", "criminal procedure", "contract law", "tort law", "constitutional law"]
                jurisdictions = ["federal", "state", "local"]
                
                base_case["court"] = courts[i % len(courts)]
                base_case["topic"] = topics[i % len(topics)]
                base_case["jurisdiction"] = jurisdictions[i % len(jurisdictions)]
                
                # Create synthetic embedding (in real scenario this would be computed)
                base_case["embedding"] = [(i * 0.01) % 1.0] * 768
            
            mock_data.append(base_case)
        
        logger.info(f"Created {len(mock_data)} mock caselaw entries")
        return mock_data
    
    def get_dataset_info(self) -> Dict[str, Any]:
        """Get information about the dataset"""
        return {
            "name": self.dataset_name,
            "description": "Caselaw Access Project dataset with embeddings for legal document search",
            "fields": {
                "id": "Unique case identifier",
                "title": "Case title/name",
                "court": "Court that decided the case",
                "year": "Year of decision",
                "citation": "Legal citation",
                "topic": "Primary legal topic/area",
                "jurisdiction": "Legal jurisdiction (federal/state/local)",
                "text": "Full case text or summary",
                "summary": "Brief case summary",
                "legal_concepts": "List of legal concepts involved",
                "precedent_value": "Precedential importance (high/medium/low)",
                "embedding": "Vector embedding for semantic search"
            },
            "recommended_queries": [
                "civil rights cases involving education",
                "criminal procedure and constitutional rights",
                "Supreme Court decisions on privacy",
                "affirmative action in higher education",
                "equal protection clause interpretations"
            ]
        }


def load_caselaw_dataset(split: str = "train", max_samples: Optional[int] = None, 
                        cache_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to load the Caselaw Access Project dataset.
    
    Args:
        split: Dataset split to load
        max_samples: Maximum samples to load (None for all)
        cache_dir: Cache directory for dataset files
        
    Returns:
        Dictionary with dataset information and data
    """
    loader = CaselawDatasetLoader(cache_dir=cache_dir)
    return loader.load_dataset(split=split, max_samples=max_samples)


if __name__ == "__main__":
    # Test the loader
    print("Testing Caselaw Dataset Loader...")
    
    loader = CaselawDatasetLoader()
    result = loader.load_dataset(split="train", max_samples=10)
    
    print(f"✅ Loaded {result['count']} cases from {result['source']}")
    print("📊 Dataset info:", loader.get_dataset_info()["description"])
    
    if result["dataset"]:
        sample = result["dataset"][0]
        print(f"📄 Sample case: {sample['title']} ({sample['year']})")
        print(f"🏛️ Court: {sample['court']}")
        print(f"📋 Topic: {sample['topic']}")
        print(f"✨ Summary: {sample['summary'][:100]}...")