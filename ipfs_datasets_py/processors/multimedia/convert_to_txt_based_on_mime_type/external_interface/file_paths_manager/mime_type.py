from enum import Enum

class MimeType(str, Enum):
    """Mime types"""
    APPLICATION = "application"
    IMAGE = "image"
    TEXT = "text"
    VIDEO = "video"
    AUDIO = "audio"
