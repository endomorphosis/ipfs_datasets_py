"""
DEI Provision Extractor

Extracts specific DEI provisions from legal documents with context.
Based on HACC's deep_analysis.py for identifying exact statutory/regulatory
requirements related to diversity, equity, and inclusion.

This module helps identify:
- Specific statute/regulation sections containing DEI language
- Context around DEI requirements
- Binding vs. aspirational language
- Enforcement mechanisms
"""

import re
from typing import List, Dict, Optional, Any
from datetime import datetime


class DEIProvisionExtractor:
    """
    Extract specific DEI provisions from legal and policy documents.
    
    This extractor identifies DEI-related provisions with surrounding context,
    helping to understand the specific requirements and their applicability.
    
    Based on HACC's deep_analysis.py methodology for provision extraction.
    
    Example:
        >>> extractor = DEIProvisionExtractor()
        >>> provisions = extractor.extract_provisions(statute_text)
        >>> for prov in provisions:
        ...     print(f"{prov['section']}: {prov['summary']}")
    """
    
    # DEI term patterns from HACC's deep_analysis.py
    DEI_PATTERNS = [
        r"\b(diversity|diverse)\b",
        r"\b(equity|equitable)\b",
        r"\b(inclusion|inclusive)\b",
        r"\b(underrepresented minorit(y|ies))\b",
        r"\b(underserved communit(y|ies))\b",
        r"\b(disadvantaged business enterprise|DBE)\b",
        r"\b(minority[- ]owned business|MBE)\b",
        r"\b(wom[ae]n[- ]owned business|WBE)\b",
        r"\b(MWESB|ESB)\b",
        r"\b(affirmative action)\b",
        r"\b(protected class(es)?)\b",
        r"\b(disparate (impact|treatment))\b",
        r"\b(cultural competen(cy|ce))\b",
        r"\b(implicit bias|unconscious bias)\b",
        r"\b(racial equity)\b",
        r"\b(social equity)\b",
        r"\b(environmental justice)\b",
        r"\b(historically underrepresented)\b",
        r"\b(marginalized communit(y|ies))\b",
        r"\b(BIPOC)\b",
        r"\b(equal opportunity)\b",
        r"\b(fair housing)\b",
        r"\b(Section 3)\b",
        r"\b(community benefit(s)?)\b",
        r"\b(socially disadvantaged)\b",
        r"\b(economically disadvantaged)\b",
        r"\b(people of color)\b",
        r"\b(equity (lens|framework|initiative))\b",
        r"\b(lived experience)\b",
        r"\b(cultural (humility|responsiveness))\b",
    ]
    
    # Binding/enforcement language indicators
    BINDING_PATTERNS = [
        r"\b(shall|must|required|mandatory)\b",
        r"\b(is required to|are required to)\b",
        r"\b(obligation|obligated|obligate)\b",
        r"\b(enforce|enforcement|enforceable)\b",
        r"\b(comply|compliance)\b",
        r"\b(violation|violate)\b",
        r"\b(penalty|penalties|penalize)\b",
    ]
    
    def __init__(self):
        """Initialize the provision extractor with compiled patterns."""
        self.dei_patterns = [re.compile(p, re.IGNORECASE) for p in self.DEI_PATTERNS]
        self.binding_patterns = [re.compile(p, re.IGNORECASE) for p in self.BINDING_PATTERNS]
    
    def extract_provisions(self, text: str, 
                          document_type: str = 'policy',
                          context_chars: int = 500) -> List[Dict[str, Any]]:
        """
        Extract DEI provisions from text with context.
        
        Args:
            text: Document text to analyze
            document_type: Type of document ('statute', 'regulation', 'policy', 'contract')
            context_chars: Number of characters to include as context
            
        Returns:
            List of provision dictionaries containing:
            - section: Section identifier (if available)
            - text: Provision text
            - context: Surrounding context
            - dei_terms: DEI terms found
            - binding_terms: Binding language found
            - is_binding: Whether provision appears binding
            - position: Character position in document
        """
        provisions = []
        
        # Split text into paragraphs or sections
        sections = self._split_into_sections(text, document_type)
        
        for section_info in sections:
            section_text = section_info['text']
            
            # Check if section contains DEI terms
            dei_matches = self._find_matches(section_text, self.dei_patterns)
            if not dei_matches:
                continue
            
            # Check for binding language
            binding_matches = self._find_matches(section_text, self.binding_patterns)
            is_binding = len(binding_matches) > 0
            
            # Extract context
            start_pos = section_info['position']
            context_start = max(0, start_pos - context_chars)
            context_end = min(len(text), start_pos + len(section_text) + context_chars)
            context = text[context_start:context_end]
            
            provision = {
                'section': section_info['identifier'],
                'text': section_text[:1000],  # Limit length
                'context': context,
                'dei_terms': list(set(dei_matches)),
                'binding_terms': list(set(binding_matches)),
                'is_binding': is_binding,
                'position': start_pos,
                'char_count': len(section_text),
                'extracted_at': datetime.now().isoformat()
            }
            
            provisions.append(provision)
        
        return provisions
    
    def _split_into_sections(self, text: str, document_type: str) -> List[Dict[str, Any]]:
        """
        Split document into logical sections.
        
        Different document types have different section markers:
        - Statutes: § xxx.xxx or Section xxx
        - Regulations: Part xxx, § xxx.xxx
        - Policies: Numbered paragraphs, headings
        - Contracts: Articles, sections
        """
        sections = []
        
        if document_type in ['statute', 'regulation']:
            # Look for section markers like "§ 123.456" or "Section 123"
            section_pattern = r'(§\s*\d+\.?\d*|Section\s+\d+\.?\d*|Part\s+\d+)'
            matches = list(re.finditer(section_pattern, text, re.IGNORECASE))
            
            if matches:
                for i, match in enumerate(matches):
                    start = match.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    
                    sections.append({
                        'identifier': match.group(0),
                        'text': text[start:end].strip(),
                        'position': start
                    })
            else:
                # No section markers found, treat as single section
                sections.append({
                    'identifier': 'Document',
                    'text': text,
                    'position': 0
                })
        else:
            # For policies and contracts, split by paragraphs
            paragraphs = text.split('\n\n')
            position = 0
            
            for i, para in enumerate(paragraphs):
                if para.strip():
                    sections.append({
                        'identifier': f'Paragraph {i+1}',
                        'text': para.strip(),
                        'position': position
                    })
                position += len(para) + 2  # +2 for \n\n
        
        return sections
    
    def _find_matches(self, text: str, patterns: List[re.Pattern]) -> List[str]:
        """Find all pattern matches in text."""
        matches = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                matches.append(match.group(0).lower())
        return matches
    
    def extract_statute_provisions(self, text: str, chapter: str) -> List[Dict[str, Any]]:
        """
        Extract provisions from statute text (specialized for ORS format).
        
        Args:
            text: Statute text
            chapter: Chapter number (e.g., "456", "279A")
            
        Returns:
            List of provisions specific to the chapter
        """
        provisions = []
        
        # Pattern for statute numbers like "456.055" or "279A.110"
        statute_pattern = rf'{re.escape(chapter)}\.?\d{{3}}'
        
        lines = text.split('\n')
        current_statute = None
        current_text = []
        
        for line in lines:
            # Check if line starts a new statute section
            if re.search(statute_pattern, line):
                # Save previous statute if it had DEI terms
                if current_statute and current_text:
                    full_text = '\n'.join(current_text)
                    
                    # Check for DEI terms
                    dei_matches = self._find_matches(full_text, self.dei_patterns)
                    if dei_matches:
                        binding_matches = self._find_matches(full_text, self.binding_patterns)
                        
                        provisions.append({
                            'statute': current_statute,
                            'chapter': chapter,
                            'text': full_text[:2000],
                            'dei_terms': list(set(dei_matches)),
                            'binding_terms': list(set(binding_matches)),
                            'is_binding': len(binding_matches) > 0,
                            'extracted_at': datetime.now().isoformat()
                        })
                
                # Start new statute
                current_statute = line.strip()[:30]
                current_text = [line]
            else:
                # Continue collecting lines for current statute
                if current_statute and len(current_text) < 200:
                    current_text.append(line)
        
        # Check last statute
        if current_statute and current_text:
            full_text = '\n'.join(current_text)
            dei_matches = self._find_matches(full_text, self.dei_patterns)
            if dei_matches:
                binding_matches = self._find_matches(full_text, self.binding_patterns)
                provisions.append({
                    'statute': current_statute,
                    'chapter': chapter,
                    'text': full_text[:2000],
                    'dei_terms': list(set(dei_matches)),
                    'binding_terms': list(set(binding_matches)),
                    'is_binding': len(binding_matches) > 0,
                    'extracted_at': datetime.now().isoformat()
                })
        
        return provisions
    
    def summarize_provisions(self, provisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Summarize extracted provisions.
        
        Args:
            provisions: List of extracted provisions
            
        Returns:
            Summary statistics and categorization
        """
        if not provisions:
            return {
                'total': 0,
                'binding': 0,
                'non_binding': 0,
                'most_common_terms': [],
                'sections_affected': []
            }
        
        # Count binding vs non-binding
        binding_count = sum(1 for p in provisions if p.get('is_binding', False))
        
        # Aggregate all DEI terms
        all_terms = []
        for prov in provisions:
            all_terms.extend(prov.get('dei_terms', []))
        
        # Count term frequency
        term_counts = {}
        for term in all_terms:
            term_counts[term] = term_counts.get(term, 0) + 1
        
        # Sort by frequency
        most_common = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'total': len(provisions),
            'binding': binding_count,
            'non_binding': len(provisions) - binding_count,
            'most_common_terms': most_common[:10],
            'sections_affected': [p.get('section', p.get('statute', 'Unknown')) 
                                 for p in provisions]
        }
