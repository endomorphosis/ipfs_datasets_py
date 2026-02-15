# """
# Audio processor implementation using Whisper for speech-to-text.

# This module provides a concrete implementation of audio processing with
# speech-to-text capabilities.




# """
# from datetime import timedelta
# import os
# import tempfile
# from typing import Any, Tuple


# from deprecated.processors.base_processor import BaseProcessor # TODO 
# from logger import logger
# from configs import configs
# from utils.common.try_except_decorator import try_except


# try:
#     import whisper
#     import numpy as np
#     WHISPER_AVAILABLE = True
# except ImportError:
#     logger.warning("Whisper not available, speech-to-text functionality will not be available")
#     WHISPER_AVAILABLE = False

# try:
#     from pydub import AudioSegment
#     from pydub.utils import mediainfo
#     PYDUB_AVAILABLE = True
# except ImportError:
#     logger.warning("pydub not available, audio extraction will be limited")
#     PYDUB_AVAILABLE = False


# def _calc_spectral_centroid_using_fft(samples: np.ndarray, sample_rate: int) -> float:
#     """
#     TODO - Validate this function. LLM generated math code makes me nervous.
#     Calculate the spectral centroid of an audio signal using FFT.

#     Args:
#         samples: The audio samples as a numpy array.
#         sample_rate: The sample rate of the audio signal.
    
#     Returns:
#         The spectral centroid in Hz. TODO - Validate unit.
#     """
#     # Perform Fast Fourier Transform
#     n_samples = len(samples)
#     window = np.hamming(n_samples)  # Apply Hamming window to reduce spectral leakage
#     windowed_samples = samples * window
    
#     # Calculate FFT and get magnitudes
#     fft_result = np.abs(np.fft.rfft(windowed_samples))
#     frequencies = np.fft.rfftfreq(n_samples, 1.0/sample_rate)
    
#     # Calculate spectral centroid (weighted average of frequencies)
#     if np.sum(fft_result) > 0:
#         return np.sum(frequencies * fft_result) / np.sum(fft_result)
#     else:
#         return 0


# def _calc_spectral_centroid(samples: np.ndarray, sample_rate: int) -> float:
#     """
#     TODO - Validate this function.
    
#     """
#     np.sum( # Sum the absolute differences between consecutive samples
#         np.abs( # Calculate the absolute differences
#             np.diff(samples) # np.diff() calculates the difference between consecutive samples e.g. [1, 2, 72] -> [1, 70]
#         )) / (len(samples) - 1
#     ) * sample_rate


# @try_except(raise_=False, msg="Error in waveform analysis", default_return={"error": f"Waveform analysis failed"})
# def _analyze_waveform(audio: 'AudioSegment', sample_rate: int, duration: float) -> dict[str, Any]:
#     """
#     Analyze the waveform of an audio segment.
    
#     Args:
#         audio: The audio segment to analyze.
#         sample_rate: The sample rate of the audio.
#         duration: The duration of the audio in seconds.
        
#     Returns:
#         A dictionary containing waveform analysis results.
#     """
#     if not PYDUB_AVAILABLE:
#         return {"error": "pydub not available for waveform analysis"}

#     # Convert to numpy array for analysis
#     samples = np.array(audio.get_array_of_samples())
    
#     # If stereo, average the channels for simplicity
#     if audio.channels > 1:
#         samples = samples.reshape((-1, audio.channels)).mean(axis=1)

#     # Normalize to -1.0 to 1.0 range
#     max_value = 2**(audio.sample_width * 8 - 1) - 1
#     samples = samples / max_value
    
#     # Calculate some basic statistics
#     rms = np.sqrt(np.mean(samples**2)) # Root Mean Square
#     peak = np.max(np.abs(samples)) # Peak amplitude
    
#     # Calculate spectral centroid (rough estimate of "brightness")
#     if len(samples) > 0 and duration > 0:
#         spectral_centroid = _calc_spectral_centroid_using_fft(samples, sample_rate) if len(samples) > 0 else 0
#     else:
#         spectral_centroid = 0
    
#     # Create a reduced version for visualization
#     # Aim for about 1000 points max
#     points = min(1000, len(samples))
#     step = max(1, len(samples) // points)
#     visualization = samples[::step].tolist()[:points]
    
#     return {
#         "num_samples": len(samples),
#         "rms": float(rms),
#         "peak": float(peak),
#         "dynamic_range_db": float(20 * np.log10(peak / (rms + 1e-9))),
#         "spectral_centroid": float(spectral_centroid),
#         "visualization": {
#             "points": len(visualization),
#             "step": step,
#             "data": visualization
#         }
#     }


