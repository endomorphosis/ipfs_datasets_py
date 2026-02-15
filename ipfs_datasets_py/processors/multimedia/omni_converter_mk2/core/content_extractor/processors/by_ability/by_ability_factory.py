

from ._audio_processor import AudioProcessor
from ._image_processor import ImageProcessor
from ._document_processor import DocumentProcessor
from ._video_processor import VideoProcessor
from ._ebook_processor import EbookProcessor
from ._ocr_processor import OCRProcessor
from ._llm_processor import LLMProcessor

from dependencies import dependencies
from external_programs import ExternalPrograms
from configs import configs
from logger import logger

_processors = [
    AudioProcessor,
    ImageProcessor,
    DocumentProcessor,
    VideoProcessor,
    EbookProcessor,
    OCRProcessor,
    LLMProcessor
]

def _get_available_processors() -> list:
    """
    Check if the processor is available.
    This function should be implemented in each processor class.
    """
    available_processors = []
    for processor in _processors:
        # Try to instantiate the processor
        resources = {
            "dependencies": dependencies,
            "external_programs": ExternalPrograms,
            "logger": logger,
        }
        processor = None
        try:
            processor = processor(resources=resources, configs=configs)
            available_processors.append(processor)
        except Exception as e:
            print(f"Failed to instantiate processor {processor.__name__}: {e}")
            continue 
        finally:
            # Free resources if processor was instantiated
            if processor is not None:
                del processor 

def make_processors():
    """
    """
    available_processor = _get_available_processors()

def create_llm_processor() -> LLMProcessor:
    """
    Factory function to create an LLMProcessor instance.
    
    Args:
        resources: Dictionary of resources for dependency injection
        configs: Configuration parameters
        
    Returns:
        Configured LLMProcessor instance
    """
    resources = {}
    return LLMProcessor(resources=resources, configs=configs)
