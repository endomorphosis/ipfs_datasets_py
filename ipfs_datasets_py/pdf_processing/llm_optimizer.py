"""
LLM Optimization Module for PDF Processing Pipeline

Optimizes extracted content for LLM consumption by:
- Chunking text into optimal sizes
- Preserving semantic relationships
- Generating structured summaries
- Creating context-aware embeddings
- Handling multi-modal content
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import re


import tiktoken
from transformers import AutoTokenizer, AutoModel
import torch
import numpy as np
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.utils.text_processing import TextProcessor
from ipfs_datasets_py.utils.chunk_optimizer import ChunkOptimizer

logger = logging.getLogger(__name__)

@dataclass
class LLMChunk:
    """Represents an optimized chunk for LLM processing."""
    content: str
    chunk_id: str
    source_page: int
    source_element: str
    token_count: int
    semantic_type: str  # 'text', 'table', 'figure_caption', 'header', etc.
    relationships: List[str]  # Related chunk IDs
    metadata: Dict[str, Any]
    embedding: Optional[np.ndarray] = None

@dataclass
class LLMDocument:
    """Complete LLM-optimized document representation."""
    document_id: str
    title: str
    chunks: List[LLMChunk]
    summary: str
    key_entities: List[Dict[str, Any]]
    processing_metadata: Dict[str, Any]
    document_embedding: Optional[np.ndarray] = None

class LLMOptimizer:
    """
    Optimizes PDF content for LLM consumption and processing.
    """
    
    def __init__(self, 
                 model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 tokenizer_name: str = "gpt-3.5-turbo",
                 max_chunk_size: int = 2048,
                 chunk_overlap: int = 200,
                 min_chunk_size: int = 100):
        """
        Initialize the LLM optimizer.
        
        Args:
            model_name: Sentence transformer model for embeddings
            tokenizer_name: Tokenizer for token counting
            max_chunk_size: Maximum tokens per chunk
            chunk_overlap: Token overlap between chunks
            min_chunk_size: Minimum tokens per chunk
        """
        self.model_name = model_name
        self.tokenizer_name = tokenizer_name
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        
        # Initialize models
        self._initialize_models()
        
        # Text processing utilities
        self.text_processor = TextProcessor()
        self.chunk_optimizer = ChunkOptimizer(
            max_size=max_chunk_size,
            overlap=chunk_overlap,
            min_size=min_chunk_size
        )
        
    def _initialize_models(self):
        """Initialize embedding and tokenization models."""
        try:
            # Initialize sentence transformer for embeddings
            self.embedding_model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded embedding model: {self.model_name}")
            
            # Initialize tokenizer for token counting
            if "gpt" in self.tokenizer_name.lower():
                self.tokenizer = tiktoken.encoding_for_model(self.tokenizer_name)
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_name)
            
            logger.info(f"Loaded tokenizer: {self.tokenizer_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize models: {e}")
            # Fallback to basic tokenization
            self.embedding_model = None
            self.tokenizer = None
    
    async def optimize_for_llm(self, 
                              decomposed_content: Dict[str, Any],
                              document_metadata: Dict[str, Any]) -> LLMDocument:
        """
        Optimize decomposed PDF content for LLM consumption.
        
        Args:
            decomposed_content: Content from PDF decomposition stage
            document_metadata: Document metadata and properties
            
        Returns:
            LLMDocument with optimized chunks and embeddings
        """
        logger.info("Starting LLM optimization process")
        
        # Extract text content with structure preservation
        structured_text = await self._extract_structured_text(decomposed_content)
        
        # Generate document summary
        document_summary = await self._generate_document_summary(structured_text)
        
        # Create optimal chunks
        chunks = await self._create_optimal_chunks(structured_text, decomposed_content)
        
        # Generate embeddings
        chunks_with_embeddings = await self._generate_embeddings(chunks)
        
        # Extract key entities
        key_entities = await self._extract_key_entities(structured_text)
        
        # Create document-level embedding
        document_embedding = await self._generate_document_embedding(document_summary, structured_text)
        
        # Build LLM document
        llm_document = LLMDocument(
            document_id=document_metadata.get('document_id', ''),
            title=document_metadata.get('title', ''),
            chunks=chunks_with_embeddings,
            summary=document_summary,
            key_entities=key_entities,
            document_embedding=document_embedding,
            processing_metadata={
                'optimization_timestamp': asyncio.get_event_loop().time(),
                'chunk_count': len(chunks_with_embeddings),
                'total_tokens': sum(chunk.token_count for chunk in chunks_with_embeddings),
                'model_used': self.model_name,
                'tokenizer_used': self.tokenizer_name
            }
        )
        
        logger.info(f"LLM optimization complete: {len(chunks_with_embeddings)} chunks created")
        return llm_document
    
    async def _extract_structured_text(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Extract text content while preserving structure and context."""
        structured_text = {
            'pages': [],
            'metadata': decomposed_content.get('metadata', {}),
            'structure': decomposed_content.get('structure', {})
        }
        
        for page_num, page_content in enumerate(decomposed_content.get('pages', [])):
            page_text = {
                'page_number': page_num + 1,
                'elements': [],
                'full_text': ''
            }
            
            # Extract text elements with context
            for element in page_content.get('elements', []):
                if element.get('type') == 'text':
                    text_element = {
                        'content': element.get('content', ''),
                        'type': element.get('subtype', 'paragraph'),
                        'position': element.get('position', {}),
                        'style': element.get('style', {}),
                        'confidence': element.get('confidence', 1.0)
                    }
                    page_text['elements'].append(text_element)
                    page_text['full_text'] += text_element['content'] + '\n'
            
            structured_text['pages'].append(page_text)
        
        return structured_text
    
    async def _generate_document_summary(self, structured_text: Dict[str, Any]) -> str:
        """Generate a comprehensive document summary."""
        # Combine all text content
        full_text = ""
        for page in structured_text['pages']:
            full_text += page['full_text'] + "\n"
        
        # Basic extractive summarization (can be enhanced with LLM)
        sentences = self.text_processor.split_sentences(full_text)
        
        # Score sentences by position and keyword frequency
        scored_sentences = []
        keywords = self.text_processor.extract_keywords(full_text, top_k=20)
        
        for i, sentence in enumerate(sentences[:50]):  # First 50 sentences
            score = 0
            # Position weight (earlier sentences get higher scores)
            score += (50 - i) / 50 * 0.3
            
            # Keyword presence
            for keyword in keywords:
                if keyword.lower() in sentence.lower():
                    score += 0.1
            
            # Length penalty for very short/long sentences
            words = len(sentence.split())
            if 10 <= words <= 30:
                score += 0.2
            
            scored_sentences.append((sentence, score))
        
        # Select top sentences for summary
        scored_sentences.sort(key=lambda x: x[1], reverse=True)
        summary_sentences = [sent[0] for sent in scored_sentences[:5]]
        
        return " ".join(summary_sentences)
    
    async def _create_optimal_chunks(self, 
                                   structured_text: Dict[str, Any],
                                   decomposed_content: Dict[str, Any]) -> List[LLMChunk]:
        """Create semantically optimal chunks for LLM processing."""
        chunks = []
        chunk_id_counter = 0
        
        for page in structured_text['pages']:
            page_num = page['page_number']
            
            # Process elements by semantic type
            current_chunk_content = ""
            current_chunk_metadata = {
                'source_elements': [],
                'semantic_types': set(),
                'page_number': page_num
            }
            
            for element in page['elements']:
                element_content = element['content'].strip()
                if not element_content:
                    continue
                
                # Calculate tokens for current content + new element
                potential_content = current_chunk_content + "\n" + element_content
                token_count = self._count_tokens(potential_content)
                
                # Check if adding this element would exceed chunk size
                if token_count > self.max_chunk_size and current_chunk_content:
                    # Create chunk with current content
                    chunk = await self._create_chunk(
                        current_chunk_content,
                        chunk_id_counter,
                        page_num,
                        current_chunk_metadata
                    )
                    chunks.append(chunk)
                    chunk_id_counter += 1
                    
                    # Start new chunk with overlap
                    overlap_content = self._get_chunk_overlap(current_chunk_content)
                    current_chunk_content = overlap_content + "\n" + element_content
                    current_chunk_metadata = {
                        'source_elements': [element['type']],
                        'semantic_types': {element['type']},
                        'page_number': page_num
                    }
                else:
                    # Add element to current chunk
                    if current_chunk_content:
                        current_chunk_content += "\n" + element_content
                    else:
                        current_chunk_content = element_content
                    
                    current_chunk_metadata['source_elements'].append(element['type'])
                    current_chunk_metadata['semantic_types'].add(element['type'])
            
            # Create final chunk for page if content remains
            if current_chunk_content.strip():
                chunk = await self._create_chunk(
                    current_chunk_content,
                    chunk_id_counter,
                    page_num,
                    current_chunk_metadata
                )
                chunks.append(chunk)
                chunk_id_counter += 1
        
        # Establish relationships between chunks
        chunks = self._establish_chunk_relationships(chunks)
        
        return chunks
    
    async def _create_chunk(self, 
                          content: str, 
                          chunk_id: int, 
                          page_num: int,
                          metadata: Dict[str, Any]) -> LLMChunk:
        """Create a single LLM chunk with metadata."""
        token_count = self._count_tokens(content)
        
        # Determine primary semantic type
        semantic_types = metadata.get('semantic_types', set())
        if len(semantic_types) == 1:
            primary_type = list(semantic_types)[0]
        elif 'header' in semantic_types:
            primary_type = 'header'
        elif 'table' in semantic_types:
            primary_type = 'table'
        else:
            primary_type = 'mixed'
        
        chunk = LLMChunk(
            content=content.strip(),
            chunk_id=f"chunk_{chunk_id:04d}",
            source_page=page_num,
            source_element=metadata.get('source_elements', []),
            token_count=token_count,
            semantic_type=primary_type,
            relationships=[],  # Will be populated later
            metadata={
                'semantic_types': list(semantic_types),
                'creation_timestamp': asyncio.get_event_loop().time(),
                'source_elements_count': len(metadata.get('source_elements', []))
            }
        )
        
        return chunk
    
    def _establish_chunk_relationships(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
        """Establish semantic relationships between chunks."""
        for i, chunk in enumerate(chunks):
            relationships = []
            
            # Adjacent chunks (sequential relationship)
            if i > 0:
                relationships.append(chunks[i-1].chunk_id)
            if i < len(chunks) - 1:
                relationships.append(chunks[i+1].chunk_id)
            
            # Same page chunks
            same_page_chunks = [
                c.chunk_id for c in chunks 
                if c.source_page == chunk.source_page and c.chunk_id != chunk.chunk_id
            ]
            relationships.extend(same_page_chunks[:3])  # Limit to 3 for performance
            
            chunk.relationships = list(set(relationships))
        
        return chunks
    
    async def _generate_embeddings(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
        """Generate embeddings for all chunks."""
        if not self.embedding_model:
            logger.warning("No embedding model available, skipping embedding generation")
            return chunks
        
        # Prepare texts for embedding
        texts = [chunk.content for chunk in chunks]
        
        # Generate embeddings in batches
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_chunks = chunks[i:i+batch_size]
            
            try:
                embeddings = self.embedding_model.encode(
                    batch_texts,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                
                for chunk, embedding in zip(batch_chunks, embeddings):
                    chunk.embedding = embedding
                    
            except Exception as e:
                logger.error(f"Failed to generate embeddings for batch {i//batch_size + 1}: {e}")
                # Continue without embeddings for this batch
        
        return chunks
    
    async def _extract_key_entities(self, structured_text: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract key entities and concepts from the document."""
        # Combine all text for entity extraction
        full_text = ""
        for page in structured_text['pages']:
            full_text += page['full_text'] + "\n"
        
        entities = []
        
        # Basic entity extraction (can be enhanced with NER models)
        # Extract dates
        date_pattern = r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b'
        dates = re.findall(date_pattern, full_text)
        for date in dates[:10]:  # Limit to first 10
            entities.append({
                'text': date,
                'type': 'date',
                'confidence': 0.8
            })
        
        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, full_text)
        for email in emails[:5]:  # Limit to first 5
            entities.append({
                'text': email,
                'type': 'email',
                'confidence': 0.9
            })
        
        # Extract potential organizations (capitalized multi-word phrases)
        org_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
        orgs = re.findall(org_pattern, full_text)
        for org in orgs[:10]:  # Limit to first 10
            if len(org.split()) >= 2:  # At least 2 words
                entities.append({
                    'text': org,
                    'type': 'organization',
                    'confidence': 0.6
                })
        
        return entities
    
    async def _generate_document_embedding(self, 
                                         summary: str, 
                                         structured_text: Dict[str, Any]) -> Optional[np.ndarray]:
        """Generate a document-level embedding."""
        if not self.embedding_model:
            return None
        
        # Combine summary with key parts of document
        doc_text = summary
        
        # Add key headers and first paragraphs
        for page in structured_text['pages'][:3]:  # First 3 pages
            for element in page['elements'][:5]:  # First 5 elements per page
                if element['type'] in ['header', 'title']:
                    doc_text += " " + element['content']
        
        try:
            embedding = self.embedding_model.encode(
                doc_text,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate document embedding: {e}")
            return None
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using the configured tokenizer."""
        if not text:
            return 0
        
        if self.tokenizer is None:
            # Fallback: approximate token count
            return len(text.split()) * 1.3  # Rough approximation
        
        try:
            if hasattr(self.tokenizer, 'encode'):
                # tiktoken or similar
                return len(self.tokenizer.encode(text))
            else:
                # HuggingFace tokenizer
                return len(self.tokenizer.tokenize(text))
        except Exception as e:
            logger.warning(f"Token counting failed: {e}")
            return len(text.split()) * 1.3
    
    def _get_chunk_overlap(self, content: str) -> str:
        """Get overlap content for chunk continuity."""
        if not content:
            return ""
        
        # Get last N tokens for overlap
        words = content.split()
        overlap_words = min(self.chunk_overlap // 4, len(words))  # Approximate word count
        
        if overlap_words > 0:
            return " ".join(words[-overlap_words:])
        return ""

# Utility classes for text processing
class TextProcessor:
    """Utility class for text processing operations."""
    
    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Basic sentence splitting (can be enhanced with NLTK or spaCy)
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def extract_keywords(self, text: str, top_k: int = 20) -> List[str]:
        """Extract keywords from text."""
        # Simple keyword extraction based on frequency
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Filter common stop words
        stop_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'this', 'that', 'these', 'those', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
        
        filtered_words = [w for w in words if w not in stop_words]
        
        # Count frequency
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # Return top keywords
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in sorted_words[:top_k]]

class ChunkOptimizer:
    """Utility class for optimizing text chunks."""
    
    def __init__(self, max_size: int, overlap: int, min_size: int):
        self.max_size = max_size
        self.overlap = overlap
        self.min_size = min_size
    
    def optimize_chunk_boundaries(self, text: str, current_boundaries: List[int]) -> List[int]:
        """Optimize chunk boundaries to respect sentence and paragraph breaks."""
        # Find sentence boundaries
        sentence_ends = []
        for match in re.finditer(r'[.!?]+\s+', text):
            sentence_ends.append(match.end())
        
        # Find paragraph boundaries  
        paragraph_ends = []
        for match in re.finditer(r'\n\s*\n', text):
            paragraph_ends.append(match.end())
        
        optimized_boundaries = []
        
        for boundary in current_boundaries:
            # Find closest sentence or paragraph boundary
            closest_sentence = min(sentence_ends, key=lambda x: abs(x - boundary), default=boundary)
            closest_paragraph = min(paragraph_ends, key=lambda x: abs(x - boundary), default=boundary)
            
            # Prefer paragraph boundaries, then sentence boundaries
            if abs(closest_paragraph - boundary) <= 50:  # Within 50 characters
                optimized_boundaries.append(closest_paragraph)
            elif abs(closest_sentence - boundary) <= 25:  # Within 25 characters
                optimized_boundaries.append(closest_sentence)
            else:
                optimized_boundaries.append(boundary)
        
        return optimized_boundaries