# class AudioProcessor:
#     """
#     Audio processor framework class.
    
#     This class provides functionality to extract metadata, waveform data, and
#     transcribe speech to text from audio files using the Whisper library.
#     """
    
#     def __init__(self, model_name: str = "base", resources=None, configs=None) -> None:
#         """
#         Initialize the Whisper audio processor.
        
#         Args:
#             model_name: The name of the Whisper model to use.
#                 Options include: "tiny", "base", "small", "medium", "large".
#                 Default is "base" which offers a good balance of accuracy and speed.
#         """
#         self._configs = configs
#         self.resources = resources

#         self._supported_formats = resources['supported_formats']
#         self._extract_metadata = resources['extract_metadata']
#         self.model = None

#         # Initialize the Whisper model if available
#         if WHISPER_AVAILABLE:
#             try:
#                 logger.info(f"Loading Whisper model: {model_name}")
#                 self.model = whisper.load_model(model_name)
#                 logger.info(f"Whisper model {model_name} loaded successfully")
#             except Exception as e:
#                 logger.error(f"Error loading Whisper model: {e}")
#                 self.model = None

#         if self.model is not None:
#             if not hasattr(self.model, "transcribe"):
#                 raise AttributeError(f"Whisper model {self.model_name} does not have a transcribe method")
    
#     def can_process(self, format_name: str) -> bool:
#         """
#         Check if this processor can handle the given format.
        
#         Args:
#             format_name: The name of the format to check.
            
#         Returns:
#             True if this processor can handle the format and required libraries are available,
#             False otherwise.
#         """
#         has_requirements = WHISPER_AVAILABLE and PYDUB_AVAILABLE
#         return has_requirements and format_name.lower() in self.supported_formats
    
#     @property
#     def supported_formats(self) -> list[str]:
#         """
#         Get the list of formats supported by this processor.
        
#         Returns:
#             A list of format names supported by this processor.
#         """
#         return self._supported_formats if WHISPER_AVAILABLE and PYDUB_AVAILABLE else []
    
#     def get_processor_info(self) -> dict[str, Any]:
#         """
#         Get information about this processor.
        
#         Returns:
#             A dictionary containing information about this processor.
#         """
#         info = {
#             "name": "AudioProcessor",
#             "supported_formats": self.supported_formats,
#             "whisper_available": WHISPER_AVAILABLE,
#             "pydub_available": PYDUB_AVAILABLE,
#             "model_name": self.model_name,
#             "model_loaded": self.model is not None
#         }
        
#         if WHISPER_AVAILABLE:
#             info["whisper_version"] = whisper.__version__
        
#         return info
    
#     def extract_metadata(self, data: bytes, format_name: str, options: dict[str, Any]) -> dict[str, Any]:
#         """
#         Extract metadata from an audio file.
        
#         Args:
#             data: The binary data of the audio file.
#             format_name: The format of the audio file.
#             options: Processing options.
            
#         Returns:
#             Metadata extracted from the audio file.
            
#         Raises:
#             ValueError: If pydub is not available or the data cannot be processed.
#         """
#         if not PYDUB_AVAILABLE:
#             raise ValueError("pydub is not available for audio metadata extraction")
        
#         try:
#             # Save audio data to a temporary file
#             with tempfile.NamedTemporaryFile(suffix=f'.{format_name}', delete=False) as temp_file:
#                 temp_file.write(data)
#                 temp_file_path = temp_file.name
            
#             try:
#                 # Get media info
#                 info = mediainfo(temp_file_path)
                
#                 # Load audio file to get additional properties
#                 audio = AudioSegment.from_file(temp_file_path, format=format_name)
                
#                 # Extract common properties
#                 duration_seconds = len(audio) / 1000.0
#                 # Calculate average loudness (dBFS)

#                 # Build metadata dictionary
#                 metadata = {
#                     'format': format_name,
#                     'duration_seconds': duration_seconds,
#                     'duration': str(timedelta(seconds=duration_seconds)),
#                     'channels': audio.channels,
#                     'sample_width_bytes': audio.sample_width,
#                     'frame_rate_hz': audio.frame_rate,
#                     'frame_width_bytes': audio.frame_width,
#                     'loudness_dbfs': audio.dBFS,
#                     'file_size_bytes': len(data)
#                 }

#                 # Add additional metadata from mediainfo
#                 if info:
#                     for key, value in info.items():
#                         if key not in metadata and value:
#                             metadata[key] = value
                
