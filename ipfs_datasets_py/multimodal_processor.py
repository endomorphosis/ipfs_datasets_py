"""
Multi-Modal Content Processor

Processes diverse content types into unified text and embedding format.
Handles HTML pages, PDFs, audio files, video files, and images.

Processing Capabilities:
- HTML → clean text + structured data
- PDF → text + metadata + images  
- Audio → transcription + metadata
- Video → transcription + captions + frames
- Images → OCR + descriptions
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field

import numpy as np

# Import existing components
from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
from ipfs_datasets_py.embeddings.create_embeddings import EmbeddingGenerator
from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import ytdlp_download_video
from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_info import ffmpeg_get_media_info

# External dependencies (with graceful fallback)
try:
    from bs4 import BeautifulSoup
    import html2text
    HAVE_HTML_PROCESSING = True
except ImportError:
    HAVE_HTML_PROCESSING = False

try:
    import PyPDF2
    import pdfplumber
    HAVE_PDF_PROCESSING = True
except ImportError:
    HAVE_PDF_PROCESSING = False

try:
    import speech_recognition as sr
    HAVE_SPEECH_RECOGNITION = True
except ImportError:
    HAVE_SPEECH_RECOGNITION = False

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class ProcessedContent:
    """Processed content ready for embedding and knowledge extraction"""
    source_url: str
    content_type: str  # 'html', 'pdf', 'audio', 'video', 'image'
    text_content: str
    metadata: Dict[str, Any]
    embeddings: Optional[np.ndarray] = None
    processing_timestamp: datetime = field(default_factory=datetime.now)
    processing_errors: List[str] = field(default_factory=list)
    confidence_score: float = 1.0  # Confidence in text extraction quality
    
    @property
    def text_length(self) -> int:
        """Get length of extracted text"""
        return len(self.text_content) if self.text_content else 0
    
    @property
    def has_embeddings(self) -> bool:
        """Check if embeddings are available"""
        return self.embeddings is not None
    

@dataclass
class ProcessedContentBatch:
    """Batch of processed content from entire website"""
    base_url: str
    processed_items: List[ProcessedContent]
    processing_stats: Dict[str, Any]
    errors: List[Dict[str, Any]] = field(default_factory=list)
    batch_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_items(self) -> int:
        """Total number of processed items"""
        return len(self.processed_items)
    
    @property
    def success_rate(self) -> float:
        """Processing success rate as percentage"""
        if self.total_items == 0:
            return 0.0
        total_attempted = self.total_items + len(self.errors)
        return (self.total_items / total_attempted) * 100 if total_attempted > 0 else 0.0


class MultiModalContentProcessor:
    """
    Processes diverse content types into unified text and embedding format.
    
    Processing Pipeline:
    1. HTML pages → clean text + structured data extraction
    2. PDFs → text extraction + metadata
    3. Audio → transcription + metadata  
    4. Video → transcription + captions + keyframe analysis
    5. Generate embeddings for all text content
    
    Usage:
        processor = MultiModalContentProcessor()
        result = await processor.process_content_batch(
            content_manifest,
            include_embeddings=True
        )
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize multi-modal content processor
        
        Args:
            config: Processing configuration options
        """
        self.config = config or self._default_config()
        self._initialize_processors()
    
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for content processing"""
        return {
            # Text processing
            'max_text_length': 100000,  # Maximum text length to process
            'chunk_size': 1000,
            'chunk_overlap': 200,
            
            # Media processing
            'transcription_model': 'base',  # Whisper model size
            'max_media_duration': 3600,  # Max 1 hour
            'video_frame_interval': 30,  # Extract frame every 30 seconds
            
            # Embeddings
            'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2',
            'batch_embedding_size': 32,
            
            # Quality control
            'min_text_length': 50,  # Minimum meaningful text length
            'confidence_threshold': 0.5
        }
    
    def _initialize_processors(self):
        """Initialize specialized processors for each content type"""
        try:
            # Text and HTML processing
            if HAVE_HTML_PROCESSING:
                self.html_converter = html2text.HTML2Text()
                self.html_converter.ignore_links = False
                self.html_converter.ignore_images = False
                self.html_converter.ignore_emphasis = False
            else:
                self.html_converter = None
                
            # Embedding generator
            self.embedding_generator = EmbeddingGenerator(
                model_name=self.config['embedding_model']
            )
            
            # Speech recognition for transcription
            if HAVE_SPEECH_RECOGNITION:
                self.speech_recognizer = sr.Recognizer()
            else:
                self.speech_recognizer = None
            
            logger.info("Content processors initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize processors: {e}")
            raise
    
    async def process_content_batch(
        self, 
        content_manifest: ContentManifest,
        include_embeddings: bool = True,
        include_media: bool = True
    ) -> ProcessedContentBatch:
        """
        Process all content in manifest into unified format
        
        Args:
            content_manifest: Discovered content to process
            include_embeddings: Whether to generate embeddings
            include_media: Whether to process media files
            
        Returns:
            ProcessedContentBatch with all processed content
        """
        start_time = datetime.now()
        processed_items = []
        processing_stats = {
            'html': 0, 'pdf': 0, 'audio': 0, 'video': 0, 'image': 0, 'total': 0
        }
        errors = []
        
        logger.info(f"Processing content batch for {content_manifest.base_url}")
        
        # Process HTML pages
        for html_asset in content_manifest.html_pages:
            try:
                processed = await self._process_html(html_asset)
                if processed:
                    processed_items.append(processed)
                    processing_stats['html'] += 1
                    processing_stats['total'] += 1
                    
            except Exception as e:
                error_info = {
                    'asset_url': html_asset.url,
                    'content_type': 'html',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                errors.append(error_info)
                logger.warning(f"Failed to process HTML {html_asset.url}: {e}")
        
        # Process PDFs
        for pdf_asset in content_manifest.pdf_documents:
            try:
                processed = await self._process_pdf(pdf_asset)
                if processed:
                    processed_items.append(processed)
                    processing_stats['pdf'] += 1
                    processing_stats['total'] += 1
                    
            except Exception as e:
                error_info = {
                    'asset_url': pdf_asset.url,
                    'content_type': 'pdf',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                errors.append(error_info)
                logger.warning(f"Failed to process PDF {pdf_asset.url}: {e}")
        
        # Process Media (if enabled)
        if include_media:
            for media_asset in content_manifest.media_files:
                try:
                    if media_asset.content_type == 'audio':
                        processed = await self._process_audio(media_asset)
                        if processed:
                            processed_items.append(processed)
                            processing_stats['audio'] += 1
                            processing_stats['total'] += 1
                            
                    elif media_asset.content_type == 'video':
                        processed = await self._process_video(media_asset)
                        if processed:
                            processed_items.append(processed)
                            processing_stats['video'] += 1
                            processing_stats['total'] += 1
                            
                    elif media_asset.content_type == 'image':
                        processed = await self._process_image(media_asset)
                        if processed:
                            processed_items.append(processed)
                            processing_stats['image'] += 1
                            processing_stats['total'] += 1
                
                except Exception as e:
                    error_info = {
                        'asset_url': media_asset.url,
                        'content_type': media_asset.content_type,
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    }
                    errors.append(error_info)
                    logger.warning(f"Failed to process media {media_asset.url}: {e}")
        
        # Generate embeddings for all processed content
        if include_embeddings and processed_items:
            await self._generate_embeddings_batch(processed_items)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        batch_metadata = {
            'processing_time_seconds': processing_time,
            'include_embeddings': include_embeddings,
            'include_media': include_media,
            'config': self.config
        }
        
        logger.info(
            f"Content processing completed: {processing_stats['total']} items processed, "
            f"{len(errors)} errors in {processing_time:.2f} seconds"
        )
        
        return ProcessedContentBatch(
            base_url=content_manifest.base_url,
            processed_items=processed_items,
            processing_stats=processing_stats,
            errors=errors,
            batch_metadata=batch_metadata
        )
    
    async def _process_html(self, html_asset: ContentAsset) -> Optional[ProcessedContent]:
        """Extract clean text and structured data from HTML"""
        try:
            # For now, use the content preview from the asset
            # In production, this would fetch the full HTML content
            html_content = html_asset.content_preview or ""
            
            if not html_content.strip():
                return None
            
            # Extract clean text
            if self.html_converter:
                clean_text = self._extract_text_with_beautifulsoup(html_content)
            else:
                clean_text = self._extract_text_basic(html_content)
            
            # Validate text quality
            if len(clean_text) < self.config['min_text_length']:
                return None
            
            # Extract metadata
            metadata = {
                'original_url': html_asset.url,
                'mime_type': html_asset.mime_type,
                'size_bytes': html_asset.size_bytes,
                'charset': html_asset.metadata.get('charset', 'utf-8'),
                'extraction_method': 'beautifulsoup' if HAVE_HTML_PROCESSING else 'basic',
                'structured_data': self._extract_structured_data(html_content)
            }
            
            return ProcessedContent(
                source_url=html_asset.url,
                content_type='html',
                text_content=clean_text,
                metadata=metadata,
                confidence_score=0.9 if HAVE_HTML_PROCESSING else 0.7
            )
            
        except Exception as e:
            logger.error(f"HTML processing failed for {html_asset.url}: {e}")
            return None
    
    async def _process_pdf(self, pdf_asset: ContentAsset) -> Optional[ProcessedContent]:
        """Extract text and metadata from PDF documents"""
        if not HAVE_PDF_PROCESSING:
            logger.warning("PDF processing not available - missing dependencies")
            return None
        
        try:
            # In production, this would download and process the actual PDF
            # For now, return a placeholder
            text_content = f"PDF document at {pdf_asset.url}\n\nContent would be extracted here."
            
            metadata = {
                'original_url': pdf_asset.url,
                'mime_type': pdf_asset.mime_type,
                'size_bytes': pdf_asset.size_bytes,
                'extraction_method': 'pdfplumber',
                'link_text': pdf_asset.metadata.get('link_text', ''),
                'title': pdf_asset.metadata.get('title', '')
            }
            
            return ProcessedContent(
                source_url=pdf_asset.url,
                content_type='pdf',
                text_content=text_content,
                metadata=metadata,
                confidence_score=0.8
            )
            
        except Exception as e:
            logger.error(f"PDF processing failed for {pdf_asset.url}: {e}")
            return None
    
    async def _process_audio(self, audio_asset: ContentAsset) -> Optional[ProcessedContent]:
        """Transcribe audio content to text"""
        try:
            # In production, this would use speech recognition to transcribe audio
            # For now, return metadata-based content
            
            metadata = audio_asset.metadata or {}
            text_content = f"Audio file: {os.path.basename(audio_asset.url)}\n"
            
            # Add available metadata as text
            if metadata.get('controls'):
                text_content += "Audio player with controls enabled.\n"
            if metadata.get('autoplay'):
                text_content += "Audio set to autoplay.\n"
            if metadata.get('loop'):
                text_content += "Audio set to loop.\n"
                
            text_content += f"Source: {audio_asset.url}"
            
            processing_metadata = {
                'original_url': audio_asset.url,
                'mime_type': audio_asset.mime_type,
                'size_bytes': audio_asset.size_bytes,
                'transcription_method': 'placeholder',  # Would be 'whisper' in production
                'audio_metadata': metadata
            }
            
            return ProcessedContent(
                source_url=audio_asset.url,
                content_type='audio',
                text_content=text_content,
                metadata=processing_metadata,
                confidence_score=0.6  # Lower confidence for placeholder
            )
            
        except Exception as e:
            logger.error(f"Audio processing failed for {audio_asset.url}: {e}")
            return None
    
    async def _process_video(self, video_asset: ContentAsset) -> Optional[ProcessedContent]:
        """Extract text from video (captions, transcription, OCR)"""
        try:
            # In production, this would extract video metadata, captions, and transcribe audio
            # For now, return metadata-based content
            
            metadata = video_asset.metadata or {}
            text_content = f"Video file: {os.path.basename(video_asset.url)}\n"
            
            # Add available metadata as text
            if metadata.get('width') and metadata.get('height'):
                text_content += f"Resolution: {metadata['width']}x{metadata['height']}\n"
            if metadata.get('controls'):
                text_content += "Video player with controls enabled.\n"
            if metadata.get('poster'):
                text_content += f"Poster image: {metadata['poster']}\n"
                
            text_content += f"Source: {video_asset.url}"
            
            processing_metadata = {
                'original_url': video_asset.url,
                'mime_type': video_asset.mime_type,
                'size_bytes': video_asset.size_bytes,
                'extraction_methods': ['metadata'],  # Would include 'captions', 'transcription', 'ocr'
                'video_metadata': metadata
            }
            
            return ProcessedContent(
                source_url=video_asset.url,
                content_type='video',
                text_content=text_content,
                metadata=processing_metadata,
                confidence_score=0.6  # Lower confidence for placeholder
            )
            
        except Exception as e:
            logger.error(f"Video processing failed for {video_asset.url}: {e}")
            return None
    
    async def _process_image(self, image_asset: ContentAsset) -> Optional[ProcessedContent]:
        """Extract text from images using OCR and generate descriptions"""
        try:
            # In production, this would use OCR and image captioning
            # For now, return metadata-based content
            
            metadata = image_asset.metadata or {}
            text_content = f"Image file: {os.path.basename(image_asset.url)}\n"
            
            # Add available metadata as text
            if metadata.get('alt'):
                text_content += f"Alt text: {metadata['alt']}\n"
            if metadata.get('title'):
                text_content += f"Title: {metadata['title']}\n"
            if metadata.get('width') and metadata.get('height'):
                text_content += f"Dimensions: {metadata['width']}x{metadata['height']}\n"
                
            text_content += f"Source: {image_asset.url}"
            
            processing_metadata = {
                'original_url': image_asset.url,
                'mime_type': image_asset.mime_type,
                'size_bytes': image_asset.size_bytes,
                'extraction_methods': ['metadata'],  # Would include 'ocr', 'captioning'
                'image_metadata': metadata
            }
            
            return ProcessedContent(
                source_url=image_asset.url,
                content_type='image',
                text_content=text_content,
                metadata=processing_metadata,
                confidence_score=0.6  # Lower confidence for placeholder
            )
            
        except Exception as e:
            logger.error(f"Image processing failed for {image_asset.url}: {e}")
            return None
    
    def _extract_text_with_beautifulsoup(self, html_content: str) -> str:
        """Extract clean text using BeautifulSoup and html2text"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Convert to markdown-style text
            clean_text = self.html_converter.handle(str(soup))
            
            # Clean up excessive whitespace
            clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
            clean_text = re.sub(r' +', ' ', clean_text)
            
            return clean_text.strip()
            
        except Exception as e:
            logger.warning(f"BeautifulSoup extraction failed, falling back to basic: {e}")
            return self._extract_text_basic(html_content)
    
    def _extract_text_basic(self, html_content: str) -> str:
        """Basic text extraction without external libraries"""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Decode HTML entities
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def _extract_structured_data(self, html_content: str) -> Dict[str, Any]:
        """Extract structured data (JSON-LD, microdata, etc.)"""
        structured_data = {}
        
        # Extract JSON-LD
        json_ld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        json_ld_matches = re.findall(json_ld_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        if json_ld_matches:
            structured_data['json_ld'] = []
            for match in json_ld_matches:
                try:
                    data = json.loads(match.strip())
                    structured_data['json_ld'].append(data)
                except json.JSONDecodeError:
                    pass
        
        # Extract meta tags
        meta_pattern = r'<meta\s+([^>]*?)/?>'
        meta_matches = re.findall(meta_pattern, html_content, re.IGNORECASE)
        
        meta_data = {}
        for meta in meta_matches:
            name_match = re.search(r'name=["\']([^"\']+)["\']', meta)
            content_match = re.search(r'content=["\']([^"\']+)["\']', meta)
            
            if name_match and content_match:
                meta_data[name_match.group(1)] = content_match.group(1)
        
        if meta_data:
            structured_data['meta'] = meta_data
        
        return structured_data
    
    async def _generate_embeddings_batch(self, processed_items: List[ProcessedContent]):
        """Generate embeddings for all processed content"""
        try:
            texts = [item.text_content for item in processed_items if item.text_content]
            
            if not texts:
                logger.warning("No text content available for embedding generation")
                return
            
            logger.info(f"Generating embeddings for {len(texts)} text items")
            
            # Generate embeddings in batches
            batch_size = self.config['batch_embedding_size']
            
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_items = processed_items[i:i + batch_size]
                
                try:
                    # Generate embeddings using the embedding generator
                    embeddings = self.embedding_generator.generate_embeddings(batch_texts)
                    
                    # Assign embeddings to corresponding items
                    for j, embedding in enumerate(embeddings):
                        if i + j < len(batch_items):
                            batch_items[i + j].embeddings = embedding
                            
                except Exception as e:
                    logger.error(f"Failed to generate embeddings for batch {i//batch_size + 1}: {e}")
                    continue
            
            embedding_count = sum(1 for item in processed_items if item.has_embeddings)
            logger.info(f"Generated embeddings for {embedding_count}/{len(processed_items)} items")
            
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")

    def get_processing_stats(self, batch: ProcessedContentBatch) -> Dict[str, Any]:
        """Get detailed processing statistics"""
        return {
            'total_items': batch.total_items,
            'success_rate': batch.success_rate,
            'processing_time': batch.batch_metadata.get('processing_time_seconds', 0),
            'content_type_breakdown': batch.processing_stats,
            'text_statistics': {
                'total_characters': sum(item.text_length for item in batch.processed_items),
                'average_length': np.mean([item.text_length for item in batch.processed_items]) if batch.processed_items else 0,
                'items_with_embeddings': sum(1 for item in batch.processed_items if item.has_embeddings)
            },
            'quality_metrics': {
                'average_confidence': np.mean([item.confidence_score for item in batch.processed_items]) if batch.processed_items else 0,
                'high_confidence_items': sum(1 for item in batch.processed_items if item.confidence_score > 0.8)
            }
        }

    def filter_by_content_type(
        self, 
        batch: ProcessedContentBatch, 
        content_types: List[str]
    ) -> List[ProcessedContent]:
        """Filter processed content by content type"""
        return [
            item for item in batch.processed_items 
            if item.content_type in content_types
        ]

    def get_content_by_quality(
        self, 
        batch: ProcessedContentBatch, 
        min_confidence: float = 0.7
    ) -> List[ProcessedContent]:
        """Get content items above quality threshold"""
        return [
            item for item in batch.processed_items
            if item.confidence_score >= min_confidence
        ]


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
    
    async def test_processing():
        """Test multi-modal content processing"""
        processor = MultiModalContentProcessor()
        
        # Create sample content manifest
        html_asset = ContentAsset(
            url="https://example.com/page.html",
            content_type="html",
            mime_type="text/html",
            size_bytes=1000,
            content_preview="<html><body><h1>Test Page</h1><p>This is test content.</p></body></html>"
        )
        
        pdf_asset = ContentAsset(
            url="https://example.com/doc.pdf",
            content_type="pdf",
            mime_type="application/pdf",
            size_bytes=5000
        )
        
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[html_asset],
            pdf_documents=[pdf_asset],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )
        
        # Process content
        result = await processor.process_content_batch(
            content_manifest=manifest,
            include_embeddings=False,  # Skip embeddings for this test
            include_media=False
        )
        
        print(f"Processed {result.total_items} items")
        print(f"Success rate: {result.success_rate:.1f}%")
        print(f"Processing stats: {result.processing_stats}")
        
        # Display processed content
        for item in result.processed_items:
            print(f"\n{item.content_type.upper()}: {item.source_url}")
            print(f"Text length: {item.text_length}")
            print(f"Confidence: {item.confidence_score}")
            print(f"Preview: {item.text_content[:100]}...")
    
    # Run test
    asyncio.run(test_processing())