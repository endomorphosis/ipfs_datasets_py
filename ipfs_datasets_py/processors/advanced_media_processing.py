#!/usr/bin/env python3
"""
Advanced Media Processing for GraphRAG Systems

This module provides comprehensive audio and video processing capabilities
for the GraphRAG website processing system, including:
- Audio transcription with multiple engine support (Whisper, speech_recognition)
- Video processing and frame extraction
- Subtitle/closed captions extraction
- Audio content analysis and summarization
- Metadata extraction from media files
"""

import os
import json
import tempfile
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid

# Optional imports for media processing
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except ImportError:
    HAS_SPEECH_RECOGNITION = False

try:
    import subprocess
    import ffmpeg
    HAS_FFMPEG = True
except ImportError:
    HAS_FFMPEG = False

try:
    import cv2
    HAS_OPENCV = True  
except ImportError:
    HAS_OPENCV = False

logger = logging.getLogger(__name__)


@dataclass
class MediaProcessingConfig:
    """Configuration for media processing"""
    
    # Audio processing
    audio_transcription_engine: str = "whisper"  # whisper, speech_recognition, hybrid
    whisper_model: str = "base"  # tiny, base, small, medium, large
    audio_chunk_duration: int = 30  # seconds
    transcription_language: str = "auto"
    
    # Video processing
    frame_extraction_interval: int = 5  # seconds between frames
    max_frames_per_video: int = 100
    video_summary_enabled: bool = True
    
    # Quality settings
    audio_quality_threshold: float = 0.7
    transcription_confidence_threshold: float = 0.6
    
    # Performance
    max_concurrent_processing: int = 4
    processing_timeout: int = 300  # seconds
    

@dataclass
class TranscriptionResult:
    """Result of audio/video transcription"""
    
    text: str = ""
    segments: List[Dict[str, Any]] = field(default_factory=list)
    language: str = "unknown"
    confidence: float = 0.0
    duration: float = 0.0
    word_count: int = 0
    processing_time: float = 0.0
    engine_used: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass  
class MediaAnalysisResult:
    """Complete media analysis result"""
    
    media_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    media_type: str = "unknown"  # audio, video
    file_path: str = ""
    original_url: str = ""
    
    # Content
    transcription: TranscriptionResult = field(default_factory=TranscriptionResult)
    extracted_frames: List[str] = field(default_factory=list)  # frame file paths
    subtitles: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    duration: float = 0.0
    file_size: int = 0
    format_info: Dict[str, Any] = field(default_factory=dict)
    technical_metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Analysis
    content_summary: str = ""
    key_topics: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    processing_time: float = 0.0
    
    # Status
    processing_status: str = "pending"  # pending, processing, completed, failed
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