#                 # Extract tags if available
#                 if 'TAG' in info:
#                     for tag_key, tag_value in info['TAG'].items():
#                         if tag_value:
#                             metadata[f'tag_{tag_key}'] = tag_value
                
#                 return metadata
                
#             finally:
#                 # Remove temporary file
#                 try:
#                     os.unlink(temp_file_path)
#                 except Exception:
#                     pass
                
#         except Exception as e:
#             logger.error(f"Error extracting metadata from audio: {e}")
#             raise ValueError(f"Error extracting metadata from audio: {e}")
    
#     @try_except(raise_=True, exception_type=ValueError, msg="Error in waveform analysis")
#     def extract_waveform(self, data: bytes, format_name: str, options: dict[str, Any]) -> dict[str, Any]:
#         """
#         Extract waveform data from an audio file.
        
#         Args:
#             data: The binary data of the audio file.
#             format_name: The format of the audio file.
#             options: Processing options.
            
#         Returns:
#             Waveform data extracted from the audio file.
            
#         Raises:
#             ValueError: If pydub is not available or the data cannot be processed.
#         """
#         if not PYDUB_AVAILABLE:
#             raise ValueError("pydub is not available for audio waveform extraction")

#         # Save audio data to a temporary file
#         with tempfile.NamedTemporaryFile(suffix=f'.{format_name}', delete=False) as temp_file:
#             temp_file.write(data)
#             temp_file_path = temp_file.name
        
#         try:
#             # Load audio file
#             audio = AudioSegment.from_file(temp_file_path, format=format_name)

#             # TODO - Fully validate this part of the code.
#             # For a 30-second visualization, we'll extract 150 samples (1 sample per 0.2 seconds)
#             duration_seconds = len(audio) / 1000.0
#             max_samples = options.get("waveform_samples", 150)
            
#             # Calculate sample interval based on duration
#             sample_interval_ms = (len(audio) / max_samples) if duration_seconds > 0 else 200

#             # waveform_analysis_results = _analyze_waveform(audio, sample_interval_ms, duration_seconds)

#             samples = []
#             for i in range(0, len(audio), int(sample_interval_ms)):
#                 if len(samples) >= max_samples:
#                     break
#                 segment = audio[i:i+10]  # Get a 10ms segment
#                 if len(segment) > 0:
#                     samples.append(segment.dBFS)
            
#             return {
#                 'waveform_type': 'dBFS',
#                 'sample_count': len(samples),
#                 'sample_interval_ms': sample_interval_ms,
#                 'min_value': min(samples) if samples else None,
#                 'max_value': max(samples) if samples else None,
#                 'samples': samples
#             }
            
#         finally:
#             # Remove temporary file
#             try:
#                 os.unlink(temp_file_path)
#             except Exception:
#                 pass

#     @try_except(raise_=True, exception_type=ValueError, msg="Error transcribing audio")
#     def transcribe_audio(self, data: bytes, format_name: str, options: dict[str, Any]) -> str:
#         """
#         Transcribe speech to text from an audio file using Whisper.
        
#         Args:
#             data: The binary data of the audio file.
#             format_name: The format of the audio file.
#             options: Processing options including:
#                 language: The language code for transcription (e.g., "en")
#                 task: The task to perform ("transcribe" or "translate")
                
#         Returns:
#             Transcribed text from the audio file.
            
#         Raises:
#             ValueError: If Whisper is not available or the data cannot be processed.
#         """
#         if not WHISPER_AVAILABLE or self.model is None:
#             raise ValueError("Whisper is not available for speech-to-text transcription")
        
#         if not PYDUB_AVAILABLE:
#             raise ValueError("pydub is not available for audio processing")

#         # Save audio data to a temporary file
#         with tempfile.NamedTemporaryFile(suffix=f'.{format_name}', delete=False) as temp_file:
#             temp_file.write(data)
#             temp_file_path = temp_file.name
        
#         try:
#             # Parse options
#             language = options.get("language")
#             task = options.get("task", "transcribe")  # Default to transcribe
            
#             # Transcribe the audio
#             result = self.model.transcribe(
#                 temp_file_path,
#                 language=language,
#                 task=task
#             )
            
#             # Extract the transcribed text
#             text = result.get("text", "")
            
#             # Extract segments with timestamps if available
#             segments = []
#             if "segments" in result:
#                 for segment in result["segments"]:
#                     segments.append({
#                         "start": segment.get("start"),
#                         "end": segment.get("end"),
#                         "text": segment.get("text")
#                     })
            
#             # Combine them into a nicely formatted transcript
#             transcript = text.strip()
            
