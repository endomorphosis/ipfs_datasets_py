"""
Caselaw Access Project Dataset Integration

This module provides functionality to import and process the HuggingFace dataset
"justicedao/Caselaw_Access_Project_embeddings" and integrate it with the existing
GraphRAG pipeline for legal document search and analysis.

The dataset contains legal cases with pre-computed embeddings for semantic search.
When the HuggingFace dataset is not available, it falls back to a comprehensive
mock dataset with realistic legal cases and synthetic embeddings.
"""

import os
import json
import logging
import random
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
import tempfile
import re

try:
    import datasets
    from huggingface_hub import snapshot_download, list_repo_files
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


class CaselawDatasetLoader:
    """
    Enhanced loader for the Caselaw Access Project dataset with comprehensive
    fallback mechanisms and proper embedding support.
    """
    
    def __init__(self, cache_dir: Optional[str] = None, embedding_dim: int = 768):
        self.dataset_name = "justicedao/Caselaw_Access_Project_embeddings"
        self.cache_dir = cache_dir or os.path.expanduser("~/.cache/ipfs_datasets_py/caselaw")
        self.embedding_dim = embedding_dim
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Enhanced legal case database for more realistic fallback
        self._legal_case_templates = self._load_comprehensive_case_database()
        
    def _load_comprehensive_case_database(self) -> List[Dict[str, Any]]:
        """Load a comprehensive database of legal cases for realistic fallback"""
        return [
            # Landmark Constitutional Cases
            {
                "id": "1803-marbury-v-madison",
                "title": "Marbury v. Madison",
                "full_caption": "William Marbury v. James Madison, Secretary of State of the United States",
                "citation": "5 U.S. 137 (1803)",
                "short_citation": "5 U.S. 137", 
                "case_number": "No. 1803-001",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1803,
                "topic": "constitutional law",
                "jurisdiction": "federal",
                "text": """Chief Justice Marshall established the principle of judicial review, declaring that the Supreme Court has the authority to review and strike down laws, statutes, and government actions that violate the Constitution. This foundational case established the Court as a co-equal branch of government with the power to interpret the Constitution.""",
                "summary": "Established judicial review as fundamental principle of constitutional law",
                "legal_concepts": ["judicial review", "constitutional interpretation", "separation of powers", "federalism"],
                "precedent_value": "high",
                "case_type": "constitutional",
                "outcome": "landmark_precedent",
                "cited_by_count": 15000,
                "precedent_citations": [],  # Cases this case cites as precedent
                "citing_cases": [],  # Cases that cite this case (will be populated)
                "legal_doctrines": ["judicial review", "constitutional supremacy"]
            },
            {
                "id": "1954-brown-v-board",
                "title": "Brown v. Board of Education of Topeka",
                "full_caption": "Oliver L. Brown, et al. v. Board of Education of Topeka, et al.",
                "citation": "347 U.S. 483 (1954)",
                "short_citation": "347 U.S. 483",
                "case_number": "No. 1",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1954,
                "topic": "civil rights",
                "jurisdiction": "federal",
                "text": """The Supreme Court unanimously held that racial segregation of children in public schools violated the Equal Protection Clause of the Fourteenth Amendment. The Court declared that separate educational facilities are inherently unequal, overturning the 'separate but equal' doctrine established in Plessy v. Ferguson (1896). This landmark decision marked a significant victory for the civil rights movement and catalyzed nationwide desegregation efforts.""",
                "summary": "Landmark case declaring racial segregation in public schools unconstitutional",
                "legal_concepts": ["equal protection", "civil rights", "segregation", "education", "fourteenth amendment"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "landmark_precedent",
                "cited_by_count": 25000,
                "precedent_citations": ["Plessy v. Ferguson, 163 U.S. 537 (1896)"],
                "citing_cases": [],
                "legal_doctrines": ["equal protection", "separate but equal doctrine"]
            },
            {
                "id": "1966-miranda-v-arizona", 
                "title": "Miranda v. Arizona",
                "full_caption": "Ernesto Arturo Miranda v. State of Arizona",
                "citation": "384 U.S. 436 (1966)",
                "short_citation": "384 U.S. 436",
                "case_number": "No. 759",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1966,
                "topic": "criminal procedure",
                "jurisdiction": "federal",
                "text": """The Court ruled that detained criminal suspects must be informed of their constitutional right to an attorney and against self-incrimination prior to police questioning. The decision established the famous 'Miranda rights' that must be read to suspects during arrest. This ruling significantly impacted police procedures and criminal justice practices nationwide, requiring law enforcement to balance effective investigation with constitutional protections.""",
                "summary": "Established requirement for Miranda warnings during police custody",
                "legal_concepts": ["criminal procedure", "constitutional rights", "self-incrimination", "due process", "fifth amendment"],
                "precedent_value": "high",
                "case_type": "criminal_law",
                "outcome": "landmark_precedent",
                "cited_by_count": 20000,
                "precedent_citations": ["Escobedo v. Illinois, 378 U.S. 478 (1964)"],
                "citing_cases": [],
                "legal_doctrines": ["Miranda rights", "Fifth Amendment privilege", "custodial interrogation"]
            },
            {
                "id": "1973-roe-v-wade",
                "title": "Roe v. Wade", 
                "full_caption": "Jane Roe, et al. v. Henry Wade, District Attorney of Dallas County",
                "citation": "410 U.S. 113 (1973)",
                "short_citation": "410 U.S. 113",
                "case_number": "No. 70-18",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1973,
                "topic": "privacy rights",
                "jurisdiction": "federal",
                "text": """The Court held that the Constitution protects a woman's liberty to choose to have an abortion without excessive government restriction. The decision was based on the Due Process Clause of the Fourteenth Amendment, which the Court said protected the right to privacy. The ruling established a trimester framework for evaluating restrictions on abortion, balancing state interests in maternal health and potential life with individual privacy rights.""",
                "summary": "Established constitutional right to abortion under privacy doctrine",
                "legal_concepts": ["privacy rights", "due process", "reproductive rights", "constitutional law", "fourteenth amendment"],
                "precedent_value": "high",
                "case_type": "constitutional",
                "outcome": "landmark_precedent",
                "cited_by_count": 18000,
                "precedent_citations": ["Griswold v. Connecticut, 381 U.S. 479 (1965)"],
                "citing_cases": [],
                "legal_doctrines": ["substantive due process", "privacy doctrine", "reproductive autonomy"]
            },
            {
                "id": "1978-regents-v-bakke",
                "title": "Regents of the University of California v. Bakke",
                "court": "Supreme Court of the United States", 
                "year": 1978,
                "citation": "438 U.S. 265",
                "topic": "affirmative action",
                "jurisdiction": "federal",
                "text": """The Court held that while racial quotas in university admissions were unconstitutional, race could be considered as one factor among many in admissions decisions to achieve educational diversity. The decision allowed affirmative action programs to continue but placed constitutional limits on their implementation. This case became a key precedent for subsequent affirmative action cases and shaped decades of education policy.""",
                "summary": "Allowed race as factor in university admissions while prohibiting quotas",
                "legal_concepts": ["affirmative action", "equal protection", "education", "racial discrimination", "diversity"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "landmark_precedent",
                "cited_by_count": 12000
            },
            # Additional Constitutional Cases
            {
                "id": "1919-schenck-v-us",
                "title": "Schenck v. United States",
                "court": "Supreme Court of the United States",
                "year": 1919,
                "citation": "249 U.S. 47",
                "topic": "first amendment",
                "jurisdiction": "federal",
                "text": """Justice Holmes established the 'clear and present danger' test for restrictions on speech, ruling that the First Amendment does not protect speech that creates a clear and present danger of bringing about substantive evils that Congress has a right to prevent. The case arose during World War I and involved defendants who distributed leaflets opposing the military draft.""",
                "summary": "Established clear and present danger test for First Amendment restrictions",
                "legal_concepts": ["first amendment", "free speech", "clear and present danger", "wartime restrictions"],
                "precedent_value": "high",
                "case_type": "constitutional",
                "outcome": "landmark_precedent",
                "cited_by_count": 8000
            },
            {
                "id": "1963-gideon-v-wainwright",
                "title": "Gideon v. Wainwright",
                "court": "Supreme Court of the United States",
                "year": 1963,
                "citation": "372 U.S. 335",
                "topic": "criminal procedure",
                "jurisdiction": "federal",
                "text": """The Court unanimously ruled that state courts are required under the Sixth and Fourteenth Amendments to provide counsel in criminal cases for defendants unable to afford their own attorneys. This extended the right to counsel previously established for federal courts to state court proceedings, fundamentally changing the criminal justice system.""",
                "summary": "Established right to counsel for indigent defendants in state criminal cases",
                "legal_concepts": ["right to counsel", "sixth amendment", "fourteenth amendment", "criminal procedure", "due process"],
                "precedent_value": "high",
                "case_type": "criminal_law",
                "outcome": "landmark_precedent",
                "cited_by_count": 15000
            },
            {
                "id": "1964-nyt-v-sullivan",
                "title": "New York Times Co. v. Sullivan",
                "court": "Supreme Court of the United States",
                "year": 1964,
                "citation": "376 U.S. 254",
                "topic": "first amendment",
                "jurisdiction": "federal",
                "text": """The Court established that the First Amendment protects the publication of all statements about public officials, even false ones, unless they are made with 'actual malice' - knowledge of falsity or reckless disregard for the truth. This decision created a higher standard for public officials to prove libel and strengthened freedom of the press.""",
                "summary": "Established actual malice standard for libel cases involving public officials",
                "legal_concepts": ["first amendment", "freedom of press", "libel", "actual malice", "public officials"],
                "precedent_value": "high",
                "case_type": "constitutional",
                "outcome": "landmark_precedent",
                "cited_by_count": 10000
            },
            # Additional cases to reach larger dataset...
            {
                "id": "1896-plessy-v-ferguson",
                "title": "Plessy v. Ferguson",
                "court": "Supreme Court of the United States",
                "year": 1896,
                "citation": "163 U.S. 537",
                "topic": "civil rights",
                "jurisdiction": "federal",
                "text": """The Court upheld the constitutionality of racial segregation laws for public facilities under the doctrine of 'separate but equal'. This decision provided constitutional sanction for laws designed to achieve racial segregation and remained in effect until Brown v. Board of Education (1954). The case arose from Homer Plessy's challenge to Louisiana's Separate Car Act.""",
                "summary": "Established 'separate but equal' doctrine allowing racial segregation",
                "legal_concepts": ["separate but equal", "racial segregation", "equal protection", "jim crow laws"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "overturned_precedent",
                "cited_by_count": 8000
            },
            {
                "id": "2015-obergefell-v-hodges",
                "title": "Obergefell v. Hodges",
                "court": "Supreme Court of the United States",
                "year": 2015,
                "citation": "576 U.S. 644",
                "topic": "civil rights",
                "jurisdiction": "federal",
                "text": """The Court held that the fundamental right to marry is guaranteed to same-sex couples by both the Due Process Clause and the Equal Protection Clause of the Fourteenth Amendment. The decision requires all states to issue marriage licenses to same-sex couples and to recognize same-sex marriages performed in other jurisdictions.""",
                "summary": "Established constitutional right to same-sex marriage nationwide",
                "legal_concepts": ["marriage equality", "due process", "equal protection", "fundamental rights", "same-sex marriage"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "landmark_precedent",
                "cited_by_count": 5000,
                "full_caption": "James Obergefell, et al. v. Richard Hodges, Director, Ohio Department of Health, et al.",
                "short_citation": "576 U.S. 644",
                "case_number": "No. 14-556",
                "court_abbrev": "SCOTUS", 
                "precedent_citations": ["Lawrence v. Texas, 539 U.S. 558 (2003)", "United States v. Windsor, 570 U.S. 744 (2013)"],
                "citing_cases": [],
                "legal_doctrines": ["marriage equality", "substantive due process", "equal protection analysis"]
            },
            
            # Qualified Immunity Cases - Important for Case Shepherding
            {
                "id": "1982-harlow-v-fitzgerald",
                "title": "Harlow v. Fitzgerald",
                "full_caption": "Bryce N. Harlow, et al. v. A. Ernest Fitzgerald",
                "citation": "457 U.S. 800 (1982)",
                "short_citation": "457 U.S. 800",
                "case_number": "No. 80-945",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1982,
                "topic": "qualified immunity",
                "jurisdiction": "federal",
                "text": """The Court established the modern standard for qualified immunity, holding that government officials performing discretionary functions are shielded from liability for civil damages unless their conduct violates clearly established statutory or constitutional rights of which a reasonable person would have known. This decision refined the qualified immunity doctrine from a subjective test to an objective one.""",
                "summary": "Established objective standard for qualified immunity protection",
                "legal_concepts": ["qualified immunity", "civil rights", "section 1983", "clearly established law", "objective reasonableness"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "landmark_precedent",
                "cited_by_count": 8500,
                "precedent_citations": ["Pierson v. Ray, 386 U.S. 547 (1967)", "Wood v. Strickland, 420 U.S. 308 (1975)"],
                "citing_cases": [],
                "legal_doctrines": ["qualified immunity doctrine", "clearly established law standard"]
            },
            {
                "id": "1967-pierson-v-ray",
                "title": "Pierson v. Ray",
                "full_caption": "Reverend Robert Pierson, et al. v. Ray, et al.",
                "citation": "386 U.S. 547 (1967)",
                "short_citation": "386 U.S. 547",
                "case_number": "No. 59",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 1967,
                "topic": "qualified immunity",
                "jurisdiction": "federal",
                "text": """The Court established that police officers are entitled to the same immunity as other executive officials when acting under color of state law in good faith and with probable cause. This case created the foundation for qualified immunity doctrine, protecting government officials from civil liability when their actions are objectively reasonable.""",
                "summary": "Established foundation of qualified immunity doctrine for law enforcement",
                "legal_concepts": ["qualified immunity", "good faith immunity", "police liability", "section 1983", "civil rights"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "foundational_precedent",
                "cited_by_count": 9500,
                "precedent_citations": [],
                "citing_cases": ["Harlow v. Fitzgerald, 457 U.S. 800 (1982)"],
                "legal_doctrines": ["qualified immunity doctrine", "good faith immunity"]
            },
            {
                "id": "2001-saucier-v-katz",
                "title": "Saucier v. Katz",
                "full_caption": "Donald J. Saucier v. Elliot Katz",
                "citation": "533 U.S. 194 (2001)",
                "short_citation": "533 U.S. 194", 
                "case_number": "No. 99-1977",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 2001,
                "topic": "qualified immunity",
                "jurisdiction": "federal",
                "text": """The Court established a mandatory two-step analysis for qualified immunity cases: first, determine whether the facts alleged show that an officer's conduct violated a constitutional right, and second, determine whether the right was 'clearly established' at the time of the alleged violation. This sequential approach aimed to promote the development of constitutional precedent.""",
                "summary": "Established two-step sequential analysis for qualified immunity cases",
                "legal_concepts": ["qualified immunity", "clearly established law", "constitutional rights", "excessive force", "sequential analysis"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "procedural_precedent",
                "cited_by_count": 7200,
                "precedent_citations": ["Harlow v. Fitzgerald, 457 U.S. 800 (1982)"],
                "citing_cases": ["Pearson v. Callahan, 555 U.S. 223 (2009)"],
                "legal_doctrines": ["sequential analysis", "clearly established law standard", "constitutional development"]
            },
            {
                "id": "2009-pearson-v-callahan",
                "title": "Pearson v. Callahan",
                "full_caption": "Afton Pearson, et al. v. Darin Callahan",
                "citation": "555 U.S. 223 (2009)",
                "short_citation": "555 U.S. 223",
                "case_number": "No. 07-751",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS",
                "year": 2009,
                "topic": "qualified immunity",
                "jurisdiction": "federal",
                "text": """The Court overruled the mandatory sequential approach from Saucier v. Katz, holding that judges should have discretion to decide which of the two prongs of qualified immunity analysis to address first. Judges may now bypass the constitutional question and decide cases solely on clearly established law grounds, which some critics argue has reduced constitutional development.""",
                "summary": "Eliminated mandatory sequential analysis, allowing judges discretion in qualified immunity cases",
                "legal_concepts": ["qualified immunity", "judicial discretion", "clearly established law", "constitutional avoidance", "procedural flexibility"],
                "precedent_value": "high",
                "case_type": "civil_rights",
                "outcome": "procedural_modification",
                "cited_by_count": 6800,
                "precedent_citations": ["Saucier v. Katz, 533 U.S. 194 (2001)", "Harlow v. Fitzgerald, 457 U.S. 800 (1982)"],
                "citing_cases": [],
                "legal_doctrines": ["flexible qualified immunity analysis", "constitutional avoidance doctrine"]
            },
            {
                "id": "2020-taylor-v-riojas", 
                "title": "Taylor v. Riojas",
                "full_caption": "Trent Michael Taylor v. Stevens Riojas, et al.",
                "citation": "141 S. Ct. 52 (2020)",
                "short_citation": "141 S. Ct. 52",
                "case_number": "No. 19-1261",
                "court": "Supreme Court of the United States",
                "court_abbrev": "SCOTUS", 
                "year": 2020,
                "topic": "qualified immunity",
                "jurisdiction": "federal",
                "text": """The Court reversed a Fifth Circuit decision granting qualified immunity to prison officials who housed an inmate in 'shockingly unsanitary' conditions for six days. The Court held that no reasonable official could have believed that it was constitutional to house an inmate in such deplorable conditions, demonstrating rare unanimous rejection of qualified immunity defense.""",
                "summary": "Rare Supreme Court reversal of qualified immunity grant in prison conditions case",
                "legal_concepts": ["qualified immunity", "prison conditions", "cruel and unusual punishment", "eighth amendment", "obviously unconstitutional"],
                "precedent_value": "moderate",
                "case_type": "civil_rights", 
                "outcome": "immunity_denied",
                "cited_by_count": 850,
                "precedent_citations": ["Hope v. Pelzer, 536 U.S. 730 (2002)"],
                "citing_cases": [],
                "legal_doctrines": ["obvious constitutional violation", "prison conditions standards"]
            }
        ]
    
    def _generate_realistic_embedding(self, case_data: Dict[str, Any], seed: int = None) -> List[float]:
        """
        Generate realistic embeddings based on case content and legal concepts.
        Uses semantic features to create embeddings that reflect legal similarity.
        """
        if not NUMPY_AVAILABLE:
            # Simple deterministic embedding generation without numpy
            text_content = f"{case_data.get('text', '')} {case_data.get('summary', '')} {' '.join(case_data.get('legal_concepts', []))}"
            
            # Use hash-based approach for deterministic embeddings
            import hashlib
            text_bytes = text_content.encode('utf-8')
            hash_obj = hashlib.sha256(text_bytes)
            
            # Generate embedding values from hash
            embedding = []
            for i in range(self.embedding_dim):
                # Create pseudo-random but deterministic values
                sub_hash = hashlib.sha256(f"{hash_obj.hexdigest()}_{i}".encode()).hexdigest()
                # Convert hex to float in range [-1, 1]
                hex_val = int(sub_hash[:8], 16)
                normalized_val = (hex_val / (16**8 - 1)) * 2 - 1
                embedding.append(normalized_val)
            
            return embedding
        
        # Enhanced embedding generation with numpy
        if seed is not None:
            np.random.seed(seed)
        
        # Create base embedding
        embedding = np.random.randn(self.embedding_dim).astype(float)
        
        # Add semantic components based on legal concepts
        legal_concepts = case_data.get('legal_concepts', [])
        concept_weights = {
            'constitutional law': [0.8, 0.1, 0.2, 0.9],
            'civil rights': [0.7, 0.8, 0.1, 0.3],
            'criminal procedure': [0.2, 0.9, 0.8, 0.1],
            'first amendment': [0.9, 0.2, 0.1, 0.7],
            'due process': [0.6, 0.7, 0.8, 0.5],
            'equal protection': [0.8, 0.8, 0.2, 0.4],
            'privacy rights': [0.3, 0.2, 0.9, 0.8],
            'affirmative action': [0.7, 0.8, 0.3, 0.6]
        }
        
        # Apply concept-based modifications
        for concept in legal_concepts:
            if concept in concept_weights:
                weights = concept_weights[concept]
                # Apply weights to different regions of the embedding
                for i, weight in enumerate(weights):
                    start_idx = i * (self.embedding_dim // 4)
                    end_idx = (i + 1) * (self.embedding_dim // 4)
                    embedding[start_idx:end_idx] *= weight
        
        # Add temporal component based on year
        year = case_data.get('year', 1950)
        year_factor = (year - 1800) / 200  # Normalize year to [0, 1] range
        embedding[:10] += year_factor * 0.5  # Add year signature to first 10 dimensions
        
        # Add court hierarchy component
        court_weights = {
            'Supreme Court of the United States': 1.0,
            'Supreme Court': 1.0,
            'Circuit Court': 0.7,
            'District Court': 0.4,
            'State Supreme Court': 0.6,
            'State Appellate Court': 0.3
        }
        court = case_data.get('court', '')
        court_weight = court_weights.get(court, 0.5)
        embedding[10:20] *= court_weight
        
        # Normalize to unit vector
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding.tolist()
        
    def load_dataset(self, split: str = "train", max_samples: Optional[int] = None) -> Dict[str, Any]:
        """
        Load the Caselaw Access Project dataset with enhanced fallback to comprehensive mock data.
        
        Args:
            split: Dataset split to load (train, test, validation)
            max_samples: Maximum number of samples to load (None for all)
            
        Returns:
            Dictionary containing dataset information and data with proper embeddings
        """
        # Try to load from HuggingFace first
        if HF_AVAILABLE:
            try:
                dataset = self._load_from_huggingface(split, max_samples)
                if dataset:
                    logger.info(f"Successfully loaded {len(dataset)} cases from HuggingFace")
                    return {
                        "status": "success",
                        "source": "huggingface",
                        "dataset": dataset,
                        "count": len(dataset),
                        "embedding_dim": self._detect_embedding_dimension(dataset[0] if dataset else None)
                    }
            except Exception as e:
                logger.warning(f"Failed to load from HuggingFace: {e}")
        
        # Enhanced fallback to comprehensive mock data
        logger.info("Using enhanced comprehensive caselaw data for demonstration")
        mock_dataset = self._create_comprehensive_mock_dataset(max_samples or 1000)
        return {
            "status": "success",
            "source": "comprehensive_mock",
            "dataset": mock_dataset,
            "count": len(mock_dataset),
            "embedding_dim": self.embedding_dim
        }
    
    def _detect_embedding_dimension(self, sample_case: Optional[Dict[str, Any]]) -> int:
        """Detect the embedding dimension from a sample case"""
        if not sample_case:
            return self.embedding_dim
            
        for key in ['embedding', 'embeddings', 'vector', 'features']:
            if key in sample_case and isinstance(sample_case[key], list):
                return len(sample_case[key])
        
        return self.embedding_dim
    
    def _load_from_huggingface(self, split: str, max_samples: Optional[int]) -> Optional[List[Dict[str, Any]]]:
        """Enhanced HuggingFace dataset loading with better error handling"""
        try:
            logger.info(f"Attempting to load HuggingFace dataset: {self.dataset_name}")
            
            # Try different split specifications
            split_variants = [
                f"{split}[:{max_samples}]" if max_samples else split,
                f"{split}[:100]",  # Fallback to smaller sample
                "train[:100]",     # Try train split
                "[:100]"           # Try without split specification
            ]
            
            for split_spec in split_variants:
                try:
                    dataset = datasets.load_dataset(
                        self.dataset_name, 
                        split=split_spec,
                        trust_remote_code=True  # Some datasets require this
                    )
                    
                    # Convert to our expected format
                    processed_dataset = []
                    for item in dataset:
                        # Handle different possible field names
                        case_data = self._normalize_huggingface_case(item)
                        processed_dataset.append(case_data)
                    
                    logger.info(f"Successfully loaded {len(processed_dataset)} samples from HuggingFace")
                    return processed_dataset
                    
                except Exception as e:
                    logger.debug(f"Split variant {split_spec} failed: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"HuggingFace loading failed: {e}")
            return None
    
    def _normalize_huggingface_case(self, raw_case: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize HuggingFace case data to our expected format"""
        # Common field mappings from different possible schemas
        field_mappings = {
            'case_id': ['id', 'case_id', 'identifier', '_id'],
            'title': ['title', 'case_name', 'name', 'case_title'],
            'court': ['court', 'court_name', 'jurisdiction_court'],
            'year': ['year', 'decision_date', 'date_decided'],
            'citation': ['citation', 'citations', 'legal_citation'],
            'text': ['text', 'full_text', 'opinion_text', 'content'],
            'summary': ['summary', 'abstract', 'headnotes'],
            'embedding': ['embedding', 'embeddings', 'vector', 'features']
        }
        
        normalized = {}
        
        # Map fields using the mapping table
        for our_field, possible_fields in field_mappings.items():
            for field in possible_fields:
                if field in raw_case and raw_case[field] is not None:
                    normalized[our_field] = raw_case[field]
                    break
        
        # Set defaults for missing required fields
        defaults = {
            'id': f"case-{hash(str(raw_case)) % 10000}",
            'title': "Unknown Case",
            'court': "Unknown Court",
            'year': 2000,
            'citation': "Unknown Citation",
            'topic': "general",
            'jurisdiction': "unknown",
            'text': normalized.get('summary', 'No text available'),
            'summary': normalized.get('text', 'No summary available')[:200],
            'legal_concepts': [],
            'precedent_value': "medium",
            'case_type': "general",
            'outcome': "decided",
            'cited_by_count': 0
        }
        
        for key, default_value in defaults.items():
            if key not in normalized:
                normalized[key] = default_value
        
        # Ensure embedding exists
        if 'embedding' not in normalized:
            normalized['embedding'] = self._generate_realistic_embedding(normalized)
        
        # Extract legal concepts from text if not provided
        if not normalized.get('legal_concepts'):
            normalized['legal_concepts'] = self._extract_legal_concepts_from_text(
                normalized.get('text', '') + ' ' + normalized.get('summary', '')
            )
        
        return normalized
        
    def _extract_legal_concepts_from_text(self, text: str) -> List[str]:
        """Extract legal concepts from case text using regex patterns"""
        concepts = []
        text_lower = text.lower()
        
        concept_patterns = {
            'constitutional law': r'constitution|constitutional|amendment|bill of rights',
            'civil rights': r'civil rights|discrimination|equal protection|segregation',
            'criminal procedure': r'criminal|arrest|miranda|search and seizure|warrant',
            'first amendment': r'first amendment|free speech|freedom of press|religion',
            'due process': r'due process|procedural|substantive due process',
            'equal protection': r'equal protection|discrimination|class|suspect',
            'privacy rights': r'privacy|private|personal|intimate|reproductive',
            'commerce clause': r'commerce|interstate|regulation|economic',
            'separation of powers': r'separation|powers|executive|legislative|judicial',
            'federalism': r'federal|state|local|sovereignty|supremacy'
        }
        
        for concept, pattern in concept_patterns.items():
            if re.search(pattern, text_lower):
                concepts.append(concept)
        
        return concepts[:5]  # Limit to top 5 concepts
    
    def _create_comprehensive_mock_dataset(self, count: int) -> List[Dict[str, Any]]:
        """Create comprehensive mock caselaw dataset with realistic embeddings and metadata"""
        
        mock_data = []
        base_cases = self._legal_case_templates.copy()
        
        # Create variations to reach the requested count
        case_variations = [
            # Additional landmark cases
            {
                "title_suffix": "",
                "court_variations": ["Supreme Court of the United States", "U.S. Supreme Court"],
                "topic_modifiers": {},
                "year_range": (1803, 2023)
            },
            {
                "title_suffix": " (Rehearing)",
                "court_variations": ["Supreme Court of the United States", "Court of Appeals"],
                "topic_modifiers": {"procedural": True},
                "year_range": (1850, 2020)
            },
            {
                "title_suffix": " v. State",
                "court_variations": ["State Supreme Court", "State Appellate Court"],
                "topic_modifiers": {"state_law": True},
                "year_range": (1900, 2023)
            }
        ]
        
        # Generate additional federal circuit and state cases
        additional_case_templates = [
            {
                "base_title": "United States v.",
                "topics": ["criminal procedure", "federal jurisdiction", "constitutional law"],
                "courts": ["U.S. Court of Appeals", "U.S. District Court"],
                "concepts_pool": [
                    ["federal jurisdiction", "criminal law", "constitutional rights"],
                    ["interstate commerce", "federal regulation", "due process"],
                    ["search and seizure", "fourth amendment", "criminal procedure"]
                ]
            },
            {
                "base_title": "State of {} v.",
                "topics": ["criminal law", "state jurisdiction", "civil procedure"],
                "courts": ["State Supreme Court", "State Appellate Court"],
                "concepts_pool": [
                    ["state criminal law", "evidence", "trial procedure"],
                    ["state constitutional law", "local jurisdiction", "appeals"],
                    ["civil procedure", "state courts", "jurisdiction"]
                ]
            },
            {
                "base_title": "{} County v.",
                "topics": ["local government", "zoning", "municipal law"],
                "courts": ["County Court", "Municipal Court"],
                "concepts_pool": [
                    ["local government", "zoning law", "municipal authority"],
                    ["property rights", "local regulation", "administrative law"],
                    ["municipal powers", "county jurisdiction", "local ordinance"]
                ]
            }
        ]
        
        # Generate the dataset
        for i in range(count):
            if i < len(base_cases):
                # Use template cases first
                case = base_cases[i % len(base_cases)].copy()
                
                # Add variations for duplicates
                if i >= len(base_cases):
                    variation_idx = (i - len(base_cases)) % len(case_variations)
                    variation = case_variations[variation_idx]
                    
                    # Apply variation
                    if variation["title_suffix"]:
                        case["title"] += variation["title_suffix"]
                    case["court"] = random.choice(variation["court_variations"])
                    case["year"] = random.randint(*variation["year_range"])
                    case["id"] = f"case-{i}-{case['year']}"
            else:
                # Generate synthetic cases
                template = random.choice(additional_case_templates)
                case = self._generate_synthetic_case(i, template)
            
            # Generate realistic embedding
            case["embedding"] = self._generate_realistic_embedding(case, seed=i)
            
            # Add IPLD-compatible metadata
            case["ipld_metadata"] = self._generate_ipld_metadata(case, i)
            
            mock_data.append(case)
        
        logger.info(f"Created comprehensive dataset with {len(mock_data)} legal cases")
        return mock_data
    
    def _generate_synthetic_case(self, index: int, template: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a synthetic legal case based on template"""
        states = ["California", "New York", "Texas", "Florida", "Illinois", "Pennsylvania"]
        counties = ["Jefferson", "Washington", "Madison", "Lincoln", "Franklin", "Jackson"]
        
        # Generate case title
        if "{}" in template["base_title"]:
            if "State of" in template["base_title"]:
                title = template["base_title"].format(random.choice(states))
            elif "County" in template["base_title"]:
                title = template["base_title"].format(random.choice(counties))
            else:
                title = template["base_title"] + f"Defendant {index}"
        else:
            title = template["base_title"] + f"Case {index}"
        
        # Generate other fields
        year = random.randint(1950, 2023)
        court = random.choice(template["courts"])
        topic = random.choice(template["topics"])
        legal_concepts = random.choice(template["concepts_pool"])
        
        # Generate citation
        if "U.S." in court:
            citation = f"{200 + index} F.3d {100 + (index * 13) % 900}"
        else:
            citation = f"{100 + index} State {50 + (index * 7) % 300}"
        
        # Generate case text
        text_templates = [
            f"The court held that the defendant's actions constituted a violation of established {topic} principles. The evidence presented demonstrated clear intent and established liability under relevant statutes.",
            f"In this {topic} case, the court applied established precedent to determine that the plaintiff's claims were supported by sufficient evidence and legal authority.",
            f"The appellate court reversed the lower court's decision, finding that proper {topic} procedures were not followed and that constitutional rights were violated."
        ]
        
        text = random.choice(text_templates)
        summary = f"Court decision regarding {topic} establishing precedent for future cases"
        
        return {
            "id": f"synthetic-case-{index}",
            "title": title,
            "court": court,
            "year": year,
            "citation": citation,
            "topic": topic,
            "jurisdiction": "state" if "State" in court else "federal",
            "text": text,
            "summary": summary,
            "legal_concepts": legal_concepts,
            "precedent_value": random.choice(["high", "medium", "low"]),
            "case_type": topic.replace(" ", "_"),
            "outcome": random.choice(["granted", "denied", "reversed", "affirmed"]),
            "cited_by_count": random.randint(5, 1000)
        }
    
    def _generate_ipld_metadata(self, case: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Generate IPLD-compatible metadata for knowledge graph integration"""
        return {
            "cid": f"baf{'k' * 56}{'0' * 8}{index:08d}",  # Mock CID
            "dag_links": [
                {
                    "name": "text_content",
                    "cid": f"baf{'t' * 56}{'0' * 8}{index:08d}",
                    "size": len(case.get("text", ""))
                },
                {
                    "name": "embeddings",
                    "cid": f"baf{'e' * 56}{'0' * 8}{index:08d}",
                    "size": len(case.get("embedding", [])) * 4  # 4 bytes per float
                }
            ],
            "content_type": "legal/case",
            "schema_version": "1.0",
            "created_at": f"{case.get('year', 2000)}-01-01T00:00:00Z",
            "legal_identifiers": {
                "citation": case.get("citation", ""),
                "court_id": self._normalize_court_id(case.get("court", "")),
                "jurisdiction": case.get("jurisdiction", "unknown")
            },
            "semantic_tags": case.get("legal_concepts", []),
            "provenance": {
                "source": "Caselaw Access Project",
                "processing_pipeline": "ipfs_datasets_py.caselaw_graphrag",
                "embedding_model": "mock_legal_embeddings_v1"
            }
        }
    
    def _normalize_court_id(self, court_name: str) -> str:
        """Normalize court name to standard identifier"""
        court_mappings = {
            "Supreme Court of the United States": "scotus",
            "U.S. Supreme Court": "scotus",
            "Supreme Court": "scotus",
            "U.S. Court of Appeals": "circuit_court",
            "Court of Appeals": "circuit_court",
            "U.S. District Court": "district_court",
            "District Court": "district_court",
            "State Supreme Court": "state_supreme",
            "State Appellate Court": "state_appellate",
            "County Court": "county_court",
            "Municipal Court": "municipal_court"
        }
        
        return court_mappings.get(court_name, "unknown_court")
    
    def get_dataset_statistics(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate comprehensive statistics about the dataset"""
        if not dataset:
            return {}
        
        # Court distribution
        court_dist = {}
        topic_dist = {}
        year_dist = {}
        concept_dist = {}
        jurisdiction_dist = {}
        
        for case in dataset:
            # Court distribution
            court = case.get("court", "Unknown")
            court_dist[court] = court_dist.get(court, 0) + 1
            
            # Topic distribution
            topic = case.get("topic", "unknown")
            topic_dist[topic] = topic_dist.get(topic, 0) + 1
            
            # Year distribution
            year = case.get("year", 0)
            decade = (year // 10) * 10
            year_dist[f"{decade}s"] = year_dist.get(f"{decade}s", 0) + 1
            
            # Legal concepts
            concepts = case.get("legal_concepts", [])
            for concept in concepts:
                concept_dist[concept] = concept_dist.get(concept, 0) + 1
            
            # Jurisdiction
            jurisdiction = case.get("jurisdiction", "unknown")
            jurisdiction_dist[jurisdiction] = jurisdiction_dist.get(jurisdiction, 0) + 1
        
        # Calculate embedding statistics if embeddings are available
        embedding_stats = {}
        if dataset[0].get("embedding"):
            embeddings = [case["embedding"] for case in dataset if case.get("embedding")]
            if embeddings and NUMPY_AVAILABLE:
                embedding_array = np.array(embeddings)
                embedding_stats = {
                    "dimension": embedding_array.shape[1],
                    "mean_norm": np.mean(np.linalg.norm(embedding_array, axis=1)),
                    "std_norm": np.std(np.linalg.norm(embedding_array, axis=1)),
                    "min_value": np.min(embedding_array),
                    "max_value": np.max(embedding_array)
                }
            else:
                embedding_stats = {
                    "dimension": len(embeddings[0]) if embeddings else 0,
                    "total_embeddings": len(embeddings)
                }
        
        return {
            "total_cases": len(dataset),
            "court_distribution": dict(sorted(court_dist.items(), key=lambda x: x[1], reverse=True)),
            "topic_distribution": dict(sorted(topic_dist.items(), key=lambda x: x[1], reverse=True)),
            "year_distribution": dict(sorted(year_dist.items())),
            "legal_concepts": dict(sorted(concept_dist.items(), key=lambda x: x[1], reverse=True)[:20]),
            "jurisdiction_distribution": jurisdiction_dist,
            "embedding_statistics": embedding_stats,
            "year_range": {
                "min_year": min(case.get("year", 0) for case in dataset),
                "max_year": max(case.get("year", 0) for case in dataset),
                "span": max(case.get("year", 0) for case in dataset) - min(case.get("year", 0) for case in dataset)
            }
        }
    
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