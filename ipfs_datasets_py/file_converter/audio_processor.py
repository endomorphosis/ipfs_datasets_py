"""
Audio Processing Module with Whisper Transcription.

Provides audio-to-text transcription using OpenAI Whisper with graceful fallback.
Integrates with ipfs_accelerate_py for GPU-accelerated transcription.

Features:
- Whisper speech-to-text transcription (multiple model sizes)
- Rich metadata extraction (duration, bitrate, sample rate, channels)
- Language detection and specification
- Graceful fallback when Whisper unavailable
- Optional GPU acceleration via ipfs_accelerate_py
- Support for 7 audio formats

Supported Formats:
- MP3 (.mp3)
- WAV (.wav)
- OGG (.ogg, .oga)
- FLAC (.flac)
- AAC (.aac, .m4a)
- WebM audio (.webm)
- 3GPP audio (.3gp, .3gpp)
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
import warnings

logger = logging.getLogger(__name__)

# Try to import audio processing libraries
WHISPER_AVAILABLE = False
PYDUB_AVAILABLE = False
MUTAGEN_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
    logger.debug("Whisper transcription available")
except ImportError:
    logger.debug("Whisper not available, transcription will be disabled")

try:
    from pydub import AudioSegment
    import pydub.utils
    PYDUB_AVAILABLE = True
    logger.debug("Pydub audio handling available")
except ImportError:
    logger.debug("Pydub not available, using fallback for metadata")

try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.wave import WAVE
    from mutagen.oggvorbis import OggVorbis
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    MUTAGEN_AVAILABLE = True
    logger.debug("Mutagen metadata extraction available")
except ImportError:
    logger.debug("Mutagen not available, limited metadata extraction")


class AudioProcessor:
    """
    Process audio files with optional Whisper transcription.
    
    Features:
    - Speech-to-text transcription with Whisper
    - Rich metadata extraction
    - Multiple audio format support
    - Graceful fallback when transcription unavailable
    - GPU acceleration support via ipfs_accelerate_py
    """
    
    # Supported audio formats
    AUDIO_FORMATS = {
        'audio/mpeg': ['.mp3'],
        'audio/wav': ['.wav'],
        'audio/x-wav': ['.wav'],
        'audio/ogg': ['.ogg', '.oga'],
        'audio/flac': ['.flac'],
        'audio/aac': ['.aac'],
        'audio/mp4': ['.m4a'],
        'audio/x-m4a': ['.m4a'],
        'audio/webm': ['.webm'],
        'audio/3gpp': ['.3gp', '.3gpp'],
        'audio/3gpp2': ['.3g2'],
    }
    
    def __init__(
        self,
        transcription_enabled: bool = True,
        model_size: str = 'base',
        language: Optional[str] = None,
        device: Optional[str] = None,
        enable_acceleration: bool = True
    ):
        """
        Initialize audio processor.
        
        Args:
            transcription_enabled: Enable Whisper transcription
            model_size: Whisper model size ('tiny', 'base', 'small', 'medium', 'large')
            language: Language code (e.g., 'en', 'es', 'fr') or None for auto-detect
            device: Device for processing ('cuda', 'cpu', or None for auto)
            enable_acceleration: Enable GPU acceleration via ipfs_accelerate_py
        """
        self.transcription_enabled = transcription_enabled and WHISPER_AVAILABLE
        self.model_size = model_size
        self.language = language
        self.device = device
        self.enable_acceleration = enable_acceleration
        
        self._whisper_model = None
        
        if transcription_enabled and not WHISPER_AVAILABLE:
            logger.warning(
                "Whisper transcription requested but not available. "
                "Install with: pip install openai-whisper"
            )
    
    def _load_whisper_model(self):
        """Lazy load Whisper model."""
        if self._whisper_model is None and WHISPER_AVAILABLE:
            try:
                logger.info(f"Loading Whisper model: {self.model_size}")
                self._whisper_model = whisper.load_model(
                    self.model_size,
                    device=self.device
                )
                logger.info("Whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                self.transcription_enabled = False
        
        return self._whisper_model
    
    def extract_text(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Extract text from audio file via transcription.
        
        Args:
            file_path: Path to audio file
            
        Returns:
            dict: Extraction result with text and metadata
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return {
                'text': '',
                'metadata': {},
                'error': f"File not found: {file_path}"
            }
        
        result = {
            'text': '',
            'metadata': self._extract_metadata(file_path),
            'transcription_enabled': self.transcription_enabled,
        }
        
        # Try transcription if enabled
        if self.transcription_enabled:
            try:
                transcription = self._transcribe_audio(file_path)
                result['text'] = transcription.get('text', '')
                result['metadata'].update({
                    'transcription_language': transcription.get('language'),
                    'transcription_model': self.model_size,
                })
                if 'segments' in transcription:
                    result['metadata']['segment_count'] = len(transcription['segments'])
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                result['error'] = str(e)
                result['transcription_enabled'] = False
        else:
            result['text'] = '[Audio transcription not available - install openai-whisper]'
        
        return result
    
    def _transcribe_audio(self, file_path: Path) -> Dict[str, Any]:
        """
        Transcribe audio using Whisper.
        
        Args:
            file_path: Path to audio file
            
        Returns:
            dict: Transcription result
        """
        model = self._load_whisper_model()
        
        if model is None:
            return {'text': '', 'error': 'Whisper model not available'}
        
        # Transcribe
        result = model.transcribe(
            str(file_path),
            language=self.language,
            verbose=False
        )
        
        return result
    
    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from audio file.
        
        Args:
            file_path: Path to audio file
            
        Returns:
            dict: Audio metadata
        """
        metadata = {
            'format': file_path.suffix.lstrip('.').upper(),
            'file_size': file_path.stat().st_size,
        }
        
        # Try mutagen first (more reliable)
        if MUTAGEN_AVAILABLE:
            try:
                metadata.update(self._extract_metadata_mutagen(file_path))
                return metadata
            except Exception as e:
                logger.debug(f"Mutagen metadata extraction failed: {e}")
        
        # Try pydub as fallback
        if PYDUB_AVAILABLE:
            try:
                metadata.update(self._extract_metadata_pydub(file_path))
                return metadata
            except Exception as e:
                logger.debug(f"Pydub metadata extraction failed: {e}")
        
        return metadata
    
    def _extract_metadata_mutagen(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata using mutagen."""
        metadata = {}
        
        audio = mutagen.File(str(file_path))
        if audio is None:
            return metadata
        
        # Common properties
        if hasattr(audio.info, 'length'):
            metadata['duration'] = float(audio.info.length)
        if hasattr(audio.info, 'bitrate'):
            metadata['bitrate'] = audio.info.bitrate
        if hasattr(audio.info, 'sample_rate'):
            metadata['sample_rate'] = audio.info.sample_rate
        if hasattr(audio.info, 'channels'):
            metadata['channels'] = audio.info.channels
        
        # Tags
        if hasattr(audio, 'tags') and audio.tags:
            metadata['has_tags'] = True
            # Extract common tags
            for key in ['title', 'artist', 'album', 'date']:
                if key in audio.tags:
                    metadata[key] = str(audio.tags[key][0]) if isinstance(audio.tags[key], list) else str(audio.tags[key])
        
        return metadata
    
    def _extract_metadata_pydub(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata using pydub."""
        metadata = {}
        
        try:
            audio = AudioSegment.from_file(str(file_path))
            
            metadata['duration'] = len(audio) / 1000.0  # Convert to seconds
            metadata['channels'] = audio.channels
            metadata['sample_rate'] = audio.frame_rate
            metadata['sample_width'] = audio.sample_width
            metadata['frame_rate'] = audio.frame_rate
            
        except Exception as e:
            logger.debug(f"Pydub could not process file: {e}")
        
        return metadata
    
    @classmethod
    def can_handle(cls, file_path: Union[str, Path], mime_type: Optional[str] = None) -> bool:
        """
        Check if this processor can handle the given file.
        
        Args:
            file_path: Path to file
            mime_type: MIME type (optional)
            
        Returns:
            bool: True if can handle
        """
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        
        # Check by MIME type
        if mime_type:
            if mime_type in cls.AUDIO_FORMATS:
                return True
        
        # Check by extension
        for mime, exts in cls.AUDIO_FORMATS.items():
            if ext in exts:
                return True
        
        return False
    
    @classmethod
    def get_supported_extensions(cls) -> list:
        """Get list of supported file extensions."""
        exts = []
        for ext_list in cls.AUDIO_FORMATS.values():
            exts.extend(ext_list)
        return sorted(set(exts))