#             # Add detailed transcript with timestamps if segments are available
#             if segments:
#                 detailed_transcript = []
#                 for segment in segments:
#                     start_time = segment.get("start")
#                     if start_time is not None:
#                         start_str = str(timedelta(seconds=int(start_time)))
#                         detailed_transcript.append(f"[{start_str}] {segment.get('text', '')}")
#                     else:
#                         detailed_transcript.append(segment.get("text", ""))
                
#                 transcript += "\n\n--- Transcript with Timestamps ---\n\n"
#                 transcript += "\n".join(detailed_transcript)
            
#             return transcript
            
#         finally:
#             # Remove temporary file
#             try:
#                 os.unlink(temp_file_path)
#             except Exception:
#                 pass
            

#     def process_audio(self, data: bytes, format_name: str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
#         """
#         Process an audio file completely, extracting metadata, waveform, and transcribing if available.
        
#         Args:
#             data: The binary data of the audio file.
#             format_name: The format of the audio file.
#             options: Processing options.
            
#         Returns:
#             A tuple of (text content, metadata, sections).
            
#         Raises:
#             ValueError: If required dependencies are not available or the data cannot be processed.
#         """
#         try:
#             # Extract metadata
#             metadata = self.extract_metadata(data, format_name, options)
            
#             # Initialize sections
#             sections = []
            
#             # Extract waveform data if requested
#             waveform_data = None
#             if options.get("extract_waveform", True):
#                 try:
#                     waveform_data = self.extract_waveform(data, format_name, options)
#                     sections.append({
#                         'type': 'waveform',
#                         'content': waveform_data
#                     })
#                 except Exception as e:
#                     logger.warning(f"Error extracting waveform: {e}")
            
#             # Transcribe the audio if requested and Whisper is available
#             transcript = ""
#             transcribe_enabled = options.get("transcribe", True)
            
#             if transcribe_enabled and WHISPER_AVAILABLE and self.model is not None:
#                 try:
#                     transcript = self.transcribe_audio(data, format_name, options)
#                     sections.append({
#                         'type': 'transcript',
#                         'content': transcript
#                     })
#                 except Exception as e:
#                     logger.warning(f"Error transcribing audio: {e}")
#                     transcript = f"[Error during transcription: {e}]"
#             elif transcribe_enabled and (not WHISPER_AVAILABLE or self.model is None):
#                 transcript = "[Speech-to-text transcription not available]"
#                 sections.append({
#                     'type': 'transcript',
#                     'content': transcript
#                 })
            
#             # Generate human-readable description
#             text_content = [f"Audio File: {metadata.get('tag_title', 'Untitled')}"]
#             text_content.append(f"Format: {format_name.upper()}")
#             text_content.append(f"Duration: {metadata.get('duration', '0:00:00')}")
            
#             # Add artist and album if available
#             if "tag_artist" in metadata:
#                 text_content.append(f"Artist: {metadata['tag_artist']}")
            
#             if "tag_album" in metadata:
#                 text_content.append(f"Album: {metadata['tag_album']}")
            
#             # Add technical info
#             text_content.append(f"Channels: {metadata.get('channels', '?')} ({metadata.get('channel_mode', '?')})")
#             text_content.append(f"Sample Rate: {metadata.get('frame_rate_hz', '?')} Hz")
#             text_content.append(f"Bit Depth: {metadata.get('sample_width_bytes', '?') * 8} bits")
            
#             if "bitrate" in metadata:
#                 text_content.append(f"Bitrate: {float(metadata['bitrate']) / 1000:.0f} kbps")
            
#             # Add transcript if available
#             if transcript:
#                 text_content.append("\n--- Transcript ---\n")
#                 text_content.append(transcript)
            
#             # Add audio info section
#             sections.append({
#                 'type': 'audio_info',
#                 'content': {
#                     'format': format_name,
#                     'duration': metadata.get('duration', '0:00:00'),
#                     'channels': metadata.get('channels', 0),
#                     'sample_rate': metadata.get('frame_rate_hz', 0),
#                     'bit_depth': metadata.get('sample_width_bytes', 0) * 8
#                 }
#             })
            
#             # Add metadata section
#             sections.append({
#                 'type': 'metadata',
#                 'content': metadata
#             })
            
#             return "\n".join(text_content), metadata, sections
            
#         except Exception as e:
#             logger.error(f"Error processing audio file: {e}")
#             raise ValueError(f"Error processing audio file: {e}")



# # Create a global instance for usage
# audio_processor = AudioProcessor(configs=configs, resources={})
