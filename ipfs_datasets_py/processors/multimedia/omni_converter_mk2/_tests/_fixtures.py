from typing import Any

def _fixture_dict() -> dict[str, Any]:
    """
    Create a fixture dictionary for testing.

    Returns:
        A dictionary containing various test fixtures.
    """
    from core import make_processing_pipeline
    from batch_processor.batch_processor_factory import make_batch_processor
    from monitors import make_resource_monitor, make_error_monitor, make_security_monitor
    from file_format_detector import make_file_format_detector
    from core.file_validator.file_validator_factory import FileValidator, make_file_validator
    from core.content_extractor.content_extractor_factory import ContentExtractor
    from logger import logger
    from configs import configs
    from dependencies import dependencies
    from external_programs import ExternalPrograms

    return {
        "processing_pipeline": make_processing_pipeline,
        "batch_processor": make_batch_processor,
        "file_format_detector": make_file_format_detector,
        "resource_monitor": make_resource_monitor,
        "security_monitor": make_security_monitor,
        "logger": logger,
        "error_monitor": make_error_monitor,
        "configs": configs,
        "dependencies": dependencies,
        "external_programs": ExternalPrograms,
        "file_validator": make_file_validator,
        "content_extractor_object": ContentExtractor,
    }

fixtures = _fixture_dict()
