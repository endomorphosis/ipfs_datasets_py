from types_ import Any, Callable, Configs, Content, Logger

class TextProcessor:

    def __init__(self, 
                 resources: dict[str, Callable] = None, 
                 configs: 'Configs' = None
                ) -> None:
        """Initialize the plaintext processor."""
        self.configs = configs
        self.resources = resources

        self._supported_formats: set[str] = self.resources["supported_formats"]
        self._processor_available: bool = self.resources["processor_available"]
        self._processor_name: str = self.resources["processor_name"]

        self._get_version: Callable = self.resources["get_version"]
        self._extract_structure: Callable = self.resources["extract_structure"]
        self._extract_text: Callable = self.resources["extract_text"]
        self._extract_metadata: Callable = self.resources["extract_metadata"]
        self._process: Callable = self.resources["process"]
        self._can_handle: Callable = self.resources["can_handle"]

        self._logger: Logger = self.resources["logger"]

    def __call__(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """Process plaintext content.

        Args:
            file_content: The file content to process.
            options: Processing options.
            
        Returns:
            tuple of (text content, metadata, sections).
        """
        return self.process(data, options)

    @property
    def supported_formats(self) -> set[str]:
        """Return the supported formats."""
        return self._supported_formats

    @property
    def format_extensions(self) -> set[str]:
        """Return the format extensions (same as supported formats for text processor)."""
        return self._supported_formats

    def can_process(self, file_path: str) -> bool:
        """Check if the processor can handle the given file format."""
        return self._can_handle(self.supported_formats, self.format_extensions, file_path)

    def process(self, data: str | bytes, options: dict[str, Any] = None) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """Process the provided data and return text, metadata, and sections."""
        if options is None:
            options = {}
        text, metadata, sections = self._process(data, options)
        return text, metadata, sections

    def extract_text(self, data: str | bytes, options: dict[str, Any] = None):
        """Extract text content from the provided data."""
        if options is None:
            options = {}
        return self._extract_text(data, options)

    def extract_metadata(self, data: str | bytes, options: dict[str, Any] = None):
        """Extract metadata from the provided data."""
        if options is None:
            options = {}
        return self._extract_metadata(data, options)

    def extract_structure(self, data: str | bytes, options: dict[str, Any] = None):
        """Extract structure from the provided data."""
        if options is None:
            options = {}
        return self._extract_structure(data, options)

    def processor_available(self) -> bool:
        """Check if the processor is available."""
        return self._processor_available

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return the capabilities of the processor."""
        return {
            'extract_text': {
                "available": self._extract_text is not None,
                "implementation": self._extract_text.__name__ if self._extract_text else None
            },
            'extract_metadata': {
                "available": self._extract_metadata is not None,
                "implementation": self._extract_metadata.__name__ if self._extract_metadata else None
            },
            'extract_structure': {
                "available": self._extract_structure is not None,
                "implementation": self._extract_structure.__name__ if self._extract_structure else None
            },
            'process': {
                "available": self._process is not None,
                "implementation": self._process.__name__ if self._process else None
            }
        }

    @property
    def processor_info(self) -> dict[str, Any]:
        """Get information about the processor.
        
        Returns:
            A dictionary containing processor information.
        """
        return {
            'processor_name': self._processor_name,
            'version': self.get_version(),
            'capabilities': self.capabilities,
            'supported_formats': self._supported_formats,
            'available': self._processor_available
        }

    def get_version(self) -> str:
        """
        Get the version of the processor.
        
        Returns:
            The version of the processor.
        """
        return self._get_version()
