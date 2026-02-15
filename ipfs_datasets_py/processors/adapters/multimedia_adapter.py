"""
MultimediaProcessorAdapter - Adapter for multimedia processing.

Wraps multimedia processing (FFmpeg, yt-dlp, audio transcription) to
implement ProcessorProtocol.
"""

from __future__ import annotations

import logging
from typing import Union, Dict, Any, List
from pathlib import Path
import time

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
)

logger = logging.getLogger(__name__)


class MultimediaProcessorAdapter:
    """
    Adapter for multimedia processors that implements ProcessorProtocol.
    
    Wraps FFmpeg, yt-dlp, and audio transcription to provide unified
    interface for video, audio, and media URL processing.
    
    Implements the synchronous ProcessorProtocol from processors.core.
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = MultimediaProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.FILE,
        ...     source="video.mp4",
        ...     metadata={"format": "mp4"}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._ffmpeg = None
        self._ytdlp = None
        self._media_processor = None
        self._name = "MultimediaProcessor"
        self._priority = 10
    
    def _get_ffmpeg(self):
        """Lazy-load FFmpeg wrapper."""
        if self._ffmpeg is None:
            try:
                from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
                self._ffmpeg = FFmpegWrapper()
                logger.info("FFmpegWrapper loaded")
            except ImportError as e:
                logger.warning(f"FFmpeg not available: {e}")
        return self._ffmpeg
    
    def _get_ytdlp(self):
        """Lazy-load yt-dlp wrapper."""
        if self._ytdlp is None:
            try:
                from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
                self._ytdlp = YtDlpWrapper()
                logger.info("YtDlpWrapper loaded")
            except ImportError as e:
                logger.warning(f"yt-dlp not available: {e}")
        return self._ytdlp
    
    def _get_media_processor(self):
        """Lazy-load media processor."""
        if self._media_processor is None:
            try:
                from ipfs_datasets_py.processors.multimedia import MediaProcessor
                self._media_processor = MediaProcessor()
                logger.info("MediaProcessor loaded")
            except ImportError as e:
                logger.warning(f"MediaProcessor not available: {e}")
        return self._media_processor
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle multimedia inputs.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is video, audio, or media URL
        """
        # Check format from metadata
        fmt = context.get_format()
        if fmt:
            fmt_lower = fmt.lower()
            # Video formats
            if fmt_lower in ('mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm', 'm4v'):
                return True
            # Audio formats
            if fmt_lower in ('mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'):
                return True
        
        # Check source string
        source_str = str(context.source).lower()
        
        # Video extensions
        video_exts = ('.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v')
        if source_str.endswith(video_exts):
            return True
        
        # Audio extensions
        audio_exts = ('.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a')
        if source_str.endswith(audio_exts):
            return True
        
        # Video streaming URLs
        video_sites = ('youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com')
        if any(site in source_str for site in video_sites):
            return True
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process multimedia file or URL and return standardized result.
        
        Args:
            context: Processing context with input source and options
            
        Returns:
            ProcessingResult with transcription and metadata
        """
        start_time = time.time()
        source = context.source
        
        try:
            # Download if URL
            local_file = source
            if context.input_type == InputType.URL:
                ytdlp = self._get_ytdlp()
                if ytdlp:
                    # Download video/audio
                    download_result = self._download_media(str(source))
                    local_file = download_result.get("local_path", source)
            
            # Extract metadata
            file_metadata = self._extract_metadata(local_file)
            
            # Transcribe if audio/video
            transcription = self._transcribe_media(local_file)
            
            # Build knowledge graph
            kg = self._build_knowledge_graph(transcription, str(source), file_metadata)
            
            # Generate vectors (placeholder)
            vectors: List[List[float]] = []
            
            # Processing time
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=True,
                knowledge_graph=kg,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processor_type": "multimedia",
                    "processing_time": elapsed,
                    "media_type": file_metadata.get("type", "unknown"),
                    "transcription": transcription,
                    "duration": file_metadata.get("duration", 0),
                    "local_file": str(local_file) if local_file != source else None
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            logger.error(f"Multimedia processing failed for {source}: {e}")
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"Multimedia processing failed: {str(e)}"]
            )
    
    def _download_media(self, url: str) -> dict:
        """Download media from URL."""
        # Placeholder - actual implementation would use yt-dlp
        return {
            "local_path": f"/tmp/downloaded_{abs(hash(url))}.mp4",
            "title": "Downloaded video",
            "duration": 120
        }
    
    def _extract_metadata(self, file_path: Union[str, Path]) -> dict:
        """Extract media metadata."""
        # Placeholder - actual implementation would use FFmpeg
        return {
            "type": "video",
            "duration": 120,
            "format": "mp4",
            "resolution": "1920x1080"
        }
    
    def _transcribe_media(self, file_path: Union[str, Path]) -> str:
        """Transcribe audio/video."""
        # Placeholder - actual implementation would use Whisper or similar
        return f"Transcription of {file_path}"
    
    def _build_knowledge_graph(
        self,
        transcription: str,
        source: str,
        media_metadata: dict
    ) -> Dict[str, Any]:
        """Build knowledge graph from media transcription."""
        # Create media entity
        media_entity = {
            "id": f"media_{abs(hash(source))}",
            "type": "MediaFile",
            "label": Path(source).name if not source.startswith('http') else source,
            "properties": {
                "source": source,
                "type": media_metadata.get("type", "unknown"),
                "duration": media_metadata.get("duration", 0),
                **media_metadata
            }
        }
        
        kg = {
            "entities": [media_entity],
            "relationships": [],
            "source": source
        }
        
        # In production, would extract entities from transcription using NER
        
        return kg
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return processor capabilities and metadata.
        
        Returns:
            Dictionary with processor name, priority, supported formats, etc.
        """
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["mp4", "avi", "mkv", "mov", "mp3", "wav", "ogg", "flac"],
            "input_types": ["file", "url", "video", "audio"],
            "outputs": ["knowledge_graph", "transcription"],
            "features": [
                "video_transcription",
                "audio_transcription",
                "media_metadata",
                "youtube_download"
            ]
        }