class AdvancedMediaProcessor:
    """Advanced media processing for audio and video content"""
    
    def __init__(self, config: Optional[MediaProcessingConfig] = None):
        self.config = config or MediaProcessingConfig()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Initialize transcription engines
        self._whisper_model = None
        self._speech_recognizer = None
        self._initialize_engines()
        
    def _initialize_engines(self):
        """Initialize available transcription engines"""
        
        # Initialize Whisper if available
        if HAS_WHISPER and self.config.audio_transcription_engine in ["whisper", "hybrid"]:
            try:
                self._whisper_model = whisper.load_model(self.config.whisper_model)
                self.logger.info(f"Whisper model '{self.config.whisper_model}' loaded successfully")
            except Exception as e:
                self.logger.warning(f"Failed to load Whisper model: {e}")
                
        # Initialize speech_recognition if available
        if HAS_SPEECH_RECOGNITION and self.config.audio_transcription_engine in ["speech_recognition", "hybrid"]:
            try:
                self._speech_recognizer = sr.Recognizer()
                self.logger.info("Speech recognition engine initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize speech recognition: {e}")
    
    async def process_media_file(
        self,
        file_path: str,
        original_url: str = "",
        media_type: Optional[str] = None
    ) -> MediaAnalysisResult:
        """Process a single media file (audio or video)"""
        
        start_time = datetime.now()
        result = MediaAnalysisResult(
            file_path=file_path,
            original_url=original_url,
            processing_status="processing"
        )
        
        try:
            # Determine media type if not provided
            if not media_type:
                media_type = self._detect_media_type(file_path)
            result.media_type = media_type
            
            # Extract basic metadata
            result.technical_metadata = self._extract_media_metadata(file_path)
            result.duration = result.technical_metadata.get("duration", 0.0)
            result.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            
            # Process based on media type
            if media_type == "audio":
                result.transcription = await self._transcribe_audio(file_path)
            elif media_type == "video":
                result.transcription = await self._transcribe_video(file_path)
                result.extracted_frames = await self._extract_video_frames(file_path)
                result.subtitles = await self._extract_subtitles(file_path)
            
            # Generate content analysis
            if result.transcription.text:
                result.content_summary = self._generate_content_summary(result.transcription.text)
                result.key_topics = self._extract_key_topics(result.transcription.text)
                
            # Calculate quality score
            result.quality_score = self._calculate_quality_score(result)
            
            result.processing_status = "completed"
            
        except Exception as e:
            self.logger.error(f"Error processing media file {file_path}: {e}")
            result.processing_status = "failed"
            result.error_message = str(e)
        
        result.processing_time = (datetime.now() - start_time).total_seconds()
        return result
    
    async def _transcribe_audio(self, file_path: str) -> TranscriptionResult:
        """Transcribe audio using the configured engine"""
        
        result = TranscriptionResult()
        start_time = datetime.now()
        
        try:
            if self.config.audio_transcription_engine == "whisper" and self._whisper_model:
                result = await self._transcribe_with_whisper(file_path)
            elif self.config.audio_transcription_engine == "speech_recognition" and self._speech_recognizer:
                result = await self._transcribe_with_speech_recognition(file_path)
            elif self.config.audio_transcription_engine == "hybrid":
                # Try Whisper first, fallback to speech_recognition
                if self._whisper_model:
                    result = await self._transcribe_with_whisper(file_path)
                elif self._speech_recognizer:
                    result = await self._transcribe_with_speech_recognition(file_path)
            else:
                # Fallback to basic processing
                result.text = f"[Audio content from {file_path} - transcription not available]"
                result.engine_used = "fallback"
                
        except Exception as e:
            self.logger.error(f"Audio transcription failed: {e}")
            result.text = f"[Audio transcription failed: {str(e)}]"
            result.engine_used = "error"
            
        result.processing_time = (datetime.now() - start_time).total_seconds()
        result.word_count = len(result.text.split()) if result.text else 0
        
        return result
    
    async def _transcribe_with_whisper(self, file_path: str) -> TranscriptionResult:
        """Transcribe using OpenAI Whisper"""
        
        if not self._whisper_model:
            raise RuntimeError("Whisper model not initialized")
            
        result = TranscriptionResult()
        
        try:
            # Transcribe with Whisper
            whisper_result = self._whisper_model.transcribe(
                file_path,
                language=None if self.config.transcription_language == "auto" else self.config.transcription_language
            )
            
            result.text = whisper_result["text"].strip()
            result.language = whisper_result.get("language", "unknown")
            result.segments = whisper_result.get("segments", [])
            result.engine_used = "whisper"
            
            # Calculate average confidence from segments
            if result.segments:
                confidences = [seg.get("avg_logprob", 0.0) for seg in result.segments]
                result.confidence = sum(confidences) / len(confidences) if confidences else 0.0
            else:
                result.confidence = 0.8  # Default confidence for Whisper
                
        except Exception as e:
            raise RuntimeError(f"Whisper transcription failed: {e}")
            
        return result
    
    async def _transcribe_with_speech_recognition(self, file_path: str) -> TranscriptionResult:
        """Transcribe using speech_recognition library"""
        
        if not self._speech_recognizer:
            raise RuntimeError("Speech recognizer not initialized")
            
        result = TranscriptionResult()
        
        try:
            # Convert to WAV if needed and process
            with sr.AudioFile(file_path) as source:
                audio = self._speech_recognizer.record(source)
                
            # Try Google Web Speech API (free)
            try:
                text = self._speech_recognizer.recognize_google(audio)
                result.text = text
                result.confidence = 0.7  # Default confidence for Google API
                result.engine_used = "google_web_speech"
            except sr.UnknownValueError:
                result.text = "[Speech not recognized]"
                result.confidence = 0.0
                result.engine_used = "google_web_speech_failed"
            except sr.RequestError as e:
                raise RuntimeError(f"Google Web Speech API error: {e}")
                
        except Exception as e:
            raise RuntimeError(f"Speech recognition failed: {e}")
            
        return result
    
    async def _transcribe_video(self, file_path: str) -> TranscriptionResult:
        """Extract and transcribe audio from video"""
        
        if not HAS_FFMPEG:
            return TranscriptionResult(
                text=f"[Video audio transcription not available - ffmpeg required]",
                engine_used="not_available"
            )
        
        try:
            # Extract audio to temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
                tmp_audio_path = tmp_audio.name
                
            # Use ffmpeg to extract audio
            try:
                (
                    ffmpeg
                    .input(file_path)
                    .output(tmp_audio_path, acodec='pcm_s16le', ac=1, ar=16000)
                    .overwrite_output()
                    .run(quiet=True)
                )
                
                # Transcribe the extracted audio
                result = await self._transcribe_audio(tmp_audio_path)
                
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_audio_path):
                    os.unlink(tmp_audio_path)
                    
            return result
            
        except Exception as e:
            self.logger.error(f"Video transcription failed: {e}")
            return TranscriptionResult(
                text=f"[Video transcription failed: {str(e)}]",
                engine_used="error"
            )
    
    async def _extract_video_frames(self, file_path: str) -> List[str]:
        """Extract representative frames from video"""
        
        if not HAS_OPENCV:
            self.logger.warning("OpenCV not available for frame extraction")
            return []
            
        frames = []
        
        try:
            cap = cv2.VideoCapture(file_path)
            
            if not cap.isOpened():
                self.logger.error(f"Could not open video file: {file_path}")
                return frames
                
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            # Calculate frame extraction interval
            frame_interval = int(fps * self.config.frame_extraction_interval) if fps > 0 else 30
            max_frames = min(self.config.max_frames_per_video, int(duration / self.config.frame_extraction_interval))
            
            frame_count = 0
            extracted = 0
            
            while extracted < max_frames:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                if frame_count % frame_interval == 0:
                    # Save frame to temporary file
                    frame_filename = f"frame_{extracted:04d}_{int(frame_count/fps)}s.jpg"
                    frame_path = os.path.join(tempfile.gettempdir(), frame_filename)
                    
                    if cv2.imwrite(frame_path, frame):
                        frames.append(frame_path)
                        extracted += 1
                        
                frame_count += 1
                
            cap.release()
            
        except Exception as e:
            self.logger.error(f"Frame extraction failed: {e}")
            
        return frames
    
    async def _extract_subtitles(self, file_path: str) -> List[Dict[str, Any]]:
        """Extract subtitles/captions from video if available"""
        
        subtitles = []
        
        if not HAS_FFMPEG:
            return subtitles
            
        try:
            # Try to extract subtitles using ffmpeg
            probe_result = ffmpeg.probe(file_path)
            
            for stream in probe_result.get("streams", []):
                if stream.get("codec_type") == "subtitle":
                    subtitle_info = {
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "language": stream.get("tags", {}).get("language", "unknown"),
                        "title": stream.get("tags", {}).get("title", "")
                    }
                    subtitles.append(subtitle_info)
                    
        except Exception as e:
            self.logger.error(f"Subtitle extraction failed: {e}")
            
        return subtitles
    
    def _detect_media_type(self, file_path: str) -> str:
        """Detect whether file is audio or video"""
        
        file_ext = Path(file_path).suffix.lower()
        
        audio_extensions = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma"}
        video_extensions = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv"}
        
        if file_ext in audio_extensions:
            return "audio"
        elif file_ext in video_extensions:
            return "video"
        else:
            # Try to determine using metadata if ffmpeg available
            if HAS_FFMPEG:
                try:
                    probe_result = ffmpeg.probe(file_path)
                    for stream in probe_result.get("streams", []):
                        codec_type = stream.get("codec_type")
                        if codec_type == "video":
                            return "video"
                        elif codec_type == "audio":
                            return "audio"
                except:
                    pass
                    
            return "unknown"
    
    def _extract_media_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract technical metadata from media file"""
        
        metadata = {}
        
        if HAS_FFMPEG:
            try:
                probe_result = ffmpeg.probe(file_path)
                
                # General file info
                format_info = probe_result.get("format", {})
                metadata.update({
                    "duration": float(format_info.get("duration", 0)),
                    "size": int(format_info.get("size", 0)),
                    "bit_rate": int(format_info.get("bit_rate", 0)),
                    "format_name": format_info.get("format_name", ""),
                    "format_long_name": format_info.get("format_long_name", "")
                })
                
                # Stream info
                streams = []
                for stream in probe_result.get("streams", []):
                    stream_info = {
                        "index": stream.get("index"),
                        "codec_type": stream.get("codec_type"),
                        "codec_name": stream.get("codec_name"),
                        "duration": float(stream.get("duration", 0))
                    }
                    
                    if stream.get("codec_type") == "video":
                        stream_info.update({
                            "width": stream.get("width"),
                            "height": stream.get("height"),
                            "fps": eval(stream.get("r_frame_rate", "0/1")) if stream.get("r_frame_rate") else 0
                        })
                    elif stream.get("codec_type") == "audio":
                        stream_info.update({
                            "sample_rate": stream.get("sample_rate"),
                            "channels": stream.get("channels"),
                            "channel_layout": stream.get("channel_layout")
                        })
                        
                    streams.append(stream_info)
                    
                metadata["streams"] = streams
                
            except Exception as e:
                self.logger.error(f"Metadata extraction failed: {e}")
                metadata["error"] = str(e)
        
        return metadata
    
    def _generate_content_summary(self, text: str) -> str:
        """Generate a summary of the transcribed content"""
        
        if not text or len(text) < 100:
            return text
            
        # Simple extractive summary - take first and key sentences
        sentences = text.split(". ")
        if len(sentences) <= 3:
            return text
            
        # Take first sentence and a few key sentences
        summary_sentences = [sentences[0]]
        
        # Look for sentences with key indicators
        key_indicators = ["important", "key", "main", "conclusion", "result", "finding"]
        for sentence in sentences[1:]:
            if any(indicator in sentence.lower() for indicator in key_indicators):
                summary_sentences.append(sentence)
                if len(summary_sentences) >= 3:
                    break
        
        # If we don't have enough, add more sentences
        while len(summary_sentences) < 3 and len(summary_sentences) < len(sentences):
            summary_sentences.append(sentences[len(summary_sentences)])
            
        return ". ".join(summary_sentences) + "."
    
    def _extract_key_topics(self, text: str) -> List[str]:
        """Extract key topics from transcribed text"""
        
        if not text:
            return []
            
        # Simple keyword extraction - look for repeated important terms
        import re
        from collections import Counter
        
        # Remove common stop words and extract meaningful terms
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might"}
        
        # Extract words (basic approach)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        words = [word for word in words if word not in stop_words]
        
        # Count frequency
        word_counts = Counter(words)
        
        # Return top keywords
        return [word for word, count in word_counts.most_common(10) if count >= 2]
    
    def _calculate_quality_score(self, result: MediaAnalysisResult) -> float:
        """Calculate quality score for processed media"""
        
        score = 0.0
        factors = []
        
        # Transcription quality
        if result.transcription.text:
            text_length = len(result.transcription.text)
            if text_length > 100:
                factors.append(0.4)  # Good transcription length
            elif text_length > 20:
                factors.append(0.2)  # Minimal transcription
                
            if result.transcription.confidence > self.config.transcription_confidence_threshold:
                factors.append(0.3)  # High confidence
                
        # Duration appropriateness
        if result.duration > 0:
            if 10 <= result.duration <= 3600:  # 10 seconds to 1 hour
                factors.append(0.2)
            elif result.duration > 3600:  # Very long content
                factors.append(0.1)
                
        # Processing success
        if result.processing_status == "completed":
            factors.append(0.1)
            
        return sum(factors)


# Factory function for easy integration
def create_advanced_media_processor(config: Optional[MediaProcessingConfig] = None) -> AdvancedMediaProcessor:
    """Create an AdvancedMediaProcessor with the given configuration"""
    return AdvancedMediaProcessor(config)


# Configuration presets
MEDIA_PROCESSING_PRESETS = {
    "fast": MediaProcessingConfig(
        whisper_model="tiny",
        frame_extraction_interval=10,
        max_frames_per_video=20,
        transcription_confidence_threshold=0.5
    ),
    "balanced": MediaProcessingConfig(
        whisper_model="base",
        frame_extraction_interval=5,
        max_frames_per_video=50,
        transcription_confidence_threshold=0.6
    ),
    "quality": MediaProcessingConfig(
        whisper_model="small",
        frame_extraction_interval=2,
        max_frames_per_video=100,
        transcription_confidence_threshold=0.7
    )
}


if __name__ == "__main__":
    # Simple test
    import anyio
    
    async def test_media_processor():
        """Test the media processor with a sample file"""
        
        processor = AdvancedMediaProcessor()
        print("🎬 Advanced Media Processor Test")
        print("=" * 50)
        
        # Test with a hypothetical media file
        test_file = "/path/to/test/audio.wav"
        if os.path.exists(test_file):
            result = await processor.process_media_file(test_file)
            print(f"📊 Processing Result:")
            print(f"   • Status: {result.processing_status}")
            print(f"   • Duration: {result.duration:.2f}s")
            print(f"   • Transcription: {result.transcription.text[:100]}...")
            print(f"   • Quality Score: {result.quality_score:.2f}")
        else:
            print("ℹ️  No test media file available")
            print("   Media processor initialized successfully")
            print(f"   Whisper available: {HAS_WHISPER}")
            print(f"   Speech Recognition available: {HAS_SPEECH_RECOGNITION}")
            print(f"   FFmpeg available: {HAS_FFMPEG}")
            print(f"   OpenCV available: {HAS_OPENCV}")
        
    anyio.run(test_media_processor())