class SupportedFormats:
    """
    Utility class for managing supported formats and their extensions.
    
    Properties:
        SUPPORTED_AUDIO_FORMATS (frozenset[str]): Set of supported audio format extensions.
        SUPPORTED_APPLICATION_FORMATS (frozenset[str]): Set of supported application format extensions.
        SUPPORTED_VIDEO_FORMATS (frozenset[str]): Set of supported video format extensions.
        SUPPORTED_IMAGE_FORMATS (frozenset[str]): Set of supported image format extensions.
        SUPPORTED_TEXT_FORMATS (frozenset[str]): Set of supported text format extensions.
        SUPPORTED_FORMATS (frozenset[str]): Set of all supported format extensions across categories.
        FORMAT_REGISTRY (dict[str, frozenset[str]]): Mapping of format categories to their supported extensions.
        FORMAT_SIGNATURES (dict[str, str]): Mapping of MIME types to format names.
        FORMAT_EXTENSIONS (dict[str, str]): Mapping of file extensions to format names.
        TEXT_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Text format names to extensions mapping.
        AUDIO_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Audio format names to extensions mapping.
        APPLICATION_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Application format names to extensions mapping.
        IMAGE_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Image format names to extensions mapping.
        VIDEO_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Video format names to extensions mapping.
    """

    def _make_frozen_set_from_frozen_set_dict(set_dict: dict[str, frozenset]) -> frozenset[str]:
        """Convert a dictionary of sets into a single set containing all unique elements."""
        frozenset_ = frozenset()
        for set_ in set_dict.values():
            frozenset_ = frozenset_.union(set_)
        return frozenset_

    # Decorator to create class properties
    class _classproperty:
        """Helper decorator to turn class methods into properties."""
        def __init__(self, func):
            self.func = func
        
        def __get__(self, instance, owner):
            return self.func(owner)

    @classmethod
    def __contains__(cls, key):
        """Check if a key is in the supported formats."""
        return key in cls.SUPPORTED_FORMATS

    # Audio formats
    @_classproperty
    def SUPPORTED_AUDIO_FORMATS(cls) -> frozenset[str]:
        """Set of supported audio formats."""
        return cls._make_frozen_set_from_frozen_set_dict(cls.AUDIO_FORMAT_EXTENSIONS)

    # Application formats
    @_classproperty
    def SUPPORTED_APPLICATION_FORMATS(cls) -> frozenset[str]:
        """Set of supported application formats."""
        return cls._make_frozen_set_from_frozen_set_dict(cls.APPLICATION_FORMAT_EXTENSIONS)

    # Video formats
    @_classproperty
    def SUPPORTED_VIDEO_FORMATS(cls) -> frozenset[str]:
        """Set of supported video formats."""
        return cls._make_frozen_set_from_frozen_set_dict(cls.IMAGE_FORMAT_EXTENSIONS)

    # Image formats
    @_classproperty
    def SUPPORTED_IMAGE_FORMATS(cls) -> frozenset[str]:
        """Set of supported image formats."""
        return cls._make_frozen_set_from_frozen_set_dict(cls.IMAGE_FORMAT_EXTENSIONS)
 
    # Text formats
    @_classproperty
    def SUPPORTED_TEXT_FORMATS(cls) -> frozenset[str]:
        """Set of supported text formats."""
        return cls._make_frozen_set_from_frozen_set_dict(cls.TEXT_FORMAT_EXTENSIONS)

    @_classproperty
    def TEXT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping format names to their supported file extensions.

        Example:
            >>> {
                "html": frozenset(("html", "htm", "xhtml", "xml")),
                "xml": frozenset(("xml",)),
                "plain": frozenset(("txt", "text")),
                "calendar": frozenset(("ics", "ical")),
                "csv": frozenset(("csv",))
            }
        """
        return { # NOTE More will be added as more formats are implemented.
            "html": frozenset(("html", "htm", "xhtml", "xml")),
            "xml": frozenset(("xml",)),
            "plain": frozenset(("txt", "text", "plain", "plaintext")),
            "calendar": frozenset(("ics", "ical")),
            "csv": frozenset(("csv",))
        }

    @_classproperty
    def AUDIO_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping audio format names to their supported file extensions.

        Example:
            >>> {
            "mp3": frozenset(("mp3", "mpeg")),
            "wav": frozenset(("wav", "x-wav")),
            "ogg": frozenset(("ogg",)),
            "flac": frozenset(("flac",)),
            "aac": frozenset(("aac",))
            }
        """
        return {
            "mp3": frozenset(("mp3", "mpeg")),
            "wav": frozenset(("wav", "x-wav")),
            "ogg": frozenset(("ogg",)),
            "flac": frozenset(("flac",)),
            "aac": frozenset(("aac",))
        }

    @_classproperty
    def APPLICATION_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping application format names to their supported file extensions.

        Example:
            >>> {
            "pdf": frozenset(("pdf",)),
            "json": frozenset(("json", "jsonl")),
            "docx": frozenset(("docx",)),
            "xlsx": frozenset(("xlsx", "xlsm", "xlsb", "xltx", "xltm")),
            "zip": frozenset(("zip",))
            }
        """
        return {
            "pdf": frozenset(("pdf",)),
            "json": frozenset(("json", "jsonl")),
            "docx": frozenset(("docx",)),
            "doc": frozenset(("doc",)),
            "xlsx": frozenset(("xlsx", "xlsm", "xlsb", "xltx", "xltm")),
            "zip": frozenset(("zip",))
        }

    @_classproperty
    def IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping image format names to their supported file extensions.
        
        Example:
            >>> {
            "jpeg": frozenset(("jpeg", "jpg")),
            "png": frozenset(("png",)),
            "gif": frozenset(("gif",)),
            "webp": frozenset(("webp",)),
            "svg": frozenset(("svg",))
            }
        """
        return {
            "jpeg": frozenset(("jpeg", "jpg")),
            "png": frozenset(("png",)),
            "gif": frozenset(("gif",)),
            "webp": frozenset(("webp",)),
            "svg": frozenset(("svg",))
        }

    @_classproperty
    def VECTOR_IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping vector image format names to their supported file extensions.

        Example:
            >>> {
            "svg": frozenset(("svg",)),
            "eps": frozenset(("eps",)),
            "ai": frozenset(("ai",))
            }
        """
        return {
            "svg": frozenset(("svg",)),
            "eps": frozenset(("eps",)),
            "ai": frozenset(("ai",))
        }

    @_classproperty
    def RASTER_IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping raster image format names to their supported file extensions.

        Example:
            >>> {
            "jpeg": frozenset(("jpeg", "jpg")),
            "png": frozenset(("png",)),
            "gif": frozenset(("gif",)),
            "webp": frozenset(("webp",))
            }
        """
        return frozenset(("jpeg", "jpg", "png", "gif", "webp"))

    # Video formats
    @_classproperty
    def VIDEO_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping video format names to their supported file extensions.

        Example:
            >>> {
            "mp4": frozenset(("mp4",)),
            "webm": frozenset(("webm",)),
            "avi": frozenset(("avi",)),
            "mkv": frozenset(("mkv",)),
            "mov": frozenset(("mov",))
            }
        """
        return {
            "mp4": frozenset(("mp4",)),
            "webm": frozenset(("webm",)),
            "avi": frozenset(("avi",)),
            "mkv": frozenset(("mkv",)),
            "mov": frozenset(("mov",))
        }

    @_classproperty
    def FORMAT_REGISTRY(cls) -> dict[str, frozenset[tuple[str]]]:
        """ A dictionary mapping format names to sets of supported file extensions.

        Example:
            >>> {
                "audio": {"mp3", "wav", "ogg", "flac", "aac"},
                "video": {"mp4", "webm", "avi", "mkv", "mov"},
                "image": {"jpeg", "jpg", "png", "gif", "webp", "svg+xml"},
                "text": {"html", "xml", "plaintext", "calendar", "csv"},
                "application": {"pdf", "json", "docx", "xlsx", "zip"}
            }
        """
        return {
            "audio": cls.SUPPORTED_AUDIO_FORMATS,
            "video": cls.SUPPORTED_VIDEO_FORMATS,
            "image": cls.SUPPORTED_IMAGE_FORMATS,
            "text": cls.SUPPORTED_TEXT_FORMATS,
            "application": cls.SUPPORTED_APPLICATION_FORMATS
        }

    @_classproperty
    def EBOOK_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping ebook format names to their supported file extensions.

        Example:
            >>> {
                "epub": frozenset(("epub",)),
                "mobi": frozenset(("mobi",))
            }
        """
        return frozenset(("epub", "mobi"))

    @_classproperty
    def HTML_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """Set of supported HTML formats."""
        return cls.TEXT_FORMAT_EXTENSIONS['html']

    @_classproperty
    def PLAINTEXT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """Set of supported plaintext formats."""
        return cls.TEXT_FORMAT_EXTENSIONS['plain']

    @_classproperty
    def DOCUMENT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
        """A dictionary mapping document format names to their supported file extensions.

        Example:
            >>> {
                "docx": frozenset(("docx",)),
                "doc": frozenset(("doc",))
            }
        """
        return frozenset(("docx","doc",)) # TODO Add more document formats as needed,

    @_classproperty
    def XML_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
        """Set of supported XML formats."""
        return cls.TEXT_FORMAT_EXTENSIONS['xml']

    @_classproperty
    def CALENDAR_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
        """Set of supported calendar formats."""
        return cls.TEXT_FORMAT_EXTENSIONS['calendar']

    @_classproperty
    def CSV_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
        """Set of supported CSV formats."""
        return cls.TEXT_FORMAT_EXTENSIONS['csv']

    @_classproperty
    def TRANSCRIPTION_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
        """Set of supported transcription formats."""
        return frozenset(("srt", "vtt", "ass",)) # hehe 

    @_classproperty
    def ARCHIVE_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
        """Set of supported ZIP formats."""
        return frozenset((
            "zip", "tar", "gz", "bz2", "xz", "7z", "rar",
            "tar.gz", "tar.bz2", "tar.xz", "tar.7z",
        ))

    @_classproperty
    def SUPPORTED_FORMATS(cls) -> set[str]:
        """A set of all supported mime-type formats across categories.

        Example:
            >>> {
                "mp3", "wav", "ogg", "flac", "aac",
                "mp4", "webm", "avi", "mkv", "mov",
                "jpeg", "jpg", "png", "gif", "webp", "svg+xml",
                "html", "xml", "plain", "calendar", "csv",
                "pdf", "json", "docx", "xlsx", "zip"
            }
        """
        _supported_formats = set()
        for _, frozenset_ in cls.FORMAT_REGISTRY.items():
            mutable_set = set(frozenset_)  # Convert to a mutable set for updating
            _supported_formats.update(mutable_set)

        return cls._make_frozen_set_from_frozen_set_dict(cls.FORMAT_REGISTRY)

    @_classproperty
    def FORMAT_SIGNATURES(cls) -> dict[str, set[str]]:
        """
        Map of MIME types to formats

        Example:
            {
            'text/html': 'html',
            'application/xhtml+xml': 'html',
            ...
            }
        """
        return {
            # Text formats
            'text/html': 'html',
            'application/xhtml+xml': 'html', # TODO figure out which processor to use: html or xml
            'text/xml': 'xml',
            'application/xml': 'xml',
            'application/atom+xml': 'xml',
            'application/rss+xml': 'xml',
            'application/ld+json': 'json',
            'application/rdf+xml': 'xml',
            'application/vnd.wap.xhtml+xml': 'xml',
            'application/vnd.mozilla.xul+xml': 'xml',


            'text/plain': 'plain',
            'text/calendar': 'calendar',
            'application/ics': 'calendar',  # Added from PROCESSOR_MIME_TYPE_MAP
            'text/csv': 'csv',
            'text/comma-separated-values': 'csv',  # Added from PROCESSOR_MIME_TYPE_MAP
            'text/tab-separated-values': 'csv',   # Added from PROCESSOR_MIME_TYPE_MAP
            
            # Image formats
            'image/jpeg': 'jpeg',
            'image/jpg': 'jpeg',
            'image/png': 'png',
            'image/gif': 'gif',
            'image/webp': 'webp',
            'image/svg+xml': 'svg', #TODO figure out which processor to use: xml or svg 
            
            # Audio formats
            'audio/mpeg': 'mp3',
            'audio/mp3': 'mp3',
            'audio/wav': 'wav',
            'audio/x-wav': 'wav',
            'audio/ogg': 'ogg',
            'audio/flac': 'flac',
            'audio/aac': 'aac',
            
            # Video formats
            'video/mp4': 'mp4',
            'video/webm': 'webm',
            'video/x-msvideo': 'avi',
            'video/avi': 'avi',  # Added from MIME_TYPE_TO_FORMAT_MAP
            'video/x-matroska': 'mkv',
            'video/mkv': 'mkv',  # Added from MIME_TYPE_TO_FORMAT_MAP
            'video/quicktime': 'mov',
            'video/mov': 'mov',  # Added from MIME_TYPE_TO_FORMAT_MAP
            
            # Application formats
            'application/pdf': 'pdf',
            'application/json': 'json',
            'application/zip': 'zip', # NOTE zip is for Archive/Compression formats
            'application/gzip': 'zip',
            'application/x-gzip': 'zip',
            'application/x-zip-compressed': 'zip',
            'application/x-7z-compressed': 'zip',  # # Via 7-zip
            'application/vnd.rar': 'zip',  # Via 7-zip
            'application/x-rar-compressed': 'zip', # Via 7-zip
            'application/x-bzip2': 'zip',  # Via 7-zip
            'application/x-tar': 'zip',  # Via 7-zip
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx'
        }

    @_classproperty
    def FORMAT_EXTENSIONS(cls) -> dict[str, str]:
        """
        Map of file extensions to formats

        Example:
            >>> {
                '.html': 'html',
                '.xml': 'xml',
                '.txt': 'plain',
                ...
                }
        """
        return {
            # Text formats
            ".html": "html",
            ".htm": "html",
            ".xhtml": "html",
            ".xml": "xml",
            ".txt": "plaintext",
            ".ics": "calendar",
            ".csv": "csv",
            
            # Image formats
            ".jpeg": "jpeg",
            ".jpg": "jpg",
            ".png": "png",
            ".gif": "gif",
            ".webp": "webp",
            ".svg": "svg",
            
            # Audio formats
            ".mp3": "mp3",
            ".wav": "wav",
            ".ogg": "ogg",
            ".flac": "flac",
            ".aac": "aac",
            
            # Video formats
            ".mp4": "mp4",
            ".webm": "webm",
            ".avi": "avi",
            ".mkv": "mkv",
            ".mov": "mov",

            # Application formats
            ".pdf": "pdf",
            ".json": "json",
            ".zip": "zip"
        }

    ###########################################################################
    #### Unimplemented formats from ROADMAP (MIME types not yet supported) ####
    ###########################################################################

    # Unimplemented formats from ROADMAP (MIME types not yet supported)
    @_classproperty
    def UNIMPLEMENTED_APPLICATION_FORMATS_SET(cls) -> set[str]:
        """
        Returns a set of application formats that are not currently supported by the converter.
        """
        return {
            "x-bzip", # TODO Figure out how bzip can be implemented 
            "x-freearc", # TODO freearc has been discontinued, figure out how to implement it
            # Document formats - Microsoft Office
            "msword", # TODO This is a legacy format, need a specific handler for it
            
            "vnd.ms-excel", "vnd.ms-powerpoint", "vnd.ms-word",
            "vnd.openxmlformats-officedocument.presentationml.presentation",
            # Document formats - OpenDocument
            "vnd.oasis.opendocument.presentation", "vnd.oasis.opendocument.spreadsheet",
            "vnd.oasis.opendocument.text",
            # Document formats - Other
            "rtf", "postscript", "x-abiword", "x-tex", "x-troff-man",
            # eBook formats
            "epub+zip", "vnd.amazon.ebook", "x-mobipocket-ebook",

            # JavaScript/Programming formats
            "javascript", "x-javascript", "x-json", "x-httpd-php",
            # Geographic/Mapping formats
            "vnd.google-earth.kml+xml", "vnd.google-earth.kmz",
            # Calendar/Time formats
            "calendar", "ics",
            # Media/Multimedia formats
            "ogg", "x-shockwave-flash",
            # Security/Encryption formats
            "pgp-encrypted", "pgp-signature",
            # System/Binary formats
            "octet-stream", "octetstream", "x-msdownload", "vnd.android.package-archive",
            "vnd.apple.installer+xml", "x-debian-package",
            # Script/Shell formats
            "x-csh", "x-sh",
            # Scientific/Data formats
            "marc", "x-netcdf", "x-cdf", "x-endnote-refer", "x-research-info-systems",
            "x-bibtex",
            # Download/Transfer formats
            "download", "force-download", "save-to-disk", "x-download",
            # Application/Specialized formats
            "java-archive", "x-java-jnlp-file", "x-bittorrent", "vnd.visio", "text"
        }

    @_classproperty
    def UNIMPLEMENTED_AUDIO_FORMATS_SET(cls) -> set[str]:
        return {
            # Mobile/3GPP formats
            "3gpp", "3gpp2",
            # MIDI formats
            "midi", "x-midi",
            # Playlist/Streaming formats
            "x-mpegurl", "x-scpls",
            # Container formats
            "webm"
        }

    @_classproperty
    def UNIMPLEMENTED_VIDEO_FORMATS_SET(cls) -> set[str]:
        return {
            # Mobile/3GPP formats
            "3gpp", "3gpp2",
            # MPEG variants
            "mp2t", "mpeg", 
            # Container/Streaming formats
            "ogg", "x-ms-asf", "x-msvideo"
        }

    @_classproperty
    def UNIMPLEMENTED_IMAGE_FORMATS_SET(cls) -> set[str]:
        return {
            # Animated formats
            "apng",
            # Next-gen formats
            "avif",
            # Legacy/Common formats
            "bmp", "tiff",
            # JPEG variants
            "jp2", "pjpeg",
            # Specialized formats
            "vnd.djvu", "vnd.microsoft.icon"
        }

    @_classproperty
    def UNIMPLEMENTED_TEXT_FORMATS_SET(cls) -> set[str]:
        return {
            # Web/Styling formats
            "css", "javascript",
            # Programming/Source code formats
            "x-c", "x-csrc", "x-perl",
            # Data/Structured formats
            "tab-separated-values", "turtle", "x-bibtex",
            # Contact/Calendar formats
            "vcard", "x-vcalendar", "x-vcard",
            # Document/File formats
            "directory", "enriched", "prs.lines.tag",
            # Development/Patch formats
            "x-diff", "x-patch"
        }

    # Additional unimplemented formats not in main MIME categories
    @_classproperty
    def UNIMPLEMENTED_BINARY_FORMATS_SET(cls) -> set[str]:
        return {
            "octet-stream"
        }

    @_classproperty
    def UNIMPLEMENTED_MESSAGE_FORMATS_SET(cls) -> set[str]:
        return {
            "rfc822"
        }

    @_classproperty
    def ALL_ROADMAP_FORMATS(cls) -> set[str]:
        """All formats from ROADMAP.md (implemented + unimplemented)"""
        return {
            # Get all unique format extensions from supported sets
            *cls.SUPPORTED_APPLICATION_FORMATS,
            *cls.SUPPORTED_AUDIO_FORMATS,
            *cls.SUPPORTED_IMAGE_FORMATS,
            *cls.SUPPORTED_TEXT_FORMATS,
            *cls.SUPPORTED_VIDEO_FORMATS,
            # Get all unimplemented formats
            *cls.UNIMPLEMENTED_APPLICATION_FORMATS_SET,
            *cls.UNIMPLEMENTED_AUDIO_FORMATS_SET,
            *cls.UNIMPLEMENTED_IMAGE_FORMATS_SET,
            *cls.UNIMPLEMENTED_TEXT_FORMATS_SET,
            *cls.UNIMPLEMENTED_VIDEO_FORMATS_SET,
            *cls.UNIMPLEMENTED_BINARY_FORMATS_SET,
            *cls.UNIMPLEMENTED_MESSAGE_FORMATS_SET
        }

    @classmethod
    def __getitem__(cls, name: str) -> bool:
        """Get a supported format by name."""
        try:
            return getattr(cls, name)
        except AttributeError as e:
            raise KeyError(f"Supported format '{name}' not found in SupportedFormats.") from e

    @classmethod
    def get(cls, name: str, default: bool = False) -> bool:
        """
        Get a supported format by name with a default value.
        
        Args:
            name: The name of the supported format.
            default: The default value to return if the supported format is not found.
        
        Returns:
            The supported format if found, otherwise the default value.
        """
        return getattr(cls, name, default)

    @classmethod
    def keys(cls) -> list[str]:
        """
        Get a list of all supported format names.
        
        Returns:
            A list of supported format names.
        """
        return [
            name for name in dir(cls) 
            if not name.startswith('_') # Check if it's not a private attribute
            and hasattr(cls._classproperty, name) # Check for class properties decorator
        ]

    @classmethod
    def items(cls) -> list[tuple[str, bool]]:
        """
        Get a list of all supported formats as (name, format) tuples.
        
        Returns:
            A list of tuples containing supported format names and their corresponding objects.
        """
        return [
            (name, getattr(cls, name)) # Check if the attribute exists. The second part of each tuple must be a boolean
            for name in cls.keys()
        ]

    def __contains__ (cls, item: str) -> bool:
        """
        Check if a format is supported (e.g. can be processed).
        
        Args:
            item: The name of the supported format.
        
        Returns:
            Boolean: True if the format is supported, else False.
        """
        return item in cls.keys()
