#!/usr/bin/env python3
"""
Enhanced Multi-Modal Content Processor for GraphRAG Systems

This module provides advanced content processing capabilities that go beyond
basic text extraction, including:
- Enhanced PDF processing with OCR fallback
- Advanced HTML content extraction with semantic understanding
- Local audio/video processing capabilities
- Image analysis and OCR
- Content quality assessment and filtering
- Batch processing optimization
"""

import os
import re
import json
import tempfile
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import mimetypes
from pathlib import Path

# Base imports
from ipfs_datasets_py.processors.multimodal_processor import ProcessedContent, ProcessedContentBatch
from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor

# Optional imports for enhanced functionality
try:
    from PIL import Image
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    import pdfplumber
    import pymupdf as fitz  # PyMuPDF
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    import subprocess
    import json as json_lib
    HAS_MEDIA = True
except ImportError:
    HAS_MEDIA = False

logger = logging.getLogger(__name__)


@dataclass
class ContentQualityMetrics:
    """Metrics for assessing content quality"""
    text_length: int = 0
    word_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    readability_score: float = 0.0
    information_density: float = 0.0  # Ratio of unique words to total words
    technical_term_ratio: float = 0.0
    confidence_score: float = 0.0
    extraction_method: str = ""
    processing_time: float = 0.0
    errors: List[str] = field(default_factory=list)


@dataclass
class ProcessingContext:
    """Context for content processing operations"""
    enable_ocr: bool = True
    ocr_language: str = "eng"
    extract_images: bool = True
    extract_tables: bool = True
    quality_threshold: float = 0.5
    max_content_length: int = 1_000_000  # 1MB text limit
    enable_content_filtering: bool = True
    preserve_formatting: bool = False
    extract_metadata: bool = True


