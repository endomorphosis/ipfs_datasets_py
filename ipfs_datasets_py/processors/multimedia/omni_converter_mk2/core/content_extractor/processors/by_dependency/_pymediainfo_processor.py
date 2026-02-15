"""
PyMediaInfo processor module for the Omni-Converter.

This module isolates the pymediainfo dependency and provides functions for
extracting metadata from video files in a memory-efficient manner.
"""

import os
from datetime import timedelta
from typing import Any, Optional, Union, TypeAlias

from logger import logger

# Import pymediainfo for metadata extraction (will be installed via requirements.txt)
# TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
try:
    import pymediainfo # TODO This should be checked in constants.py.
    PYMEDIAINFO_AVAILABLE = True
    
    # Define custom type for pymediainfo Track
    Track: TypeAlias = pymediainfo.Track
except ImportError:
    logger.warning("pymediainfo not available, video metadata extraction will be limited")
    PYMEDIAINFO_AVAILABLE = False
    
    # Fallback to Any if pymediainfo is not available
    Track: TypeAlias = Any


def is_available() -> bool:
    """
    Check if pymediainfo is available.
    
    Returns:
        True if pymediainfo is available, False otherwise.
    """
    return PYMEDIAINFO_AVAILABLE


def extract_metadata(file_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Extract metadata from a video file using pymediainfo.
    
    Args:
        file_path: Path to the video file.
        
    Returns:
        Tuple of (metadata dictionary, track information list).
        
    Raises:
        ValueError: If pymediainfo is not available.
        Exception: If an error occurs during extraction.
    """
    if not PYMEDIAINFO_AVAILABLE:
        raise ValueError("pymediainfo is not available. Install it to use this function.")
    
    try:
        # Create metadata dictionary
        metadata = {
            'file_size_bytes': os.path.getsize(file_path),
            'tracks': []
        }
        
        # Get media info using streaming mode if possible
        if hasattr(pymediainfo.MediaInfo, 'parse_with_options'):
            # Use streaming mode if available (newer pymediainfo versions)
            media_info = pymediainfo.MediaInfo.parse_with_options( # TODO This needs to be confirmed to exist. It shows as white in VSCode.
                filename=file_path,
                options={"File_FileNameFormat": "CSV", "File_ExpandFileNames": "1"}
            )
        else:
            # Fall back to standard parser
            media_info = pymediainfo.MediaInfo.parse(file_path)
        
        # Process tracks
        general_info = None
        video_tracks = []
        audio_tracks = []
        text_tracks = []
        other_tracks = []
        
        for track in media_info.tracks:
            track_data = {'track_type': track.track_type}
            
            # Add all attributes from the track to track_data
            for attr in dir(track):
                if not attr.startswith('__') and not callable(getattr(track, attr)):
                    value = getattr(track, attr)
                    if value is not None and value != "":
                        track_data[attr] = value
            
            # Categorize tracks by type
            match track.track_type:
                case 'General':
                    general_info = track_data
                    metadata['general'] = track_data
                    
                    # Add duration and other general information
                    if hasattr(track, 'duration'):
                        duration_ms = getattr(track, 'duration', 0)
                        if duration_ms:
                            duration = str(timedelta(milliseconds=int(duration_ms)))
                            metadata['duration_ms'] = duration_ms
                            metadata['duration'] = duration
                    
                    # Add file size
                    if hasattr(track, 'file_size'):
                        file_size = getattr(track, 'file_size', 0)
                        if file_size:
                            metadata['file_size_bytes'] = file_size
                    
                    # Add overall bitrate
                    if hasattr(track, 'overall_bit_rate'):
                        overall_bit_rate = getattr(track, 'overall_bit_rate', 0)
                        if overall_bit_rate:
                            metadata['overall_bitrate_kbps'] = int(overall_bit_rate)/1000
                
                case 'Video':
                    video_tracks.append(track_data)
                    
                case 'Audio':
                    audio_tracks.append(track_data)
                    
                case 'Text':
                    text_tracks.append(track_data)
                    
                case _:
                    other_tracks.append(track_data)
        
        # Add track data to metadata
        for key, value in [("video_tracks", video_tracks),
                           ("audio_tracks", audio_tracks),
                           ("text_tracks", text_tracks),
                           ("other_tracks", other_tracks)]:
            metadata[key] = value
            metadata[key.rstrip('s') + "_count"] = len(value)  # Add track count to metadata
        
        # Create track list
        tracks = []
        
        # Add sections for each track type
        for type_, content in [('general_info', general_info),
                             ('video_tracks', video_tracks),
                             ('audio_tracks', audio_tracks),
                             ('text_tracks', text_tracks),
                             ('other_tracks', other_tracks)]:
            if content:
                tracks.append({
                    'type': type_,
                    'content': content,
                })
        
        return metadata, tracks
        
    except Exception as e:
        logger.exception(f"Error extracting metadata with pymediainfo: '{file_path}'\n{e}")
        raise e


def format_text_content(track: 'Track', attribute_list: list[tuple[str, Any, Any]]) -> list[str]:
    """
    Format text content for a specific track.
    
    Args:
        track: The track to format.
        attribute_list: list of (attribute_name, default_value, formatter_function) tuples.
        
    Returns:
        List of formatted text lines.
    """
    text_content = []
    for attr, default, func in attribute_list:
        if hasattr(track, attr):
            value = getattr(track, attr, default)
            if value:
                name = attr.replace('_', ' ').capitalize()
                if callable(func):
                    value = func(value)
                text_content.append(f"  {name}: {value}".rstrip())
    
    return text_content


def generate_text_description(file_path: str, metadata: dict[str, Any]) -> str:
    """
    Generate a human-readable description from metadata.
    
    Args:
        file_path: Path to the video file.
        metadata: Metadata dictionary from extract_metadata.
        
    Returns:
        Human-readable description of the video file.
    """
    text_content = [f"Video File: {os.path.basename(file_path)}"]
    
    # Add format if available
    if 'format' in metadata:
        text_content.append(f"Format: {metadata['format'].upper()}")
    
    # Add general information
    if 'general' in metadata:
        general = metadata['general']
        
        # Add duration
        if 'duration' in metadata:
            text_content.append(f"Duration: {metadata['duration']}")
        
        # Add file size
        if 'file_size_bytes' in metadata:
            text_content.append(f"File Size: {format_file_size(metadata['file_size_bytes'])}")
        
        # Add overall bitrate
        if 'overall_bitrate_kbps' in metadata:
            text_content.append(f"Overall Bitrate: {metadata['overall_bitrate_kbps']:.0f} kbps")
    
    # Add video track information
    if 'video_tracks' in metadata and metadata['video_tracks']:
        text_content.append("\nVideo:")
        
        for track in metadata['video_tracks']:
            # Add resolution
            if 'width' in track and 'height' in track:
                width, height = track.get('width', 0), track.get('height', 0)
                if width and height:
                    text_content.append(f"  Resolution: {width}x{height}")
            
            # Add frame rate, codec, bit depth, and bit rate
            attribute_list = [
                ('frame_rate', 0, lambda x: f"{float(x):.2f} fps"),
                ('codec', '', None),
                ('bit_depth', '', lambda x: f"{x} bits"),
                ('bit_rate', 0, lambda x: f"{int(x)/1000:.0f} kbps")
            ]
            
            text_content.extend(format_text_content(track, attribute_list))
    
    # Add audio track information
    if 'audio_tracks' in metadata and metadata['audio_tracks']:
        for i, track in enumerate(metadata['audio_tracks']):
            # Label track if multiple audio tracks
            if len(metadata['audio_tracks']) == 1:
                text_content.append("\nAudio:")
            else:
                text_content.append(f"\nAudio Track {i+1}:")
            
            # Add channels, sample rate, codec, language, and bit rate
            attribute_list = [
                ('channel_s', 0, lambda x: '(Mono)' if x == 1 else '(Stereo)' if x == 2 else '(Multi-channel)'),
                ('sampling_rate', 0, lambda x: f"{int(x)/1000:.1f} kHz"),
                ('codec', '', None),
                ('language', '', None),
                ('bit_rate', 0, lambda x: f"{int(x)/1000:.0f} kbps")
            ]
            
            text_content.extend(format_text_content(track, attribute_list))
    
    # Add subtitle track information
    if 'text_tracks' in metadata and metadata['text_tracks']:
        text_content.append("\nSubtitles:")
        
        for track in metadata['text_tracks']:
            # Add language and format
            attribute_list = [
                ('language', '', None),
                ('format', '', None)
            ]
            
            text_content.extend(format_text_content(track, attribute_list))
    
    return "\n".join(text_content)


def format_file_size(size_in_bytes: int) -> str: # TODO This should be a separate file in utils folder. Also, this is a duplicate utility function.
    """
    Format file size in human-readable format.
    
    Args:
        size_in_bytes: Size in bytes.
        
    Returns:
        Formatted file size string.
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0 or unit == 'TB':
            break
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} {unit}"


