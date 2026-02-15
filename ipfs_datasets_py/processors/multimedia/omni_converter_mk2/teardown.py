"""
Module to handle the teardown of the application.
Its meant to make sure memory intensive objects and resources, such as
AI models like Whisper, are properly released when the application exits.
"""
def teardown():
    """
    Cleanup function to be called on application exit.
    """
    purge_whisper_model()
    # Add any other cleanup tasks here

def purge_whisper_model():
    from core.content_extractor.processors.by_ability import whisper_processor
    if whisper_processor and whisper_processor.model:
        whisper_processor.model = None

def core_dump():
    """
    Function to handle core dump on unexpected exit.
    This is a placeholder for actual core dump logic.
    """
    from monitors._error_monitor import ErrorMonitor
    # Implement core dump logic here if needed