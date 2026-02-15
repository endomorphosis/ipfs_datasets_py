"""
Output formatter module for the Omni-Converter.

This module provides the OutputFormatter class for formatting extracted normalized content
into different output formats.
"""
import json
import os
from datetime import datetime

from types_ import (
    Any,
    Callable,
    #Configs,
    #Content,
    FormatterFunc,
    FormattedOutput,
    Logger,
    Optional,
    Type,
    NormalizedContent,
)


from core.content_extractor._content import Content
from configs import Configs
import inspect


class OutputFormatter:
    """
    Output formatter for the Omni-Converter.
    
    This class formats extracted normalized content into different output formats.
    
    Attributes:
        resources (dict[str, Callable]): Dictionary of callable objects and dependencies.
        configs (Configs): Configuration settings.
        output_formats (dict[str, FormatterFunc]): Dictionary of formatter functions.
        default_format (str): The default output format.
    
    Properties:
        available_formats (list[str]): List of available output formats.
    
    Public Methods:
        format_output: Format normalized content for output in specified format.
        register_format: Register a new output format with formatter function.
    
    Private Methods:
        _register_default_formatters: Register the default output formatters.
        _format_as_txt: Format normalized content as plain text.
        _format_as_json: Format normalized content as JSON.
        _format_as_markdown: Format normalized content as Markdown.
    """
    
    def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
        """
        Initialize an output formatter.
        
        Args:
            resources: A dictionary of callable objects and dependencies.
            configs: A pydantic model containing configuration settings.
        """
        self.resources = resources
        self.configs = configs
        
        # Extract required resources
        self._normalized_content = self.resources["normalized_content"]
        self._formatted_output = self.resources["formatted_output"]
        self._logger: Logger = self.resources["logger"]

        self.default_format = self.configs.output.default_format

        self._type_normalized_content: Type = type(self.resources["normalized_content"])
        
        self.output_formats: dict[str, FormatterFunc] = {}
        
        # Register default formatters
        self._register_default_formatters()


    def _register_default_formatters(self) -> None:
        """Register the default output formatters."""
        self._logger.debug("Registering default output formatters")
        
        # Clear existing formatters to avoid duplicates
        self.output_formats = {}
        
        # Register standard formats
        self.output_formats["txt"] = self._format_as_txt
        self.output_formats["json"] = self._format_as_json
        self.output_formats["md"] = self._format_as_markdown

        # Log the registered formats
        self._logger.debug(f"Registered output formats: {', '.join(self.output_formats.keys())}")


    def _format_as_txt(self, output_dict: dict) -> str:
        """Format normalized content as plain text.
        
        Args:
            normalized_content: The normalized content to format.
            
        Returns:
            The formatted normalized content as plain text.
        """
        src_path = output_dict['source_path']  # NOTE Key must be present.
        original_text = output_dict.get('text', '')
        metadata = output_dict.get('metadata', {})
        normalized = output_dict.get('normalized_by', [])
        sections = output_dict.get('sections', [])

        text = ""
        if not original_text:
            # If no text is available, return an empty string
            self._logger.warning(f"No text content available for {src_path}")
            return ""

        # Start with a header including the source file
        text += f"Source path: {src_path}\n"

        if metadata:
            # If metadata is available, include it in the text
            text += "\nMetadata:\n"
            for key, value in metadata.items():
                text += f"{key}: {value}\n"
            text.lstrip("\n")  # Remove leading newline

        if sections:
            # If sections are available, include them in the text
            text += "\nSections:\n"
            for section in sections:
                for key, value in section.items():
                    if key != 'output_dict':
                        text += f"{key}: {value}\n"
            text.lstrip("\n")  # Remove leading newline

        normalized = output_dict.get('normalized_by', [])
        if normalized:
            # If normalized content is normalized, include normalization info
            text += "\nNormalized by: " + ", ".join(normalized)

        # If no metadata, sections, or normalization info, just add a newline
        text += "Content\n\n" if metadata or sections or normalized else "\n"
        text += original_text
        return text


    def _format_as_json(self, output_dict: dict) -> str:
        """Format normalized content as JSON.
        
        Args:
            output_dict: The normalized content to format.
            
        Returns:
            The formatted normalized content as JSON.
        """
        return json.dumps(output_dict, indent=2, default=self._json_serializer)


    @staticmethod
    def _json_serializer(obj):
        """JSON serializer for objects not serializable by default json code"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


    def _format_as_markdown(self, output_dict: dict) -> str:
        """Format normalized content as Markdown.
        
        Args:
            output_dict: The normalized content to format.
            
        Returns:
            The formatted normalized content as Markdown.
        """
        src_path = output_dict['source_path'] # NOTE Key must be present.
        original_text = output_dict.get('text', '')
        metadata = output_dict.get('metadata', {})
        normalized = output_dict.get('normalized_by', [])
        sections = output_dict.get('sections', [])

        if not original_text:
            # If no text is available, return an empty string
            self._logger.warning(f"No text content available for {src_path}")
            return ""

        # Start with a header including the source file
        md = f"# Content from {os.path.basename(src_path)}\n\n"
        
        # Add metadata section
        if metadata:
            md += "## Metadata\n\n"
            for key, value in metadata.items():
                md += f"- **{key}**: {value}\n"
            md += "\n"

        # Add normalized_content sections if available
        if sections:
            md += "## Sections\n\n"
            for section in sections:
                section_type = section.get('type', 'Section')
                section_title = section.get('title', section_type)
                section_content = section.get('output_dict', '')
                
                md += f"### {section_title}\n\n"
                md += f"{section_content}\n\n"

        # Add normalization info if available
        if normalized:
            md += "## Normalization\n\n"
            md += "Applied normalizers:\n\n"
            for normalizer in normalized:
                md += f"- {normalizer}\n"
            md += "\n"

        # Add main normalized_content
        md += "## Content\n\n"
        md += original_text

        return md

    def _merge_into_metadata(self, normalized_content: Any) -> None:
        for attr in dir(normalized_content):
            if not attr.startswith('_') and attr not in ['content', 'normalized_by']:
                # Check if the attribute is a property or method
                attr_value = getattr(normalized_content, attr)
                if callable(attr_value):
                    # If it's a method, we skip it
                    continue
                print(attr)

    def format_output(
        self,
        normalized_content: Content,
        format: Optional[str] = None,
        options: Optional[dict[str, Any]] = None,
        output_path: Optional[str] = None
    ) -> FormattedOutput:
        """
        Format normalized content for output.
        
        Args:
            normalized_content: The normalized content to format.
            format: The output format. If None, the default format is used.
            options: Optional formatting options.
            output_path: The path where the output will be written.
            
        Returns:
            The formatted output.
            
        Raises:
            ValueError: If the specified format is not supported.
        """
        output_dict = {}
        src_path = ""
        src_format = ""
        required_attributes = ['text', 'metadata', 'sections', 'source_path', 'source_format', 'extraction_time']

        # Check if we got an invalid format.
        if format is not None and isinstance(format, str):
            if format not in self.output_formats:
                self._logger.error(f"Unsupported format: {format}")
                raise ValueError(f"Unsupported format: {format}")

        self._merge_into_metadata(normalized_content)

        # Turn content into a dictionary.
        try:
            output_dict = normalized_content.content.to_dict()
        except AttributeError as e:
            # Try accessing the content directly
            output_dict = normalized_content.to_dict()

        output_dict['normalized_by'] = getattr(normalized_content, 'normalized_by', [])

        # Make sure all the required keys are present
        for attr in required_attributes:
            if attr not in output_dict.keys():
                self._logger.error(f"Missing required attribute '{attr}' in normalized content")
                raise AttributeError(f"Missing required attribute '{attr}' in normalized content")

        try:
            src_path = output_dict['source_path']
            src_format = output_dict['source_format']
            extract_time = output_dict['extraction_time']
        except (AttributeError, KeyError) as e:
            self._logger.error(f"Attribute error accessing content in normalized content: {e}")
            raise AttributeError(f"Invalid normalized content: {e}") from e

        # Use the default format if none is specified
        output_format = format or self.default_format
        self._logger.debug(f"Formatting output for {src_path}", {'format': output_format})

        # Try to get from options if not directly specified
        if output_format not in self.output_formats and options and 'format' in options:
            output_format = options['format']

        # If still not valid, default to txt
        if output_format not in self.output_formats:
            self._logger.warning(f"Unsupported format: {output_format}, defaulting to {self.default_format}")
            output_format = self.default_format

        try:
            # Format the normalized content
            formatter = self.output_formats[output_format]
            formatted_content = formatter(output_dict)

            self._logger.debug(f"Formatted normalized content for {src_path} in {output_format} format\n{formatted_content}")

            # Create formatted output
            return  self._formatted_output(
                content=formatted_content,
                format=output_format,
                metadata={
                    'source_format': src_format,
                    'source_path': src_path,
                    'extraction_time': extract_time.isoformat() if isinstance(extract_time, datetime) else extract_time,
                    **(options or {})
                },
                output_path=output_path
            )
        except (OverflowError, MemoryError) as e:
            self._logger.error(f"Error formatting output for {src_path} in {output_format} format: {e}")
            raise ValueError(f"Error formatting output: {e}") from e
        except AttributeError as e:
            self._logger.error(f"Attribute error formatting output for {src_path} in {output_format} format: {e}")
            raise AttributeError(f"Attribute error formatting output: {e}")
        except Exception as e:
            self._logger.exception(f"Unexpected error formatting output for {src_path} in {output_format} format: {e}")
            raise ValueError(f"Unexpected error formatting output: {e}") from e


    def register_format(self, format_name: str, formatter: FormatterFunc) -> None:
        """Register an output format.

        Args:
            format_name: The name of the format.
            formatter: The formatter function.
            
        Raises:
            TypeError: If the formatter is not a callable function or has an incorrect signature.
            ValueError: If a formatter for the format already exists.
        """
        if not isinstance(formatter, Callable):
            raise TypeError("Formatter must be a callable function")

        # Check if the function has the correct signature
        # It needs 1) single positional argument with type dict 2) returns a string
        sig = inspect.signature(formatter)
        params = list(sig.parameters.values())

        if len(params) != 1:
            raise TypeError(f"Formatter function must have exactly 1 parameter, got {len(params)}")

        param = params[0]
        if param.annotation != dict and param.annotation != inspect.Parameter.empty:
            raise TypeError(f"Formatter function parameter must be of type dict, got {param.annotation}")

        if sig.return_annotation != str and sig.return_annotation != inspect.Parameter.empty:
            raise TypeError(f"Formatter function must return str, got {sig.return_annotation}")

        if format_name in self.output_formats:
            raise ValueError(f"A formatter for '{format_name}' already exists")

        self.output_formats[format_name] = formatter
        self._logger.debug(f"Registered output format: {format_name}")


    @property
    def available_formats(self) -> list[str]:
        """
        Get the available output formats.
        
        Returns:
            List of available output formats.
        """
        return list(self.output_formats.keys())
