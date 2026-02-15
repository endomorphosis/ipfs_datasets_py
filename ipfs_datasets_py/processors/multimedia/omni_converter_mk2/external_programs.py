import threading as _threading
import subprocess as _sub
from logger import logger as _logger

import resource

class _classproperty:
    """Helper decorator to turn class methods into properties."""
    def __init__(self, func):
        self.func = func
    
    def __get__(self, instance, owner):
        return self.func(owner)

class ExternalPrograms: # TODO Figure out how to run the program checks in parallel.
    """Check the availability of external programs.

    NOTE: As these programs are entirely external, this class does not provide access to them.
    It only checks if they exist and can be run.

    Properties:
        ffmpeg (bool): Whether ffmpeg is available.
        ffprobe (bool): Whether ffprobe is available.
        tesseract (bool): Whether tesseract is available.
        calibre (bool): Whether calibre is available.
        cuda (bool): Whether nvcc (NVIDIA CUDA Compiler) is available.
        seven_zip (bool): Whether 7-zip is available.
        libreoffice (bool): Whether LibreOffice is available.
        audacity (bool): Whether Audacity is available (optional, TODO: check for CLI).
    """
    _EXTERNAL_PROGRAMS = {
        "ffmpeg": False,  # ffmpeg for video processing
        "ffprobe": False,  # ffprobe for video metadata extraction
        "tesseract": False,  # tesseract for OCR (optional)
        "calibre": False,  # calibre for ebook processing (optional)
        "nvcc": False,  # nvcc for CUDA compilation (optional)
        "7-zip": False,  # 7-zip for file compression/decompression (optional)
        "libreoffice": False,  # LibreOffice for document processing (optional)
        "audacity": False,  # Audacity for audio processing (optional) TODO Figure out if there's a CLI for this.
        "nvidia-smi": False,  # nvidia-smi for GPU monitoring (optional)
        "imagemagick": False,  # ImageMagick for image processing (optional)
        "ghostscript": False,  # Ghostscript for PDF processing (optional)
        "pandoc": False,  # Pandoc for document conversion (optional)
    }

    @classmethod
    def check_for_external_programs(cls) -> None:
        """
        Check if external programs are available.
        
        This method checks the availability of various external programs by attempting to run them
        with the '--help' option. If the program is found and runs successfully, it is marked as available.
        If it fails or is not found, it is marked as unavailable.
        """
        for program, _ in cls._EXTERNAL_PROGRAMS.items():
            available = False
            try: # TODO Every CLI program should have a --help option, but this should be confirmed. 
                _ = _sub.run([program, "--help"], check=True, stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
                available = True
                _logger.info(f" ✓ '{program}' is available")
            except _sub.CalledProcessError:
                _logger.warning(f"✗ '{program}' is available but returned an error when run with --help.")
            except FileNotFoundError:
                _logger.warning(f"✗ '{program}' is not available, functionality will be limited")
            except Exception as e:
                _logger.warning(f"✗ Unexpected {type(e).__name__} checking '{program}' availability: {e}")
            finally:
                cls._EXTERNAL_PROGRAMS[program] = available
                continue

    @_classproperty
    def ffmpeg(cls) -> bool:
        """Check if ffmpeg is available."""
        return cls._EXTERNAL_PROGRAMS["ffmpeg"]

    @_classproperty
    def ffprobe(cls) -> bool:
        """Check if ffprobe is available."""
        return cls._EXTERNAL_PROGRAMS["ffprobe"]

    @_classproperty
    def tesseract(cls) -> bool:
        """Check if tesseract is available."""
        return cls._EXTERNAL_PROGRAMS["tesseract"]

    @_classproperty
    def calibre(cls) -> bool:
        """Check if calibre is available."""
        return cls._EXTERNAL_PROGRAMS["calibre"]

    @_classproperty
    def cuda(cls) -> bool:
        """Check if nvcc (NVIDIA CUDA Compiler) is available."""
        return cls._EXTERNAL_PROGRAMS["nvcc"]

    @_classproperty
    def seven_zip(cls) -> bool:
        """Check if 7-zip is available."""
        return cls._EXTERNAL_PROGRAMS["7-zip"]

    @_classproperty
    def libreoffice(cls) -> bool:
        """Check if LibreOffice is available."""
        return cls._EXTERNAL_PROGRAMS["libreoffice"]

    @_classproperty
    def nvidia_smi(cls) -> bool:
        """Check if nvidia-smi is available."""
        return cls._EXTERNAL_PROGRAMS["nvidia-smi"]

    def __getitem__(self, name: str) -> bool:
        """Get a external program by name."""
        try:
            return getattr(self, name)
        except AttributeError as e:
            raise KeyError(f"External program '{name}' not found.") from e

    @classmethod
    def get(cls, name: str, default: bool = False) -> bool:
        """Get a external program by name with a default value.
        
        Args:
            name (str): The name of the external program.
            default (bool): The default value to return if the external program is not found.
                Defaults to False.
        
        Returns:
            The external program if found, otherwise the default value.
        """
        return getattr(cls, name, default)

    @classmethod
    def keys(cls) -> list[str]:
        """Get a list of all external program names.
        
        Returns:
            A list of external program names.
        """
        return [
            name for name in dir(cls) 
            if not name.startswith('_') # Check if it's not a private attribute
            and hasattr(_classproperty, name) # Check for class properties decorator
        ]

    @classmethod
    def items(cls) -> list[tuple[str, bool]]:
        """
        Get a list of all dependencies as (name, dependency) tuples.
        
        Returns:
            A list of tuples containing dependency names and their corresponding objects.
        """
        return [
            (name, getattr(cls, name)) # Check if the attribute exists. The second part of each tuple must be a boolean
            for name in cls.keys()
        ]

def _test_for_non_critical_external_programs() -> None:
    """
    Test for non-critical dependencies in a separate thread to ensure the application starts promptly.

    This function creates a temporary instance of the `_Dependencies` class to load all required
    modules without causing deadlocks. Once the modules are loaded, the temporary instance is
    cleared from memory to optimize resource usage.

    Key Steps:
    1. Creates a separate `_Dependencies` instance to handle module loading.
    2. Ensures all modules are loaded using `load_all_modules`.
    3. Clears the cache and deletes the temporary instance to free up memory.
    4. Triggers garbage collection to reclaim unused memory.

    Note:
    - This function is designed to handle non-critical dependencies, allowing the application
        to start without waiting for all dependencies to be fully loaded.
    """
    ExternalPrograms.check_for_external_programs()

_load_thread = _threading.Thread(target=_test_for_non_critical_external_programs, daemon=True)
_load_thread.start()