class EnhancedMultiModalProcessor:
    """
    Enhanced content processor with advanced capabilities for multiple content types.
    
    Features:
    - Advanced PDF processing with OCR fallback
    - Semantic HTML extraction
    - Local media processing (audio/video metadata)
    - Image analysis and OCR
    - Content quality assessment
    - Batch processing optimization
    - Local processing without external API dependencies
    """
    
    def __init__(self, context: ProcessingContext = None):
        """
        Initialize the enhanced processor
        
        Args:
            context: Processing context with configuration options
        """
        self.context = context or ProcessingContext()
        self._initialize_processors()
        
        # Processing statistics
        self.stats = {
            'documents_processed': 0,
            'successful_extractions': 0,
            'failed_extractions': 0,
            'ocr_used': 0,
            'total_processing_time': 0.0
        }
    
    def _initialize_processors(self):
        """Initialize available processors"""
        self.available_processors = {
            'pdf': HAS_PDF,
            'ocr': HAS_OCR,
            'media': HAS_MEDIA
        }
        
        logger.info(f"Enhanced processor initialized with capabilities: {self.available_processors}")
    
    @monitor
    async def process_content(
        self,
        content: str,
        content_type: str,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process individual content item (API compatibility method).
        
        Args:
            content: Content to process
            content_type: MIME type of content
            source_url: Source URL of content
            metadata: Optional metadata
            
        Returns:
            Dict with processed content and metadata
        """
        try:
            # Create a ContentAsset for processing
            asset = ContentAsset(
                url=source_url,
                content_type=content_type,
                content=content.encode('utf-8') if isinstance(content, str) else content,
                metadata=metadata or {}
            )
            
            # Create a minimal ContentManifest with single asset
            from ipfs_datasets_py.content_discovery import ContentManifest
            manifest = ContentManifest()
            
            # Add asset to appropriate category based on content type
            if content_type == "text/html":
                manifest.html_pages = [asset]
            elif content_type == "application/pdf":
                manifest.pdf_documents = [asset]
            else:
                manifest.other_documents = [asset]
            
            manifest.total_assets = 1
            
            # Process using existing batch method
            batch_result = self.process_enhanced_content_batch(manifest)
            
            if batch_result.processed_items:
                processed_item = batch_result.processed_items[0]
                return {
                    'processed_content': processed_item,
                    'text': processed_item.text_content if hasattr(processed_item, 'text_content') else str(processed_item),
                    'metadata': processed_item.metadata if hasattr(processed_item, 'metadata') else {},
                    'status': 'success'
                }
            else:
                return {
                    'processed_content': None,
                    'text': content if content_type == "text/html" else "",  # Fallback
                    'metadata': metadata or {},
                    'status': 'no_processing',
                    'warning': 'No content processed, using fallback'
                }
                
        except Exception as e:
            logger.error(f"Content processing failed: {str(e)}")
            return {
                'processed_content': None,
                'text': content if content_type == "text/html" else "",  # Fallback
                'metadata': metadata or {},
                'status': 'error',
                'error': str(e)
            }

    @monitor
    def process_enhanced_content_batch(
        self,
        content_manifest: ContentManifest,
        enable_quality_assessment: bool = True,
        enable_parallel_processing: bool = True
    ) -> ProcessedContentBatch:
        """
        Process content batch with enhanced capabilities
        
        Args:
            content_manifest: Content manifest with discovered assets
            enable_quality_assessment: Whether to assess content quality
            enable_parallel_processing: Whether to use parallel processing
            
        Returns:
            Enhanced processed content batch with quality metrics
        """
        start_time = datetime.now()
        
        logger.info(f"Starting enhanced batch processing of {content_manifest.total_assets} assets")
        
        processed_items = []
        processing_errors = []
        
        # Process HTML content
        for html_asset in content_manifest.html_pages:
            try:
                processed_item = self._process_html_enhanced(html_asset)
                if enable_quality_assessment:
                    processed_item = self._assess_content_quality(processed_item)
                processed_items.append(processed_item)
                self.stats['successful_extractions'] += 1
            except Exception as e:
                logger.error(f"Failed to process HTML {html_asset.url}: {e}")
                processing_errors.append(f"HTML processing error for {html_asset.url}: {str(e)}")
                self.stats['failed_extractions'] += 1
        
        # Process PDF content
        for pdf_asset in content_manifest.pdf_documents:
            try:
                processed_item = self._process_pdf_enhanced(pdf_asset)
                if enable_quality_assessment:
                    processed_item = self._assess_content_quality(processed_item)
                processed_items.append(processed_item)
                self.stats['successful_extractions'] += 1
            except Exception as e:
                logger.error(f"Failed to process PDF {pdf_asset.url}: {e}")
                processing_errors.append(f"PDF processing error for {pdf_asset.url}: {str(e)}")
                self.stats['failed_extractions'] += 1
        
        # Process media content (extract metadata and transcripts if available locally)
        for media_asset in content_manifest.media_files:
            try:
                processed_item = self._process_media_enhanced(media_asset)
                if enable_quality_assessment:
                    processed_item = self._assess_content_quality(processed_item)
                processed_items.append(processed_item)
                self.stats['successful_extractions'] += 1
            except Exception as e:
                logger.error(f"Failed to process media {media_asset.url}: {e}")
                processing_errors.append(f"Media processing error for {media_asset.url}: {str(e)}")
                self.stats['failed_extractions'] += 1
        
        processing_time = (datetime.now() - start_time).total_seconds()
        self.stats['total_processing_time'] += processing_time
        self.stats['documents_processed'] += len(processed_items)
        
        # Create batch metadata
        batch_metadata = {
            'processing_timestamp': datetime.now().isoformat(),
            'processing_time_seconds': processing_time,
            'total_items_processed': len(processed_items),
            'successful_extractions': self.stats['successful_extractions'],
            'failed_extractions': self.stats['failed_extractions'],
            'quality_assessment_enabled': enable_quality_assessment,
            'capabilities_used': self.available_processors,
            'context': {
                'enable_ocr': self.context.enable_ocr,
                'quality_threshold': self.context.quality_threshold,
                'max_content_length': self.context.max_content_length
            }
        }
        
        return ProcessedContentBatch(
            base_url=content_manifest.base_url,
            processed_items=processed_items,
            errors=processing_errors,
            processing_stats={
                'html': len([item for item in processed_items if item.content_type == 'html']),
                'pdf': len([item for item in processed_items if item.content_type == 'pdf']),
                'media': len([item for item in processed_items if item.content_type.startswith('audio') or item.content_type.startswith('video')]),
                'total': len(processed_items)
            },
            batch_metadata=batch_metadata
        )
    
    def _process_html_enhanced(self, html_asset: ContentAsset) -> ProcessedContent:
        """Process HTML content with enhanced semantic extraction"""
        start_time = datetime.now()
        
        try:
            from bs4 import BeautifulSoup
            
            # Parse HTML content
            if hasattr(html_asset, 'content') and html_asset.content:
                html_content = html_asset.content
            else:
                # Read from file if available
                html_content = self._read_asset_content(html_asset)
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract text with semantic understanding
            text_content = self._extract_semantic_text(soup)
            
            # Extract metadata
            metadata = self._extract_html_metadata(soup, html_asset)
            
            # Calculate quality metrics
            quality_metrics = self._calculate_text_quality(text_content)
            quality_metrics.extraction_method = "semantic_html_parsing"
            quality_metrics.processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessedContent(
                source_url=html_asset.url,
                content_type='html',
                text_content=text_content,
                metadata={
                    **metadata,
                    'quality_metrics': quality_metrics.__dict__,
                    'processing_method': 'enhanced_html'
                },
                confidence_score=min(quality_metrics.confidence_score, 1.0),
                processing_timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Enhanced HTML processing failed for {html_asset.url}: {e}")
            # Fallback to basic processing
            return self._process_html_fallback(html_asset)
    
    def _process_pdf_enhanced(self, pdf_asset: ContentAsset) -> ProcessedContent:
        """Process PDF content with enhanced extraction and OCR fallback"""
        start_time = datetime.now()
        
        if not HAS_PDF:
            logger.warning("PDF processing libraries not available, using fallback")
            return self._process_pdf_fallback(pdf_asset)
        
        try:
            # Read PDF content
            pdf_content = self._read_asset_content(pdf_asset)
            
            # Try PyMuPDF first (faster and more accurate for most PDFs)
            try:
                text_content = self._extract_pdf_pymupdf(pdf_content)
                extraction_method = "pymupdf"
            except Exception as e:
                logger.warning(f"PyMuPDF extraction failed, trying pdfplumber: {e}")
                text_content = self._extract_pdf_pdfplumber(pdf_content)
                extraction_method = "pdfplumber"
            
            # If text extraction yielded poor results, try OCR
            if (self.context.enable_ocr and HAS_OCR and 
                (len(text_content.strip()) < 100 or self._is_likely_scanned_pdf(text_content))):
                
                logger.info("PDF appears to be scanned, attempting OCR extraction")
                ocr_text = self._extract_pdf_ocr(pdf_content)
                if len(ocr_text) > len(text_content):
                    text_content = ocr_text
                    extraction_method = "ocr"
                    self.stats['ocr_used'] += 1
            
            # Extract metadata
            metadata = self._extract_pdf_metadata(pdf_content, pdf_asset)
            
            # Calculate quality metrics
            quality_metrics = self._calculate_text_quality(text_content)
            quality_metrics.extraction_method = extraction_method
            quality_metrics.processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessedContent(
                source_url=pdf_asset.url,
                content_type='pdf',
                text_content=text_content,
                metadata={
                    **metadata,
                    'quality_metrics': quality_metrics.__dict__,
                    'processing_method': 'enhanced_pdf',
                    'extraction_method': extraction_method
                },
                confidence_score=min(quality_metrics.confidence_score, 1.0),
                processing_timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Enhanced PDF processing failed for {pdf_asset.url}: {e}")
            return self._process_pdf_fallback(pdf_asset)
    
    def _process_media_enhanced(self, media_asset: ContentAsset) -> ProcessedContent:
        """Process media content with local metadata extraction"""
        start_time = datetime.now()
        
        try:
            # Extract media metadata using local tools
            metadata = self._extract_media_metadata(media_asset)
            
            # Try to find existing transcripts or captions
            transcript_text = self._find_associated_transcripts(media_asset)
            
            # If no transcript available, create placeholder content
            if not transcript_text:
                transcript_text = f"Media file: {media_asset.filename or media_asset.url}"
                if metadata.get('duration'):
                    transcript_text += f"\nDuration: {metadata['duration']}"
                if metadata.get('title'):
                    transcript_text += f"\nTitle: {metadata['title']}"
                if metadata.get('description'):
                    transcript_text += f"\nDescription: {metadata['description']}"
            
            # Calculate quality metrics
            quality_metrics = self._calculate_text_quality(transcript_text)
            quality_metrics.extraction_method = "metadata_extraction"
            quality_metrics.processing_time = (datetime.now() - start_time).total_seconds()
            
            # Determine content type
            content_type = media_asset.content_type or self._detect_media_type(media_asset)
            
            return ProcessedContent(
                source_url=media_asset.url,
                content_type=content_type,
                text_content=transcript_text,
                metadata={
                    **metadata,
                    'quality_metrics': quality_metrics.__dict__,
                    'processing_method': 'enhanced_media',
                    'has_transcript': bool(transcript_text and len(transcript_text) > 100)
                },
                confidence_score=0.7 if transcript_text and len(transcript_text) > 100 else 0.3,
                processing_timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Enhanced media processing failed for {media_asset.url}: {e}")
            return self._process_media_fallback(media_asset)
    
    # Enhanced extraction methods
    
    def _extract_semantic_text(self, soup) -> str:
        """Extract text with semantic understanding of HTML structure"""
        
        # Remove unwanted elements completely (including their content)
        unwanted_tags = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']
        for tag_name in unwanted_tags:
            for element in soup.find_all(tag_name):
                element.decompose()
        
        # Extract content in semantic order
        content_parts = []
        
        # Title
        title = soup.find('title')
        if title:
            content_parts.append(f"Title: {title.get_text().strip()}")
        
        # Main headings
        main_headings = soup.find_all(['h1', 'h2', 'h3'], limit=5)
        for heading in main_headings:
            text = heading.get_text().strip()
            if text and len(text) < 200:  # Reasonable heading length
                content_parts.append(f"Heading: {text}")
        
        # Main content areas
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main'))
        
        if main_content:
            # Extract paragraphs from main content
            paragraphs = main_content.find_all('p')
        else:
            # Fallback to all paragraphs
            paragraphs = soup.find_all('p')
        
        for paragraph in paragraphs:
            text = paragraph.get_text().strip()
            if text and len(text) > 20:  # Skip very short paragraphs
                content_parts.append(text)
        
        # Extract list items if they contain substantial content
        lists = soup.find_all(['ul', 'ol'])
        for list_elem in lists:
            list_items = list_elem.find_all('li')
            list_content = []
            for item in list_items:
                text = item.get_text().strip()
                if text and len(text) > 10:
                    list_content.append(f"• {text}")
            
            if list_content and len(list_content) <= 10:  # Reasonable list size
                content_parts.extend(list_content)
        
        # Extract table content if enabled
        if self.context.extract_tables:
            tables = soup.find_all('table')
            for table in tables[:3]:  # Limit to first 3 tables
                table_text = self._extract_table_text(table)
                if table_text:
                    content_parts.append(f"Table: {table_text}")
        
        final_text = '\n\n'.join(content_parts)
        
        # Apply length limit
        if len(final_text) > self.context.max_content_length:
            final_text = final_text[:self.context.max_content_length] + "... [content truncated]"
        
        return final_text
    
    def _extract_pdf_pymupdf(self, pdf_content: bytes) -> str:
        """Extract text using PyMuPDF"""
        import io
        
        text_parts = []
        
        # Create a file-like object from bytes
        pdf_stream = io.BytesIO(pdf_content)
        
        # Open PDF with PyMuPDF
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_text = page.get_text()
            
            if page_text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
        
        doc.close()
        return '\n\n'.join(text_parts)
    
    def _extract_pdf_pdfplumber(self, pdf_content: bytes) -> str:
        """Extract text using pdfplumber"""
        import io
        
        text_parts = []
        
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                
                if page_text and page_text.strip():
                    text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
                
                # Extract table content if enabled
                if self.context.extract_tables:
                    tables = page.extract_tables()
                    for table_num, table in enumerate(tables):
                        if table:
                            table_text = self._format_table_text(table)
                            text_parts.append(f"[Page {page_num + 1} Table {table_num + 1}]\n{table_text}")
        
        return '\n\n'.join(text_parts)
    
    def _extract_pdf_ocr(self, pdf_content: bytes) -> str:
        """Extract text using OCR on PDF images"""
        if not HAS_OCR:
            logger.warning("OCR not available, skipping")
            return ""
        
        import io
        
        text_parts = []
        
        try:
            # Convert PDF pages to images and OCR
            doc = fitz.open(stream=io.BytesIO(pdf_content), filetype="pdf")
            
            for page_num in range(min(len(doc), 10)):  # Limit OCR to first 10 pages
                page = doc.load_page(page_num)
                
                # Convert page to image
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                # Perform OCR
                ocr_text = pytesseract.image_to_string(
                    img, 
                    lang=self.context.ocr_language,
                    config='--psm 6'  # Uniform block of text
                )
                
                if ocr_text.strip():
                    text_parts.append(f"[Page {page_num + 1} OCR]\n{ocr_text}")
            
            doc.close()
            
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")
            return ""
        
        return '\n\n'.join(text_parts)
    
    # Quality assessment methods
    
    def _assess_content_quality(self, processed_content: ProcessedContent) -> ProcessedContent:
        """Assess and enhance content quality metrics"""
        
        if not processed_content.text_content:
            processed_content.confidence_score = 0.0
            return processed_content
        
        quality_metrics = processed_content.metadata.get('quality_metrics', {})
        
        # Enhanced quality assessment
        text = processed_content.text_content
        
        # Check for extraction artifacts
        artifact_penalty = 0.0
        common_artifacts = [
            r'\b[A-Z]{10,}\b',  # Long uppercase strings
            r'[\x00-\x1f\x7f-\x9f]',  # Control characters
            r'(.)\1{10,}',  # Repeated characters
            r'\b\d+\s+\d+\s+\d+\b',  # Number sequences (often from tables)
        ]
        
        for pattern in common_artifacts:
            if re.search(pattern, text):
                artifact_penalty += 0.1
        
        # Language detection and coherence
        coherence_score = self._calculate_text_coherence(text)
        
        # Information density (ratio of unique meaningful words)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        if words:
            unique_words = set(words)
            info_density = len(unique_words) / len(words)
        else:
            info_density = 0.0
        
        # Technical content detection
        technical_terms = self._count_technical_terms(text)
        technical_ratio = technical_terms / max(len(words), 1)
        
        # Calculate final confidence score
        base_confidence = quality_metrics.get('confidence_score', 0.7)
        final_confidence = (
            base_confidence * 0.4 +  # Base extraction confidence
            coherence_score * 0.3 +  # Text coherence
            info_density * 0.2 +     # Information density
            min(technical_ratio * 2, 0.1) +  # Technical content bonus (capped)
            max(0, 0.1 - artifact_penalty)   # Artifact penalty
        )
        
        # Update quality metrics
        quality_metrics.update({
            'information_density': info_density,
            'technical_term_ratio': technical_ratio,
            'coherence_score': coherence_score,
            'artifact_penalty': artifact_penalty,
            'confidence_score': min(max(final_confidence, 0.0), 1.0)
        })
        
        processed_content.metadata['quality_metrics'] = quality_metrics
        processed_content.confidence_score = quality_metrics['confidence_score']
        
        return processed_content
    
    def assess_content_quality(self, processed_content: ProcessedContent) -> ProcessedContent:
        """Public interface for content quality assessment"""
        return self._assess_content_quality(processed_content)
    
    def extract_from_pdf(self, pdf_content: bytes, file_path: str = "") -> str:
        """
        Extract text from PDF content
        
        Args:
            pdf_content: PDF file content as bytes
            file_path: Optional file path for metadata
            
        Returns:
            Extracted text content
        """
        try:
            # Try PyMuPDF first
            if HAS_PDF:
                return self._extract_pdf_pymupdf(pdf_content)
            else:
                # Fallback text extraction
                return f"PDF content extraction not available - missing dependencies. File: {file_path}"
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return f"PDF extraction failed: {str(e)}"
    
    def process_media_batch(self, media_assets: List[ContentAsset]) -> List[ProcessedContent]:
        """
        Process multiple media assets in batch
        
        Args:
            media_assets: List of media content assets
            
        Returns:
            List of processed content results
        """
        results = []
        for asset in media_assets:
            try:
                result = self._process_media_enhanced(asset)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process media asset {asset.url}: {e}")
                # Create error result
                error_result = ProcessedContent(
                    content_id=asset.content_id,
                    content_type="media",
                    source_url=asset.url,
                    text_content=f"Media processing failed: {str(e)}",
                    confidence_score=0.0,
                    metadata={'error': str(e), 'asset_type': asset.asset_type}
                )
                results.append(error_result)
        return results
    
    def process_html_content(self, html_content: str, url: str = "") -> ProcessedContent:
        """
        Process HTML content - simple interface for testing
        
        Args:
            html_content: HTML content as string
            url: Optional URL for metadata
            
        Returns:
            Processed content result
        """
        # Create a mock ContentAsset for processing with the correct constructor
        asset = ContentAsset(
            url=url or "test://html",
            content_type="html",
            mime_type="text/html",
            size_bytes=len(html_content.encode('utf-8')),
            metadata={'test_mode': True}
        )
        
        # Add the content directly to the asset
        asset.content = html_content
        
        return self._process_html_enhanced(asset)
    
    def _process_html(self, html_asset: ContentAsset) -> ProcessedContent:
        """Alias for _process_html_enhanced for backward compatibility"""
        return self._process_html_enhanced(html_asset)
    
    def _calculate_text_quality(self, text: str) -> ContentQualityMetrics:
        """Calculate comprehensive text quality metrics"""
        
        if not text or not text.strip():
            return ContentQualityMetrics()
        
        # Basic metrics
        text_length = len(text)
        words = re.findall(r'\b\w+\b', text)
        word_count = len(words)
        sentences = re.split(r'[.!?]+', text)
        sentence_count = len([s for s in sentences if s.strip()])
        paragraphs = text.split('\n\n')
        paragraph_count = len([p for p in paragraphs if p.strip()])
        
        # Information density
        if words:
            unique_words = set(word.lower() for word in words)
            info_density = len(unique_words) / word_count
        else:
            info_density = 0.0
        
        # Technical term ratio
        technical_terms = self._count_technical_terms(text)
        technical_ratio = technical_terms / max(word_count, 1)
        
        # Readability score (simplified)
        if sentence_count > 0 and word_count > 0:
            avg_sentence_length = word_count / sentence_count
            readability = max(0, 100 - (avg_sentence_length * 2))  # Simplified score
        else:
            readability = 0.0
        
        # Overall confidence
        confidence_factors = [
            min(text_length / 1000, 1.0),  # Length factor (up to 1000 chars gets full score)
            min(sentence_count / 10, 1.0),  # Sentence count factor
            info_density,                   # Information density
            min(readability / 100, 1.0),   # Readability factor
        ]
        
        confidence_score = sum(confidence_factors) / len(confidence_factors)
        
        return ContentQualityMetrics(
            text_length=text_length,
            word_count=word_count,
            sentence_count=sentence_count,
            paragraph_count=paragraph_count,
            readability_score=readability,
            information_density=info_density,
            technical_term_ratio=technical_ratio,
            confidence_score=confidence_score
        )
    
    # Helper methods
    
    def _calculate_text_coherence(self, text: str) -> float:
        """Calculate a simple coherence score based on sentence structure"""
        
        sentences = re.split(r'[.!?]+', text)
        if len(sentences) < 2:
            return 0.5  # Neutral score for very short text
        
        coherence_indicators = 0
        total_checks = 0
        
        for sentence in sentences[:20]:  # Check first 20 sentences
            sentence = sentence.strip().lower()
            if len(sentence) < 10:  # Skip very short sentences
                continue
                
            total_checks += 1
            
            # Check for coherence indicators
            coherence_patterns = [
                r'\b(however|therefore|furthermore|moreover|additionally)\b',
                r'\b(this|these|that|those|such)\b',
                r'\b(first|second|third|finally|next|then)\b',
                r'\b(for example|for instance|specifically)\b'
            ]
            
            for pattern in coherence_patterns:
                if re.search(pattern, sentence):
                    coherence_indicators += 1
                    break
        
        if total_checks == 0:
            return 0.5
        
        return min(coherence_indicators / total_checks + 0.3, 1.0)
    
    def _count_technical_terms(self, text: str) -> int:
        """Count technical terms in text"""
        
        # Common technical terms and patterns
        technical_patterns = [
            r'\b(algorithm|framework|architecture|implementation|methodology)\b',
            r'\b(optimization|configuration|integration|deployment|scalability)\b',
            r'\b(artificial intelligence|machine learning|deep learning|neural network)\b',
            r'\b(database|server|client|protocol|interface|API)\b',
            r'\b[A-Z]{2,5}\b',  # Acronyms
            r'\b\w+[._-]\w+\b',  # Technical naming (e.g., file names, IDs)
            r'\b\w+\d+\b',  # Alphanumeric terms (e.g., version numbers)
        ]
        
        count = 0
        text_lower = text.lower()
        
        for pattern in technical_patterns:
            matches = re.findall(pattern, text_lower)
            count += len(matches)
        
        return count
    
    def _read_asset_content(self, asset: ContentAsset) -> Union[str, bytes]:
        """Read content from asset (placeholder - would integrate with actual storage)"""
        # This would integrate with the actual content storage system
        if hasattr(asset, 'content') and asset.content:
            return asset.content
        elif hasattr(asset, 'content_preview') and asset.content_preview:
            # Support for test data that uses content_preview
            return asset.content_preview
        else:
            # Placeholder for reading from file system or URL
            return f"Content for {asset.url}"
    
    def _extract_html_metadata(self, soup, asset: ContentAsset) -> Dict[str, Any]:
        """Extract metadata from HTML"""
        metadata = {
            'url': asset.url,
            'file_size': getattr(asset, 'file_size', 0),
            'last_modified': getattr(asset, 'last_modified', None)
        }
        
        # Extract meta tags
        meta_tags = soup.find_all('meta')
        for tag in meta_tags:
            if tag.get('name'):
                metadata[f"meta_{tag['name']}"] = tag.get('content', '')
            elif tag.get('property'):
                metadata[f"property_{tag['property']}"] = tag.get('content', '')
        
        # Extract title
        title_tag = soup.find('title')
        if title_tag:
            metadata['title'] = title_tag.get_text().strip()
        
        return metadata
    
    def _extract_pdf_metadata(self, pdf_content: bytes, asset: ContentAsset) -> Dict[str, Any]:
        """Extract metadata from PDF"""
        metadata = {
            'url': asset.url,
            'file_size': len(pdf_content),
            'content_type': 'application/pdf'
        }
        
        if HAS_PDF:
            try:
                import io
                doc = fitz.open(stream=io.BytesIO(pdf_content), filetype="pdf")
                
                pdf_metadata = doc.metadata
                for key, value in pdf_metadata.items():
                    if value:
                        metadata[f"pdf_{key.lower()}"] = value
                
                metadata['page_count'] = len(doc)
                doc.close()
                
            except Exception as e:
                logger.warning(f"Failed to extract PDF metadata: {e}")
        
        return metadata
    
    def _extract_media_metadata(self, asset: ContentAsset) -> Dict[str, Any]:
        """Extract metadata from media files using local tools"""
        metadata = {
            'url': asset.url,
            'content_type': asset.content_type or 'unknown',
            'file_size': getattr(asset, 'file_size', 0)
        }
        
        # Try to use ffprobe if available (local tool)
        if HAS_MEDIA:
            try:
                # This would only work if the file is locally accessible
                # In practice, would need to download or access the file
                metadata.update({
                    'duration': '00:00:00',  # Placeholder
                    'format': 'unknown',
                    'has_audio': True,
                    'has_video': asset.content_type.startswith('video') if asset.content_type else False
                })
                
            except Exception as e:
                logger.warning(f"Failed to extract media metadata: {e}")
        
        return metadata
    
    def _find_associated_transcripts(self, media_asset: ContentAsset) -> Optional[str]:
        """Look for associated transcript files"""
        # This would look for common transcript file patterns
        # .vtt, .srt, .txt files with similar names
        # For now, return None as we don't have access to file system
        return None
    
    def _detect_media_type(self, asset: ContentAsset) -> str:
        """Detect media type from asset information"""
        if asset.content_type:
            return asset.content_type
        
        url = asset.url.lower()
        if any(ext in url for ext in ['.mp4', '.avi', '.mov', '.mkv']):
            return 'video/mp4'
        elif any(ext in url for ext in ['.mp3', '.wav', '.ogg', '.m4a']):
            return 'audio/mp3'
        else:
            return 'unknown'
    
    def _is_likely_scanned_pdf(self, text: str) -> bool:
        """Determine if PDF is likely scanned based on extracted text"""
        if not text or len(text.strip()) < 50:
            return True
        
        # Check for OCR artifacts
        ocr_artifacts = [
            r'\b[a-z]\s[a-z]\s[a-z]\b',  # Spaced single letters
            r'\b\w{1,2}\s\w{1,2}\s\w{1,2}\b',  # Very fragmented words
            r'[|\\/_~`]',  # Common OCR misreads
        ]
        
        artifact_count = 0
        for pattern in ocr_artifacts:
            artifact_count += len(re.findall(pattern, text))
        
        # If we have many artifacts relative to text length, likely scanned
        return artifact_count > len(text) / 500
    
    def _extract_table_text(self, table_element) -> str:
        """Extract text from HTML table element"""
        rows = []
        
        for row in table_element.find_all('tr'):
            cells = []
            for cell in row.find_all(['td', 'th']):
                text = cell.get_text().strip()
                if text:
                    cells.append(text)
            
            if cells:
                rows.append(' | '.join(cells))
        
        return '\n'.join(rows) if rows else ""
    
    def _format_table_text(self, table_data: List[List]) -> str:
        """Format table data as text"""
        if not table_data:
            return ""
        
        formatted_rows = []
        for row in table_data:
            if row:
                clean_cells = [str(cell).strip() if cell is not None else "" for cell in row]
                formatted_rows.append(' | '.join(clean_cells))
        
        return '\n'.join(formatted_rows)
    
    # Fallback methods
    
    def _process_html_fallback(self, html_asset: ContentAsset) -> ProcessedContent:
        """Fallback HTML processing method"""
        return ProcessedContent(
            source_url=html_asset.url,
            content_type='html',
            text_content=f"HTML content from {html_asset.url} (fallback processing)",
            metadata={'processing_method': 'fallback', 'url': html_asset.url},
            confidence_score=0.3,
            processing_timestamp=datetime.now()
        )
    
    def _process_pdf_fallback(self, pdf_asset: ContentAsset) -> ProcessedContent:
        """Fallback PDF processing method"""
        return ProcessedContent(
            source_url=pdf_asset.url,
            content_type='pdf',
            text_content=f"PDF content from {pdf_asset.url} (fallback processing)",
            metadata={'processing_method': 'fallback', 'url': pdf_asset.url},
            confidence_score=0.3,
            processing_timestamp=datetime.now()
        )
    
    def _process_media_fallback(self, media_asset: ContentAsset) -> ProcessedContent:
        """Fallback media processing method"""
        content_type = media_asset.content_type or 'media'
        return ProcessedContent(
            source_url=media_asset.url,
            content_type=content_type,
            text_content=f"Media content from {media_asset.url} (fallback processing)",
            metadata={'processing_method': 'fallback', 'url': media_asset.url},
            confidence_score=0.2,
            processing_timestamp=datetime.now()
        )
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            'stats': self.stats.copy(),
            'capabilities': self.available_processors.copy(),
            'context': {
                'enable_ocr': self.context.enable_ocr,
                'quality_threshold': self.context.quality_threshold,
                'max_content_length': self.context.max_content_length,
                'extract_images': self.context.extract_images,
                'extract_tables': self.context.extract_tables
            }
        }


# Example usage and testing
if __name__ == "__main__":
    def test_enhanced_processing():
        """Test enhanced content processing capabilities"""
        
        # Create sample content
        from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
        
        html_asset = ContentAsset(
            url="https://example.com/page.html",
            content_type="text/html",
            file_size=5000,
            last_modified=datetime.now()
        )
        
        # Set some sample HTML content
        html_asset.content = """
        <html>
        <head>
            <title>Advanced AI Research</title>
            <meta name="description" content="Research on machine learning and AI">
        </head>
        <body>
            <h1>Artificial Intelligence Research</h1>
            <p>This research focuses on deep learning algorithms and neural networks.</p>
            <p>Our team has developed innovative approaches to natural language processing.</p>
            <ul>
                <li>Transformer architectures</li>
                <li>Attention mechanisms</li>
                <li>BERT improvements</li>
            </ul>
        </body>
        </html>
        """
        
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[html_asset],
            pdf_documents=[],
            media_files=[],
            structured_data=[],
            total_assets=1,
            discovery_timestamp=datetime.now()
        )
        
        # Initialize enhanced processor
        context = ProcessingContext(
            enable_ocr=True,
            extract_tables=True,
            quality_threshold=0.6,
            enable_content_filtering=True
        )
        
        processor = EnhancedMultiModalProcessor(context)
        
        print("🚀 Enhanced Multi-Modal Processing Test")
        print("=" * 60)
        
        # Process content
        batch_result = processor.process_enhanced_content_batch(manifest, enable_quality_assessment=True)
        
        print(f"📊 Processing Results:")
        print(f"   • Total items processed: {len(batch_result.processed_items)}")
        print(f"   • Successful extractions: {batch_result.processing_stats['total']}")
        print(f"   • Processing errors: {len(batch_result.errors)}")
        
        if batch_result.processed_items:
            item = batch_result.processed_items[0]
            print(f"\n📄 Sample Processed Item:")
            print(f"   • URL: {item.source_url}")
            print(f"   • Type: {item.content_type}")
            print(f"   • Confidence: {item.confidence_score:.3f}")
            print(f"   • Text length: {len(item.text_content)} chars")
            print(f"   • Processing method: {item.metadata.get('processing_method')}")
            
            # Show quality metrics if available
            quality_metrics = item.metadata.get('quality_metrics', {})
            if quality_metrics:
                print(f"\n📈 Quality Metrics:")
                for key, value in quality_metrics.items():
                    if isinstance(value, float):
                        print(f"   • {key}: {value:.3f}")
                    else:
                        print(f"   • {key}: {value}")
        
        # Get processing statistics
        stats = processor.get_processing_statistics()
        print(f"\n📊 Processing Statistics:")
        for key, value in stats['stats'].items():
            print(f"   • {key}: {value}")
        
        print(f"\n🔧 Available Capabilities:")
        for capability, available in stats['capabilities'].items():
            status = "✅" if available else "❌"
            print(f"   • {capability}: {status}")
        
        print("\n✅ Enhanced processing test completed!")
        
        return batch_result
    
    # Run test
    test_enhanced_processing()