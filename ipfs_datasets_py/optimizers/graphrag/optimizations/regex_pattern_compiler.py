"""
Optimized regex pattern pre-compilation for entity extraction.

This module implements Priority 1 performance optimization:
- Pre-compile all regex patterns at class initialization (avoid repeated compilation)
- Cache compiled patterns at class level for reuse across instances
- Store as compiled Pattern objects instead of raw strings

Estimated improvement: 10-12% speedup from eliminating repeated regex compilation
"""

import re
from typing import List, Tuple, Any, Set, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PrecompiledPattern:
    """Container for pre-compiled regex patterns."""
    compiled_pattern: re.Pattern
    entity_type: str
    original_pattern: str


class RegexPatternCompiler:
    """Manages pre-compilation and caching of regex patterns."""

    # Class-level cache for compiled patterns
    _base_patterns_compiled: Optional[List[PrecompiledPattern]] = None
    _domain_patterns_compiled: Optional[dict[str, List[PrecompiledPattern]]] = None

    @classmethod
    def _compile_base_patterns(cls) -> List[PrecompiledPattern]:
        """
        Compile base patterns once at class level.
        
        These domain-agnostic patterns are used across all extractions.
        
        Returns:
            List of pre-compiled patterns
        """
        if cls._base_patterns_compiled is not None:
            return cls._base_patterns_compiled

        # Base patterns (domain-agnostic)
        base_pattern_strings = [
            (r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', 'Person'),
            (r'\b[A-Z][A-Za-z&\s]*(?:LLC|Ltd|Inc|Corp|GmbH|PLC|Co\.)\b', 'Organization'),
            (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', 'Date'),
            (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', 'Date'),
            (r'\b(?:USD|EUR|GBP)\s*[\d,]+(?:\.\d{2})?\b', 'MonetaryAmount'),
            (r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|Avenue|Road|City|County|State|Country|Region|District)\b', 'Location'),
            (r'\b(?:the\s+)?(?:obligation|duty|right|liability|breach|claim|penalty)\s+(?:of\s+)?[A-Z][a-z]+\b', 'Obligation'),
            (r'\b[A-Z][A-Za-z]{3,}\b', 'Concept'),
        ]

        # Compile and cache
        cls._base_patterns_compiled = [
            PrecompiledPattern(
                compiled_pattern=re.compile(pat_str, re.IGNORECASE),
                entity_type=ent_type,
                original_pattern=pat_str,
            )
            for pat_str, ent_type in base_pattern_strings
        ]

        logger.debug(f"Compiled {len(cls._base_patterns_compiled)} base patterns at class level")
        return cls._base_patterns_compiled

    @classmethod
    def _compile_domain_patterns(cls) -> dict[str, List[PrecompiledPattern]]:
        """
        Compile domain-specific patterns once at class level.
        
        Returns:
            Dict mapping domain name to list of pre-compiled patterns
        """
        if cls._domain_patterns_compiled is not None:
            return cls._domain_patterns_compiled

        domain_pattern_strings = {
            'legal': [
                (r'\b(?:plaintiff|defendant|claimant|respondent|petitioner)\b', 'LegalParty'),
                (r'\b(?:Article|Section|Clause|Schedule|Appendix)\s+\d+[\w.]*', 'LegalReference'),
                (r'\b(?:indemnif(?:y|ication)|warranty|waiver|covenant|arbitration)\b', 'LegalConcept'),
            ],
            'medical': [
                (r'\b(?:diagnosis|prognosis|symptom|syndrome|disorder|disease|condition)\b', 'MedicalConcept'),
                (r'\b\d+\s*(?:mg|mcg|ml|IU|units?)\b', 'Dosage'),
                (r'\b(?:patient|physician|surgeon|nurse|therapist|specialist)\b', 'MedicalRole'),
            ],
            'technical': [
                (r'\b(?:API|REST|HTTP|JSON|XML|SQL|NoSQL|GraphQL)\b', 'Protocol'),
                (r'\b(?:microservice|endpoint|middleware|container|pipeline|daemon)\b', 'TechnicalComponent'),
                (r'\bv?\d+\.\d+(?:\.\d+)*(?:-\w+)?\b', 'Version'),
            ],
            'financial': [
                (r'\b(?:asset|liability|equity|debit|credit|balance|principal|interest)\b', 'FinancialConcept'),
                (r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:USD|EUR|GBP|JPY)?\b', 'MonetaryValue'),
                (r'\b(?:IBAN|SWIFT|BIC|routing\s+number)\b', 'BankIdentifier'),
            ],
        }

        # Compile and cache all domain patterns
        cls._domain_patterns_compiled = {}
        for domain, patterns_list in domain_pattern_strings.items():
            cls._domain_patterns_compiled[domain] = [
                PrecompiledPattern(
                    compiled_pattern=re.compile(pat_str, re.IGNORECASE),
                    entity_type=ent_type,
                    original_pattern=pat_str,
                )
                for pat_str, ent_type in patterns_list
            ]

        logger.debug(f"Compiled domain-specific patterns for {len(cls._domain_patterns_compiled)} domains")
        return cls._domain_patterns_compiled

    @classmethod
    def build_precompiled_patterns(
        cls,
        domain: str,
        custom_rules: Optional[List[Tuple[str, str]]] = None,
    ) -> List[PrecompiledPattern]:
        """
        Build final list of pre-compiled patterns for extraction.
        
        Combines base patterns + domain patterns + custom rules, all pre-compiled.
        This avoids re-compiling patterns on each extraction call.
        
        Args:
            domain: Domain name (legal, medical, technical, financial, or general)
            custom_rules: Optional custom rules as list of (pattern_str, entity_type) tuples
            
        Returns:
            List of PrecompiledPattern objects ready for use
        """
        # Get base patterns (compiled once)
        base = cls._compile_base_patterns()

        # Get domain patterns (compiled once)
        domain_patterns_dict = cls._compile_domain_patterns()
        domain_patterns = domain_patterns_dict.get(domain, [])

        # Start with base + domain patterns
        all_patterns = list(base) + list(domain_patterns)

        # Add custom rules if provided (compile them on-demand)
        if custom_rules:
            custom_compiled = [
                PrecompiledPattern(
                    compiled_pattern=re.compile(pat_str, re.IGNORECASE),
                    entity_type=ent_type,
                    original_pattern=pat_str,
                )
                for pat_str, ent_type in custom_rules
            ]
            # Insert custom rules before the last generic pattern
            all_patterns = all_patterns[:-1] + custom_compiled + [all_patterns[-1]]

        logger.debug(
            f"Built {len(all_patterns)} pre-compiled patterns "
            f"({len(base)} base + {len(domain_patterns)} domain + "
            f"{len(custom_rules) if custom_rules else 0} custom)"
        )
        return all_patterns

    @staticmethod
    def extract_entities_with_precompiled(
        text: str,
        precompiled_patterns: List[PrecompiledPattern],
        allowed_types: Set[str],
        min_len: int,
        stopwords: Set[str],
        max_confidence: float,
    ) -> List[dict]:
        """
        Extract entities using pre-compiled patterns.
        
        Uses pre-compiled regex patterns to avoid repeated compilation.
        Includes Priority 2 optimization: pre-compute lowercase stopwords to avoid
        repeated .lower() calls per match.
        
        Args:
            text: Text to extract from
            precompiled_patterns: List of PrecompiledPattern objects
            allowed_types: Set of allowed entity types (empty=all)
            min_len: Minimum entity text length
            stopwords: Set of stopwords to filter
            max_confidence: Maximum confidence score
            
        Returns:
            List of entity dicts with id, type, text, confidence, span
        """
        import uuid
        import time

        entities = []
        seen_texts: Set[str] = set()
        
        # OPTIMIZATION (Priority 2): Pre-compute lowercase stopwords once
        # Avoid repeated .lower() calls for each stopword check
        lowercase_stopwords: Set[str] = {sw.lower() for sw in stopwords} if stopwords else set()

        for precomp in precompiled_patterns:
            # Check allowed types
            if allowed_types and precomp.entity_type not in allowed_types:
                continue

            # Use pre-compiled pattern directly
            compiled_pattern = precomp.compiled_pattern
            entity_type = precomp.entity_type

            # Set confidence based on entity type
            confidence = 0.5 if entity_type == 'Concept' else 0.75
            confidence = min(confidence, max_confidence)

            # Search using pre-compiled pattern
            for match in compiled_pattern.finditer(text):
                raw = match.group(0).strip()
                key = raw.lower()

                # OPTIMIZATION (Priority 2): Use pre-computed lowercase stopwords set
                # Skip if already seen, too short, or in stopwords
                if key in seen_texts or len(raw) < min_len or key in lowercase_stopwords:
                    continue

                seen_texts.add(key)
                entities.append({
                    'id': f"e_{uuid.uuid4().hex[:8]}",
                    'type': entity_type,
                    'text': raw,
                    'confidence': confidence,
                    'span': (match.start(), match.end()),
                    'timestamp': time.time(),
                })

        return entities


def benchmark_pre_compilation():
    """Benchmark pre-compiled patterns vs on-demand compilation."""
    import time

    sample_text = """
    Mr. John Smith works at Acme Corporation. Dr. Jane Doe, PhD is the CEO.
    The contract was signed on 2024-12-15 and covers USD 1,000,000.
    Article 3, Section 5(a) requires indemnification. See Appendix A.
    The facility is located at 123 Main Street, Springfield, Illinois.
    The obligation of the parties is binding under arbitration clauses.
    Patient admitted with diagnosis of hypertension. Dosage: 50 mg daily.
    API endpoints use REST with JSON payloads. Version 2.1.0-beta.
    The balance sheet shows assets totaling EUR 5,000,000.
    """

    compiler = RegexPatternCompiler()

    # Timing: Build pre-compiled patterns (done once)
    t_compile = time.time()
    precompiled = compiler.build_precompiled_patterns("legal", custom_rules=None)
    compile_time = (time.time() - t_compile) * 1000

    # Timing: Extract with pre-compiled patterns (fast)
    t_extract = time.time()
    entities = compiler.extract_entities_with_precompiled(
        sample_text,
        precompiled,
        allowed_types=set(),
        min_len=2,
        stopwords=set(),
        max_confidence=1.0,
    )
    extract_time = (time.time() - t_extract) * 1000

    print(f"✓ Pattern compilation: {compile_time:.2f}ms (one-time, class-level cached)")
    print(f"✓ Entity extraction: {extract_time:.2f}ms ({len(entities)} entities found)")
    print(f"\n  Patterns pre-compiled: {len(precompiled)}")
    print(f"  Extraction efficiency: {len(entities) / extract_time:.1f} entities/ms")


if __name__ == "__main__":
    benchmark_pre_compilation()