def process_video_metadata(file_path: str, format_name: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process a video file and extract metadata using pymediainfo.
    
    Args:
        file_path: Path to the video file.
        format_name: Format of the video file.
        
    Returns:
        Tuple of (text content, metadata, sections).
    """
    if not PYMEDIAINFO_AVAILABLE:
        # Return basic metadata if pymediainfo is not available
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        # Build basic metadata
        metadata = {
            'format': format_name,
            'file_size_bytes': file_size,
            'file_name': file_name
        }
        
        # Generate basic description
        text_content = [f"Video File: {file_name}"]
        text_content.append(f"Format: {format_name.upper()}")
        text_content.append(f"File Size: {format_file_size(file_size)}")
        text_content.append("")
        text_content.append("Note: Detailed video information not available.")
        text_content.append("Install pymediainfo for enhanced video metadata extraction.")
        
        # Create basic sections
        sections = [
            {
                'type': 'video_info',
                'content': {
                    'format': format_name,
                    'file_size': file_size
                }
            }
        ]
        
        return "\n".join(text_content), metadata, sections
    
    # Extract metadata using pymediainfo
    metadata, track_sections = extract_metadata(file_path)
    
    # Add format information
    metadata['format'] = format_name
    
    # Generate text description
    text_content = generate_text_description(file_path, metadata)
    
    # Convert track sections to sections format
    sections = track_sections
    
    return text_content, metadata, sections