from configs import configs
from file_format_detector import make_file_format_detector
from logger import logger
from utils.filesystem import FileSystem
from ._file_validator import FileValidator
from ._validation_result import ValidationResult


def make_file_validator() -> FileValidator:
    """Factory function to create a FileValidator instance.

    Args:
        resources: Additional resources to provide.
        configs: Configuration settings.

    Returns:
        An instance of FileValidator.
    """
    # Create resources dictionary
    resources = {
        "file_exists": FileSystem.file_exists,
        "get_file_info": FileSystem.get_file_info,
        "validation_result": ValidationResult,
        "file_format_detector": make_file_format_detector(),
        "logger": logger,
    }

    return FileValidator(resources=resources, configs=configs)
