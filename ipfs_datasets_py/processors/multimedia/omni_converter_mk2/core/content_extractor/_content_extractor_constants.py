from pathlib import Path
from typing import Generator

# TODO Can probably move this to utils folder.
def _get_generic_processors() -> Generator[set[str], None, None]:
    _dependency_dir = Path.cwd() / 'extractors' / 'fallbacks'
    for file in _dependency_dir.glob("*.py"):
        if file.name.startswith("_") and "generic" in file.name:
            # _generic_plaintext_processor.py -> generic_plaintext
            file_stem = file.stem.lstrip("_").rstrip("_processor")
            yield file_stem


class _classproperty:
    """Helper decorator to turn class methods into properties."""
    def __init__(self, func):
        self.func = func
    
    def __get__(self, instance, owner):
        return self.func(owner)


class Constants:
    """
    Utility class for managing constants related to format handlers.
    This includes 
    Constants for format handlers including supported formats and capabilities.
    
    Table of Contents:
    - Dependency and External Programs Availability
        Boolean properties to check if external cls._dependencies and programs are available.
    - Combination Processors
        Boolean properties to check if a combination of cls._dependencies are available to enable certain processors.
        For example, if openpyxl *or* pandas is available, the xlsx processor can be used.
    - Format Handlers Constants
    - MIME Type to Format Mapping
    - Unimplemented Formats
    - All Formats from ROADMAP
    """
    #########################################################################
    ### Dependency, Generic Fallbacks, and External Programs Availability ###
    #########################################################################
    from dependencies import dependencies
    from external_programs import ExternalPrograms

    _dependencies = {name: True for name in dependencies.keys()}

    # Generic fallbacks that only use built-in python libraries.
    _generic_processors = {name: True for name in _get_generic_processors()}

    _external_programs = {name: True for name in ExternalPrograms.keys()}

    @_classproperty
    def ANTHROPIC_AVAILABLE(cls) -> bool:
        """Check if anthropic is available."""
        return cls._dependencies.get('anthropic', False)

    @_classproperty
    def BS4_AVAILABLE(cls) -> bool:
        """Check if BeautifulSoup is available."""
        return cls._dependencies.get('bs4', False)

    @_classproperty
    def CV2_AVAILABLE(cls) -> bool:
        """Check if cv2 is available."""
        return cls._dependencies.get('cv2', False)

    @_classproperty
    def DUCKDB_AVAILABLE(cls) -> bool:
        """Check if duckdb is available."""
        return cls._dependencies.get('duckdb', False)

    @_classproperty
    def FFMPEG_AVAILABLE(cls) -> bool:
        """Check if ffmpeg is available."""
        return cls._external_programs.get('ffmpeg', False)

    @_classproperty
    def FFPROBE_AVAILABLE(cls) -> bool:
        """Check if ffprobe is available."""
        return cls._external_programs.get('ffprobe', False)

    @_classproperty
    def JINJA2_AVAILABLE(cls) -> bool:
        """Check if jinja2 is available."""
        return cls._dependencies.get('jinja2', False)

    @_classproperty
    def PYMEDIAINFO_AVAILABLE(cls) -> bool:
        """Check if pymediainfo is available."""
        return cls._dependencies.get('pymediainfo', False)

    @_classproperty
    def NLTK_AVAILABLE(cls) -> bool:
        """Check if nltk is available."""
        return cls._dependencies.get('nltk', False)

    @_classproperty
    def NUMPY_AVAILABLE(cls) -> bool:
        """Check if numpy is available."""
        return cls._dependencies.get('numpy', False)

    @_classproperty
    def OPENAI_AVAILABLE(cls) -> bool:
        """Check if openai is available."""
        return cls._dependencies.get('openai', False)

    @_classproperty
    def OPENPYXL_AVAILABLE(cls) -> bool:
        """Check if openpyxl is available."""
        return cls._dependencies.get('openpyxl', False)

    @_classproperty
    def PANDAS_AVAILABLE(cls) -> bool:
        """Check if pandas is available."""
        return cls._dependencies.get('pandas', False)

    @_classproperty
    def PYPDF2_AVAILABLE(cls) -> bool:
        """Check if PyPDF2 is available."""
        return cls._dependencies.get('PyPDF2', False)

    @_classproperty
    def PIL_AVAILABLE(cls) -> bool:
        return cls._dependencies.get('PIL', False)

    @_classproperty
    def PSUTIL_AVAILABLE(cls) -> bool:
        """Check if psutil is available."""
        return cls._dependencies.get('psutil', False)

    @_classproperty
    def PYDANTIC_AVAILABLE(cls) -> bool:
        """Check if pydantic is available."""
        return cls._dependencies.get('pydantic', False)

    @_classproperty
    def PYDUB_AVAILABLE(cls) -> bool:
        """Check if pydub is available."""
        return cls._dependencies.get('pydub', False)

    @_classproperty
    def PYPDF2_AVAILABLE(cls) -> bool:
        """Check if PDF processor is available."""
        return cls._dependencies.get('PyPDF2', False)

    @_classproperty
    def PYTESSERACT_AVAILABLE(cls) -> bool:
        """Check if pytesseract is available."""
        return cls._dependencies.get('pytesseract', False)

    @_classproperty
    def PYTHON_DOCX_AVAILABLE(cls) -> bool:
        """Check if DOCX processor is available."""
        return cls._dependencies.get('docx', False)

    @_classproperty
    def PYYAML_AVAILABLE(cls) -> bool:
        """Check if yaml is available."""
        return cls._dependencies.get('yaml', False)

    @_classproperty
    def REPORTLAB_AVAILABLE(cls) -> bool:
        """Check if reportlab is available."""
        return cls._dependencies.get('reportlab', False)

    @_classproperty
    def ROUGE_AVAILABLE(cls) -> bool:
        """Check if rouge is available."""
        return cls._dependencies.get('rouge', False)

    @_classproperty
    def TESSERACT_AVAILABLE(cls) -> bool:
        """Check if tesseract is available."""
        return cls._external_programs.get('tesseract', False)

    @_classproperty
    def TIKTOKEN_AVAILABLE(cls) -> bool:
        """Check if tiktoken is available."""
        return cls._dependencies.get('tiktoken', False)

    @_classproperty
    def TORCH_AVAILABLE(cls) -> bool:
        """Check if torch is available."""
        return cls._dependencies.get('torch', False)

    @_classproperty
    def TQDM_AVAILABLE(cls) -> bool:
        """Check if tqdm is available."""
        return cls._dependencies.get('tqdm', False)

    @_classproperty
    def WHISPER_AVAILABLE(cls) -> bool:
        """Check if whisper is available."""
        return cls._dependencies.get('whisper', False)

    ####################################
    ### Generic Processors Constants ###
    ####################################

    @_classproperty
    def GENERIC_PLAINTEXT_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if generic plaintext processor is available."""
        return cls._generic_processors.get('generic_plaintext', False)

    @_classproperty
    def GENERIC_HTML_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if generic plaintext processor is available."""
        return cls._generic_processors.get('generic_html', False)

    @_classproperty
    def GENERIC_XML_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if generic plaintext processor is available."""
        return cls._generic_processors.get('generic_xml', False)

    @_classproperty
    def GENERIC_SVG_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if generic plaintext processor is available."""
        return cls._generic_processors.get('generic_svg', False)

    ##############################
    ### Combination Processors ###
    ##############################

    @_classproperty
    def PLAINTEXT_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if plaintext processor is available."""
        return cls.PYTHON_DOCX_AVAILABLE or cls.GENERIC_PLAINTEXT_PROCESSOR_AVAILABLE 

    @_classproperty
    def IMAGE_PROCESSOR_AVAILABLE(cls) -> bool: # TODO Add more checks for other cls._dependencies. Should be along the lines of `x or y or z` to check for multiple cls._dependencies.
        """Check if image processing capabilities are available."""
        return cls.PIL_AVAILABLE or cls.OPENAI_AVAILABLE or cls.PYTESSERACT_AVAILABLE

    @_classproperty
    def VIDEO_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if video processing capabilities are available."""
        return cls.FFMPEG_AVAILABLE and cls.PYMEDIAINFO_AVAILABLE

    @_classproperty
    def XLSX_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if XLSX processing capabilities are available."""
        return cls.OPENPYXL_AVAILABLE or cls.PANDAS_AVAILABLE

    @_classproperty
    def PDF_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if PDF processor is available."""
        return cls.PYPDF2_AVAILABLE

    @_classproperty
    def HTML_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if HTML processor is available."""
        return cls.BS4_AVAILABLE or cls.GENERIC_HTML_PROCESSOR_AVAILABLE

    @_classproperty
    def TRANSCRIPTION_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if transcription capabilities are available."""
        return cls.WHISPER_AVAILABLE

    @_classproperty
    def OCR_PROCESSOR_AVAILABLE(cls) -> bool:
        """Check if OCR capabilities are available."""
        return cls.OPENAI_AVAILABLE or cls.ANTHROPIC_AVAILABLE or cls.PYTESSERACT_AVAILABLE

    def __getitem__(self, name: str) -> bool:
        """Get a external program by name."""
        try:
            return getattr(self, name)
        except AttributeError as e:
            raise KeyError(f"External program '{name}' not found ExternalPrograms.") from e

    @classmethod
    def get(cls, name: str, default: bool = False) -> bool:
        """
        Get a external program by name with a default value.
        
        Args:
            name: The name of the external program.
            default: The default value to return if the external program is not found.
        
        Returns:
            The external program if found, otherwise the default value.
        """
        return getattr(cls, name, default)

    @classmethod
    def keys(cls) -> list[str]:
        """
        Get a list of all external program names.
        
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
