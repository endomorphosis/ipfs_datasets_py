

from supported_formats import SupportedFormats
from types_ import Any, Generator


def get_processor_resource_configs() -> Generator[dict[str, Any], None, None]:
    """
    Generator that yields resource configuration dictionaries for content processors.
    
    Each resource configuration contains:
    - supported_formats: Set of file extensions the processor can handle
    - processor_name: Unique identifier for the processor
    - dependencies: Dict of required Python packages/modules (name -> version or None)
    - critical_resources: List of methods that must be available for core functionality
    - optional_resources: List of methods that provide enhanced features but aren't required
    
    Yields:
        dict: Resource configuration for each processor
    """
    resource_list = [
        {
            "supported_formats": SupportedFormats.SUPPORTED_IMAGE_FORMATS, #{"jpg", "jpeg", "png", "gif", "bmp"},
            "processor_name": "image_processor",
            "dependencies": {"PIL": None, "opencv": None},
            "critical_resources": ["extract_metadata", "process"],
            "optional_resources": ["extract_text", "resize", "convert"],
        },
        {
            "supported_formats": SupportedFormats.SUPPORTED_AUDIO_FORMATS, #{"mp3", "wav", "flac", "ogg"},
            "processor_name": "audio_processor",
            "dependencies": {"pydub": None, "librosa": None},
            "critical_resources": ["extract_metadata", "process"],
            "optional_resources": ["extract_text", "convert", "analyze"],
        },
        {
            "supported_formats": SupportedFormats.SUPPORTED_TEXT_FORMATS, #{"txt", "md", "rst"},
            "processor_name": "text_processor",
            "dependencies": {},
            "critical_resources": ["extract_text", "process", "extract_metadata", "extract_structure"],
            "optional_resources": ["extract_metadata", "analyze"],
        },
        {
            "supported_formats": SupportedFormats.SUPPORTED_VIDEO_FORMATS, # {"mp4", "avi", "mov", "mkv"},
            "processor_name": "video_processor",
            "dependencies": {"opencv": None, "moviepy": None},
            "critical_resources": ["extract_metadata", "process"],
            "optional_resources": ["extract_frames", "extract_audio"],
        },
        { # TODO: Figure out which formats document_processor should support.
            "supported_formats": SupportedFormats.DOCUMENT_FORMAT_EXTENSIONS, # {"doc", "docx", "odt", "rtf"},
            "processor_name": "document_processor",
            "dependencies": {"docx": None, "libreoffice": None},
            "critical_resources": ["extract_text", "extract_metadata", "process"],
            "optional_resources": ["extract_images", "extract_structure"],
        },
        {
            "supported_formats": SupportedFormats.HTML_FORMAT_EXTENSIONS, # {"html", "htm"},
            "processor_name": "html_processor",
            "dependencies": {"beautifulsoup4": None, "lxml": None},
            "critical_resources": ["extract_text", "process", "extract_metadata", "extract_structure"],
            "optional_resources": ["extract_links"],
        },
        {
            "supported_formats": SupportedFormats.XML_FORMAT_EXTENSIONS, # {"xml"},
            "processor_name": "xml_processor",
            "dependencies": {"lxml": None, "xml.etree": None},
            "critical_resources": ["extract_structure", "process"],
            "optional_resources": ["extract_text", "validate"],
        },
        {
            "supported_formats": SupportedFormats.CALENDAR_FORMAT_EXTENSIONS, # {"ics", "ical"},
            "processor_name": "calendar_processor",
            "dependencies": {"icalendar": None},
            "critical_resources": ["extract_text", "process", "extract_metadata", "extract_structure"],
            "optional_resources": ["extract_metadata"],
        },
        {
            "supported_formats": SupportedFormats.CSV_FORMAT_EXTENSIONS, # {"csv"},
            "processor_name": "csv_processor",
            "dependencies": {"pandas": None},
            "critical_resources": ["extract_metadata", "extract_structure", "extract_text", "process"],
            "optional_resources": ["extract_metadata", "analyze"],
        },
        # {
        #     "supported_formats": SupportedFormats.PLAINTEXT_FORMAT_EXTENSIONS,
        #     "processor_name": "plaintext_processor",
        #     "dependencies": {},
        #     "critical_resources": ["extract_text", "process"],
        #     "optional_resources": ["extract_metadata"],
        # },
        {
            "supported_formats": SupportedFormats.EBOOK_FORMAT_EXTENSIONS, # {"epub", "mobi", "azw"},
            "processor_name": "ebook_processor",
            "dependencies": {"ebooklib": None, "calibre": None},
            "critical_resources": ["extract_text", "extract_metadata"],
            "optional_resources": ["extract_images", "convert"],
        },
        {
            "supported_formats": SupportedFormats.TRANSCRIPTION_FORMAT_EXTENSIONS, # {"srt", "vtt", "ass"},
            "processor_name": "transcription_processor",
            "dependencies": {"pysrt": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["extract_metadata", "convert"],
        },
        {
            "supported_formats": {"svg"},
            "processor_name": "svg_processor",
            "dependencies": {"svgpathtools": None, "lxml": None},
            "critical_resources": ["extract_structure", "process"],
            "optional_resources": ["extract_text", "convert"],
        },
        {
            "supported_formats": {"pdf"},
            "processor_name": "pdf_processor",
            "dependencies": {"pypdf2": None, "pdfplumber": None},
            "critical_resources": ["extract_text", "extract_metadata"],
            "optional_resources": ["extract_images", "extract_structure"],
        },
        {
            "supported_formats": {"json", "jsonl"},
            "processor_name": "json_processor",
            "dependencies": {},
            "critical_resources": ["extract_data", "process"],
            "optional_resources": ["validate", "analyze"],
        },
        {
            "supported_formats": {"docx"},
            "processor_name": "docx_processor",
            "dependencies": {"python-docx": None, "libreoffice": None},
            "critical_resources": ["extract_text", "extract_metadata"],
            "optional_resources": ["extract_images", "extract_structure"],
        },
        {
            "supported_formats": {"pptx", "ppt"},
            "processor_name": "pptx_processor",
            "dependencies": {"python-pptx": None, "libreoffice": None},
            "critical_resources": ["extract_text", "extract_metadata"],
            "optional_resources": ["extract_images", "extract_structure"],
        },
        {
            "supported_formats": SupportedFormats.ARCHIVE_FORMAT_EXTENSIONS, # {"zip", "tar", "gz", "7z"},
            "processor_name": "zip_processor",
            "dependencies": {"zipfile": None, "tarfile": None},
            "critical_resources": ["extract_files", "process"],
            "optional_resources": ["extract_metadata"],
        },
        {
            "supported_formats": SupportedFormats.RASTER_IMAGE_FORMAT_EXTENSIONS, # {"jpg", "jpeg", "png", "bmp"},
            "processor_name": "raster_image_processor",
            "dependencies": {"pillow": None},
            "critical_resources": ["process", "analyze"],
            "optional_resources": ["resize", "convert",],
        },
        {
            "supported_formats": {"svg", "ai"},
            "processor_name": "vector_image_processor",
            "dependencies": {"svgpathtools": None},
            "critical_resources": ["process", "analyze"],
            "optional_resources": ["convert", "extract_paths"],
        },
        {
            "supported_formats": {"jpg", "jpeg", "png"},
            "processor_name": "ocr_processor",
            "dependencies": {"tesseract": None, "pytesseract": None},
            "critical_resources": ["extract_text"],
            "optional_resources": ["detect_language"],
        },
        {
            "supported_formats": {"xlsx", "xlsm"},
            "processor_name": "xlsx_processor",
            "dependencies": {"openpyxl": None, "pandas": None},
            "critical_resources": ["extract_data", "extract_metadata"],
            "optional_resources": ["extract_images", "analyze"],
        },
        {
            "supported_formats": {"xls"},
            "processor_name": "xls_processor",
            "dependencies": {"xlrd": None, "pandas": None},
            "critical_resources": ["extract_data", "extract_metadata"],
            "optional_resources": ["analyze"],
        },
        {
            "supported_formats": {"yaml", "yml"},
            "processor_name": "yaml_processor",
            "dependencies": {"pyyaml": None},
            "critical_resources": ["extract_data", "process"],
            "optional_resources": ["validate", "analyze"],
        },
        {
            "supported_formats": {"toml"},
            "processor_name": "toml_processor",
            "dependencies": {"toml": None},
            "critical_resources": ["extract_data", "process"],
            "optional_resources": ["validate"],
        },
        {
            "supported_formats": {"ini", "cfg", "conf"},
            "processor_name": "config_processor",
            "dependencies": {"configparser": None},
            "critical_resources": ["extract_data", "process"],
            "optional_resources": ["validate"],
        },
        {
            "supported_formats": {"log"},
            "processor_name": "log_processor",
            "dependencies": {"re": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["analyze", "parse_timestamps"],
        },
        {
            "supported_formats": {"md", "markdown"},
            "processor_name": "markdown_processor",
            "dependencies": {"markdown": None, "mistune": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["extract_metadata", "convert_to_html"],
        },
        {
            "supported_formats": {"rst"},
            "processor_name": "rst_processor",
            "dependencies": {"docutils": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["extract_metadata", "convert_to_html"],
        },
        {
            "supported_formats": {"tex", "latex"},
            "processor_name": "latex_processor",
            "dependencies": {"pylatex": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["extract_metadata", "compile"],
        },
        {
            "supported_formats": {"sql"},
            "processor_name": "sql_processor",
            "dependencies": {"sqlparse": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["analyze", "format"],
        },
        {
            "supported_formats": {"py", "pyw"},
            "processor_name": "python_processor",
            "dependencies": {"ast": None, "tokenize": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["analyze", "extract_functions", "extract_classes"],
        },
        {
            "supported_formats": {"js", "jsx", "ts", "tsx"},
            "processor_name": "javascript_processor",
            "dependencies": {"esprima": None},
            "critical_resources": ["extract_text", "process"],
            "optional_resources": ["analyze", "minify"],
        },
    ]
    for resources in resource_list:
        yield resources
