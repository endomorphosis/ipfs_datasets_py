"""
Chunk Optimization Utilities

Provides advanced chunking strategies optimized for LLM consumption.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ChunkMetrics:
    """Metrics for evaluating chunk quality."""
    coherence_score: float
    completeness_score: float
    length_score: float
    semantic_density: float
    overall_quality: float

class ChunkOptimizer:
    """Advanced chunk optimization for LLM consumption."""
    
    def __init__(self, 
                 max_size: int = 2048,
                 overlap: int = 200,
                 min_size: int = 100):
        self.max_size = max_size
        self.overlap = overlap
        self.min_size = min_size
    
    def optimize_chunks(self, 
                       text: str, 
                       preserve_structure: bool = True) -> List[Dict[str, Any]]:
        """Create optimized chunks with quality scoring."""
        if not text:
            return []
        
        # Create initial chunks
        if preserve_structure:
            chunks = self._create_structure_aware_chunks(text)
        else:
            chunks = self._create_sliding_window_chunks(text)
        
        # Optimize chunk boundaries
        optimized_chunks = self._optimize_boundaries(chunks, text)
        
        # Score and rank chunks
        scored_chunks = []
        for chunk in optimized_chunks:
            metrics = self._calculate_chunk_metrics(chunk)
            chunk['metrics'] = metrics
            chunk['quality_score'] = metrics.overall_quality
            scored_chunks.append(chunk)
        
        return scored_chunks
    
    def _create_structure_aware_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Create chunks that respect document structure."""
        chunks = []
        
        # Split into paragraphs first
        paragraphs = re.split(r'\n\s*\n', text)
        
        current_chunk = ""
        current_paragraphs = []
        current_tokens = 0
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            paragraph_tokens = len(paragraph.split())
            
            # Check if adding this paragraph would exceed max size
            if current_tokens + paragraph_tokens > self.max_size and current_chunk:
                # Create chunk with current content
                chunk = self._create_chunk_dict(
                    current_chunk.strip(),
                    current_tokens,
                    current_paragraphs,
                    'structure_aware'
                )
                chunks.append(chunk)
                
                # Start new chunk with overlap
                overlap_content = self._get_overlap_content(current_chunk)
                current_chunk = overlap_content + "\n\n" + paragraph
                current_paragraphs = [paragraph]
                current_tokens = len(current_chunk.split())
            else:
                # Add paragraph to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
                current_paragraphs.append(paragraph)
                current_tokens += paragraph_tokens
        
        # Add final chunk if content remains
        if current_chunk.strip():
            chunk = self._create_chunk_dict(
                current_chunk.strip(),
                current_tokens,
                current_paragraphs,
                'structure_aware'
            )
            chunks.append(chunk)
        
        return chunks
    
    def _create_sliding_window_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Create chunks using sliding window approach."""
        words = text.split()
        chunks = []
        
        step_size = max(1, self.max_size - self.overlap)
        
        for i in range(0, len(words), step_size):
            chunk_words = words[i:i + self.max_size]
            
            if len(chunk_words) >= self.min_size:
                chunk_text = ' '.join(chunk_words)
                chunk = self._create_chunk_dict(
                    chunk_text,
                    len(chunk_words),
                    [chunk_text],  # Single paragraph
                    'sliding_window'
                )
                chunk['start_index'] = i
                chunk['end_index'] = i + len(chunk_words)
                chunks.append(chunk)
        
        return chunks
    
    def _create_chunk_dict(self, 
                          content: str, 
                          token_count: int,
                          paragraphs: List[str], 
                          chunk_type: str) -> Dict[str, Any]:
        """Create a standardized chunk dictionary."""
        return {
            'content': content,
            'token_count': token_count,
            'paragraph_count': len(paragraphs),
            'sentence_count': len(self._split_sentences(content)),
            'chunk_type': chunk_type,
            'word_count': len(content.split()),
            'char_count': len(content),
            'paragraphs': paragraphs
        }
    
    def _optimize_boundaries(self, 
                           chunks: List[Dict[str, Any]], 
                           full_text: str) -> List[Dict[str, Any]]:
        """Optimize chunk boundaries for better coherence."""
        if len(chunks) <= 1:
            return chunks
        
        optimized_chunks = []
        
        for i, chunk in enumerate(chunks):
            content = chunk['content']
            
            # For middle chunks, try to optimize start and end boundaries
            if 0 < i < len(chunks) - 1:
                # Optimize end boundary
                content = self._optimize_end_boundary(content)
                
                # Update chunk with optimized content
                chunk['content'] = content
                chunk['token_count'] = len(content.split())
                chunk['word_count'] = len(content.split())
                chunk['char_count'] = len(content)
            
            optimized_chunks.append(chunk)
        
        return optimized_chunks
    
    def _optimize_end_boundary(self, content: str) -> str:
        """Optimize the end boundary of a chunk."""
        # Try to end at sentence boundary
        sentences = self._split_sentences(content)
        
        if len(sentences) > 1:
            # Check if last sentence is incomplete or very short
            last_sentence = sentences[-1].strip()
            
            if len(last_sentence.split()) < 5 or not last_sentence.endswith(('.', '!', '?')):
                # Remove incomplete last sentence
                content = '. '.join(sentences[:-1]) + '.'
        
        return content
    
    def _get_overlap_content(self, content: str) -> str:
        """Get overlap content for chunk continuity."""
        words = content.split()
        overlap_words = min(self.overlap // 4, len(words))  # Conservative overlap
        
        if overlap_words > 0:
            overlap_text = ' '.join(words[-overlap_words:])
            # Try to end at sentence boundary
            sentences = self._split_sentences(overlap_text)
            if sentences:
                return sentences[-1] if len(sentences) == 1 else '. '.join(sentences[-2:])
            return overlap_text
        
        return ""
    
    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Improved sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _calculate_chunk_metrics(self, chunk: Dict[str, Any]) -> ChunkMetrics:
        """Calculate quality metrics for a chunk."""
        content = chunk['content']
        word_count = chunk['word_count']
        
        # Coherence score (based on sentence flow)
        coherence_score = self._calculate_coherence(content)
        
        # Completeness score (based on sentence endings)
        completeness_score = self._calculate_completeness(content)
        
        # Length score (optimal length range)
        length_score = self._calculate_length_score(word_count)
        
        # Semantic density (unique meaningful words)
        semantic_density = self._calculate_semantic_density(content)
        
        # Overall quality (weighted combination)
        overall_quality = (
            coherence_score * 0.3 +
            completeness_score * 0.25 +
            length_score * 0.25 +
            semantic_density * 0.2
        )
        
        return ChunkMetrics(
            coherence_score=coherence_score,
            completeness_score=completeness_score,
            length_score=length_score,
            semantic_density=semantic_density,
            overall_quality=overall_quality
        )
    
    def _calculate_coherence(self, content: str) -> float:
        """Calculate coherence score based on text flow."""
        sentences = self._split_sentences(content)
        
        if len(sentences) <= 1:
            return 0.8  # Single sentence is coherent
        
        # Check for transition words and phrases
        transition_words = {
            'however', 'therefore', 'furthermore', 'moreover', 'additionally',
            'consequently', 'nevertheless', 'meanwhile', 'subsequently',
            'in addition', 'for example', 'in contrast', 'on the other hand'
        }
        
        transition_count = 0
        for sentence in sentences[1:]:  # Skip first sentence
            sentence_lower = sentence.lower()
            if any(trans in sentence_lower for trans in transition_words):
                transition_count += 1
        
        # Score based on transition word usage
        transition_score = min(1.0, transition_count / max(1, len(sentences) - 1))
        
        # Check for pronoun references (indicates coherence)
        pronouns = {'he', 'she', 'it', 'they', 'this', 'that', 'these', 'those'}
        pronoun_count = sum(1 for word in content.lower().split() if word in pronouns)
        pronoun_score = min(1.0, pronoun_count / max(1, len(content.split()) / 20))
        
        # Combine scores
        coherence_score = (transition_score * 0.6) + (pronoun_score * 0.4)
        return min(1.0, coherence_score)
    
    def _calculate_completeness(self, content: str) -> float:
        """Calculate completeness score based on sentence endings."""
        if not content:
            return 0.0
        
        sentences = self._split_sentences(content)
        
        if not sentences:
            return 0.0
        
        # Check if chunk starts and ends appropriately
        first_sentence = sentences[0].strip()
        last_sentence = sentences[-1].strip()
        
        # Score for proper endings
        proper_endings = ('.', '!', '?', ':', ';')
        ends_properly = last_sentence.endswith(proper_endings)
        
        # Score for complete sentences
        complete_sentences = sum(1 for s in sentences if s.strip().endswith(proper_endings))
        sentence_completeness = complete_sentences / len(sentences) if sentences else 0
        
        # Score for paragraph structure
        has_multiple_sentences = len(sentences) > 1
        
        completeness_score = (
            (1.0 if ends_properly else 0.7) * 0.4 +
            sentence_completeness * 0.4 +
            (1.0 if has_multiple_sentences else 0.8) * 0.2
        )
        
        return min(1.0, completeness_score)
    
    def _calculate_length_score(self, word_count: int) -> float:
        """Calculate length score based on optimal range."""
        if word_count < self.min_size:
            return word_count / self.min_size
        elif word_count > self.max_size:
            return self.max_size / word_count
        else:
            # Optimal range - score based on how close to ideal length
            ideal_length = (self.min_size + self.max_size) / 2
            distance_from_ideal = abs(word_count - ideal_length)
            max_distance = (self.max_size - self.min_size) / 2
            
            return 1.0 - (distance_from_ideal / max_distance)
    
    def _calculate_semantic_density(self, content: str) -> float:
        """Calculate semantic density (meaningful content ratio)."""
        words = content.lower().split()
        
        if not words:
            return 0.0
        
        # Common stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be',
            'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did'
        }
        
        # Count meaningful words (not stop words, length > 2)
        meaningful_words = [
            word for word in words 
            if word not in stop_words and len(word) > 2
        ]
        
        # Calculate density
        density = len(meaningful_words) / len(words)
        
        # Bonus for unique words (vocabulary richness)
        unique_meaningful = len(set(meaningful_words))
        uniqueness_bonus = unique_meaningful / max(1, len(meaningful_words))
        
        # Combine density and uniqueness
        semantic_density = (density * 0.7) + (uniqueness_bonus * 0.3)
        
        return min(1.0, semantic_density)
    
    def merge_small_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge chunks that are too small."""
        if not chunks:
            return []
        
        merged_chunks = []
        i = 0
        
        while i < len(chunks):
            current_chunk = chunks[i]
            
            # If chunk is too small and not the last chunk
            if (current_chunk['word_count'] < self.min_size and 
                i < len(chunks) - 1):
                
                # Try to merge with next chunk
                next_chunk = chunks[i + 1]
                combined_size = current_chunk['word_count'] + next_chunk['word_count']
                
                if combined_size <= self.max_size:
                    # Merge chunks
                    merged_content = current_chunk['content'] + "\n\n" + next_chunk['content']
                    merged_chunk = self._create_chunk_dict(
                        merged_content,
                        combined_size,
                        current_chunk['paragraphs'] + next_chunk['paragraphs'],
                        'merged'
                    )
                    
                    # Calculate metrics for merged chunk
                    merged_chunk['metrics'] = self._calculate_chunk_metrics(merged_chunk)
                    merged_chunk['quality_score'] = merged_chunk['metrics'].overall_quality
                    
                    merged_chunks.append(merged_chunk)
                    i += 2  # Skip next chunk as it's been merged
                else:
                    # Can't merge, keep original
                    merged_chunks.append(current_chunk)
                    i += 1
            else:
                # Chunk is acceptable size or is last chunk
                merged_chunks.append(current_chunk)
                i += 1
        
        return merged_chunks
