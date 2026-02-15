"""
MultimediaProcessorAdapter - Adapter for multimedia processing.

Wraps multimedia processing (FFmpeg, yt-dlp, audio transcription) to
implement ProcessorProtocol.
"""

from __future__ import annotations

import logging
from typing import Union
from pathlib import Path
import time

from ..protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore,
    Entity,
    Relationship
)

logger = logging.getLogger(__name__)


class MultimediaProcessorAdapter:
    """
    Adapter for multimedia processors that implements ProcessorProtocol.
    
    Wraps FFmpeg, yt-dlp, and audio transcription to provide unified
    interface for video, audio, and media URL processing.
    
    Example:
        >>> adapter = MultimediaProcessorAdapter()
        >>> can_process = await adapter.can_process("video.mp4")
        >>> result = await adapter.process("video.mp4")
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._ffmpeg = None
        self._ytdlp = None
        self._media_processor = None
    
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
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle multimedia inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is video, audio, or media URL
        """
        input_str = str(input_source).lower()
        
        # Video extensions
        video_exts = ('.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v')
        if input_str.endswith(video_exts):
            return True
        
        # Audio extensions
        audio_exts = ('.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a')
        if input_str.endswith(audio_exts):
            return True
        
        # Video streaming URLs
        video_sites = ('youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com')
        if any(site in input_str for site in video_sites):
            return True
        
        return False
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process multimedia file or URL and return standardized result.
        
        Args:
            input_source: Video/audio file or URL
            **options: Processing options
            
        Returns:
            ProcessingResult with transcription and metadata
        """
        start_time = time.time()
        
        # Determine input type
        is_url = str(input_source).startswith(('http://', 'https://'))
        input_type = InputType.URL if is_url else InputType.FILE
        
        metadata = ProcessingMetadata(
            processor_name="MultimediaProcessor",
            processor_version="1.0",
            input_type=input_type
        )
        
        try:
            # Download if URL
            local_file = input_source
            if is_url:
                ytdlp = self._get_ytdlp()
                if ytdlp:
                    # Download video/audio
                    download_result = await self._download_media(str(input_source))
                    local_file = download_result.get("local_path", input_source)
                else:
                    metadata.add_warning("yt-dlp not available, cannot download")
            
            # Extract metadata
            file_metadata = await self._extract_metadata(local_file)
            
            # Transcribe if audio/video
            transcription = await self._transcribe_media(local_file)
            
            # Build knowledge graph
            kg = self._build_knowledge_graph(transcription, str(input_source), file_metadata)
            
            # Generate vectors (placeholder)
            vectors = VectorStore(
                metadata={
                    "model": "multimedia_processor",
                    "source": str(input_source)
                }
            )
            
            # Processing time
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.SUCCESS
            
            return ProcessingResult(
                knowledge_graph=kg,
                vectors=vectors,
                content={
                    "transcription": transcription,
                    "metadata": file_metadata,
                    "local_file": str(local_file) if local_file != input_source else None
                },
                metadata=metadata,
                extra={
                    "processor_type": "multimedia",
                    "media_type": file_metadata.get("type", "unknown")
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            logger.error(f"Multimedia processing failed for {input_source}: {e}")
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=str(input_source)),
                vectors=VectorStore(),
                content={"error": str(e)},
                metadata=metadata
            )
    
    async def _download_media(self, url: str) -> dict:
        """Download media from URL."""
        # Placeholder - actual implementation would use yt-dlp
        return {
            "local_path": f"/tmp/downloaded_{hash(url)}.mp4",
            "title": "Downloaded video",
            "duration": 120
        }
    
    async def _extract_metadata(self, file_path: Union[str, Path]) -> dict:
        """Extract media metadata."""
        # Placeholder - actual implementation would use FFmpeg
        return {
            "type": "video",
            "duration": 120,
            "format": "mp4",
            "resolution": "1920x1080"
        }
    
    async def _transcribe_media(self, file_path: Union[str, Path]) -> str:
        """Transcribe audio/video."""
        # Placeholder - actual implementation would use Whisper or similar
        return f"Transcription of {file_path}"
    
    def _build_knowledge_graph(
        self,
        transcription: str,
        source: str,
        media_metadata: dict
    ) -> KnowledgeGraph:
        """Build knowledge graph from media transcription."""
        kg = KnowledgeGraph(source=source)
        
        # Create media entity
        media_entity = Entity(
            id=f"media_{hash(source)}",
            type="MediaFile",
            label=Path(source).name if not source.startswith('http') else source,
            properties={
                "source": source,
                "type": media_metadata.get("type", "unknown"),
                "duration": media_metadata.get("duration", 0),
                **media_metadata
            }
        )
        kg.add_entity(media_entity)
        
        # In production, would extract entities from transcription using NER
        
        return kg
    
    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return ["video", "audio", "url", "media"]
    
    def get_priority(self) -> int:
        """Return processor priority."""
        return 10
    
    def get_name(self) -> str:
        """Return processor name."""
        return "MultimediaProcessor"
