from types_ import Any


class HandlerCapabilities: # TODO Determine if this even needs to exist.
    """
    Utility class to define and manage handler capabilities for different file types.
    """

    class _classproperty:
        """Helper decorator to turn class methods into properties."""
        def __init__(self, func):
            self.func = func
        
        def __get__(self, instance, owner):
            return self.func(owner)

    @_classproperty
    def APPLICATION_HANDLER_CAPABILITIES(cls) -> dict[str, Any]:
        return {
        'category': 'application',
        'preserves_structure': True,
        'extracts_metadata': True,
        'supports_nested_files': True
        }

    @_classproperty
    def AUDIO_HANDLER_CAPABILITIES(cls) -> dict[str, Any]:
        return  {
        'category': 'audio',
        'preserves_structure': False,
        'extracts_metadata': True,
        'supports_transcription': False,  # Set dynamically based on availability
    }

    @_classproperty
    def IMAGE_HANDLER_CAPABILITIES(cls) -> dict[str, Any]:
        return {
        'category': 'image',
        'preserves_structure': False,
        'extracts_metadata': True,
        'supports_ocr': 'basic'
        }

    @_classproperty
    def TEXT_HANDLER_CAPABILITIES(cls) -> dict[str, Any]:
        return {
        'category': 'text',
        'preserves_structure': True,
        'extracts_metadata': True,
        'supports_encoding_detection': True
        }

    @_classproperty
    def VIDEO_HANDLER_CAPABILITIES(cls) -> dict[str, Any]:
        return {
        'category': 'video',
        'preserves_structure': False,
        'extracts_metadata': True,
        'supports_transcription': False,
        'extracts_thumbnails': False
        }
