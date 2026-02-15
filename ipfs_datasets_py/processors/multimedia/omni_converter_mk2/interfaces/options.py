import argparse
from enum import StrEnum
from pathlib import Path
from typing import Optional, Any, Annotated as Ann


try:
    from pydantic import (
        BaseModel, 
        Field, 
        PositiveInt, 
        AfterValidator as AV, 
        DirectoryPath,
        FilePath,
        PositiveFloat,
        NonNegativeFloat,
        ValidationError
    )
except ImportError:
    raise ImportError("Pydantic is required for the Python API.")


from utils.hardware import Hardware


# def _validate_format(format: str) -> str:
#     """Validate the output format option.

#     Args:
#         format: The output format string.

#     Returns:
#         The validated output format string.

#     Raises:
#         ValueError: If the format is not supported.
#     """
#     supported_formats = ["txt", "md"]
#     if format not in supported_formats:
#         raise ValueError(f"Unsupported output format: {format}. Supported formats are: {supported_formats}")
#     return format

def _validate_max_workers(max_threads: PositiveInt) -> PositiveInt:
    """Validate the maximum number of worker threads.

    Returns:
        The validated maximum number of worker threads.

    Raises:
        ValueError: If the maximum number of workers is less than 1.
    """
    if Hardware.get_num_cpu_cores() < max_threads:
        raise ValueError("Maximum number of workers must be less than or equal to the number of physical CPU cores.")
    return max_threads

def _validate_max_memory(max_memory: PositiveInt) -> PositiveInt:
    """Validate the maximum memory usage in GB.

    Args:
        max_memory: The maximum memory usage in GB.

    Returns:
        The validated maximum memory usage in GB.

    Raises:
        ValueError: If the maximum memory is greater than the system's memory.
    """
    if Hardware.get_total_memory_in_gb() < max_memory:
        raise ValueError(
            f"Maximum RAM usage is set to {max_memory}GB, but current RSS usage is {Hardware.get_total_memory_in_gb()}MB."
            "Please increase the maximum memory limit."
        )
    return max_memory

def _validate_max_vram(max_vram: PositiveInt) -> PositiveInt:
    """Validate the maximum VRAM usage in GB.)

    Args:
        max_vram: The maximum VRAM usage in GB.

    Returns:
        The validated maximum VRAM usage in GB.

    Raises:
        ValueError: If the maximum VRAM is less than 1MB.
    """
    # TODO Implement VRAM usage validation when CUDA hardware checker is available.
    # if Hardware.get_memory_vms_usage_in_mb() > max_vram:
    #     raise ValidationError(
    #         f"Maximum VRAM usage is set to {max_vram}MB, but current VMS usage is {Hardware.get_memory_vms_usage_in_mb()}MB."
    #         "Please increase the maximum VRAM limit."
    #     )
    return max_vram


def name(e: Exception) -> str:
    """Get the string name of the error."""
    return type(e).__name__

def getitem(self, key: str) -> str | int | float:
    try:
        return getattr(self, key)
    except AttributeError as e:
        raise KeyError(f"Key '{key}' not found in configuration: {e}") from e

def setitem(self, key: str, value: Any) -> None:
    try:
        setattr(self, key, value)
        self.model_validate()
    except ValidationError as e:
        raise ValueError(f"Invalid value for key '{key}': {value}") from e
    except TypeError as e:
        raise TypeError(f"Invalid type for key '{key}': {type(value)}") from e
    except AttributeError as e:
        raise KeyError(f"Key '{key}' not found in configuration") from e



class OutputFormat(StrEnum):
    """Enumeration for supported output file formats."""
    TXT = "txt"
    MD = "md"
    JSON = "json"


class Options(BaseModel):
    """Options for the Omni-Converter.

    These options are intended to validate argparse arguments 
    and provide a structured way to manage conversion settings.

    Attributes:
        input: The input file(s) or directory to convert.
        output: Output directory for the converted content.
        walk: Process directories recursively, including all subdirectories.
        normalize: Normalize text before saving.
        security_checks: Check input files for malicious aspects.
        metadata: Extract metadata from input files.
        structure: Extract structural elements from input files.
        format: Output format for the converted text.
        max_threads: Maximum number of threads for parallel processing.
        max_memory: Maximum memory usage (GB).
        max_vram: Maximum VRAM usage (GB).
        budget_in_usd: Budget in USD for priced API calls.
        normalizers: Text normalizers to apply (comma-separated).
        max_cpu: Maximum CPU usage percentage.
        quality_threshold: Quality filtering threshold (0-1).
        continue_on_error: Continue processing files even if some fail.
        parallel: Enable parallel document processing.
        follow_symlinks: Follow symbolic links when processing directories.
        include_metadata: Include file metadata in output.
        lossy: Relax quality threshold for large/complex files.
        normalize_text: Normalize text output.
        sanitize: Sanitize output files.
        show_options: Show current options and exit.
        show_progress: Show progress bar during batch operations.
        verbose: Log detailed information during processing.
        list_formats: List supported input formats and exit.
        list_normalizers: List supported text normalizers and exit.
        list_output_formats: List supported output formats and exit.
        version: Show version information and exit.
        max_batch_size: Maximum number of files to process in a single batch.
        retries: Maximum number of retries for failed conversions.
    """
    # TODO Figure out why adding aliases overrides the field names.
    input:             DirectoryPath | FilePath | list[FilePath] = Field(..., description="The input file(s) or directory to convert")
    output:            DirectoryPath = Field(default_factory=Path.home, description="Output directory for the converted content. Defaults to home directory")
    walk:              bool = Field(default=False, description="If input is a directory, process it recursively, including all subdirectories")
    normalize:         bool = Field(default=True, description="Normalize text before saving (e.g., remove extra whitespace, convert to lowercase, etc.)")
    security_checks:   bool = Field(default=True, description="Check the input files for malicious aspects. Ex: malware, zip bombs, etc. Disable at your own risk")
    metadata:          bool = Field(default=True, description="""
        Whether to extract metadata from input files and append it to the converted text. 
        The exact metadata extracted depends on the input file format. 
        For example, Excel metadata includes computed field formulas, while PDF metadata includes booleans for whether the pd is flattened or not.
        See the documentation for more details on the metadata extracted for each format.
    """)
    structure:         bool = Field(default=True, description="Extract structural elements from the input files and append it to the converted text. Ex: headings, lists, etc.")
    format:            OutputFormat = Field(default=OutputFormat.TXT, description="Output format for the converted text. Options are: 'txt', 'md', 'json'")
    max_threads:       Ann[PositiveInt, AV(_validate_max_workers)] = Field(default=4, description="Maximum number of threads to use during parallel processing")  # At least one worker thread
    max_memory:        Ann[PositiveInt, AV(_validate_max_memory)]  = Field(default=6, description="Maximum memory usage (GB). Cannot exceed the system's total physical RAM.") # 6GB in MB
    max_vram:          Ann[PositiveInt, AV(_validate_max_vram)]    = Field(default=6, description="Maximum VRAM usage (GB). Cannot exceed your graphics card's total VRAM.")  # 6GB in MB
    budget_in_usd:     NonNegativeFloat = Field(default=0.00, description="Budget in USD for priced API calls and cloud processing. NOTE: Setting this to 0 will disable certain dependencies (e.g. OpenAI, Anthropic, etc.).")  # Budget for cloud processing
    normalizers:       Optional[str] = Field(default=None, description="Specifies which text normalizers to apply (comma-separated)")
    max_cpu:           PositiveInt = Field(default=80, le=100, description="Maximum CPU usage allowed during processing (percentage)")
    quality_threshold: NonNegativeFloat = Field(default=0.9, le=1.0, description="Arbitrary threshold for quality filtering. Range is a float from 0 to 1, where 0 is no filtering and 1 is strict filtering. Default is 0.9.")
    continue_on_error: bool = Field(default=True, description="Whether to continue processing files even if some fail")
    parallel:          bool = Field(default=False, description="Enables parallel document processing")  # TODO Implement parallel processing.
    follow_symlinks:   bool = Field(default=False, description="Whether to follow symbolic links when processing directories")
    include_metadata:  bool = Field(default=True, description="Whether to include file metadata in the output")
    lossy:             bool = Field(default=False, description="Relax the quality threshold for large/complex files and formats")
    normalize_text:    bool = Field(default=True, description="Whether to normalize text (e.g., remove extra whitespace, convert to lowercase, etc.)")
    sanitize:          bool = Field(default=True, description="Whether to sanitize output files (e.g. remove executable code, personal information, etc.)")
    show_options:      bool = Field(default=False, description="Show current options and exit")
    show_progress:     bool = Field(default=False, description="Show a progress bar during batch operations")  # TODO Unused argument. Implement.
    verbose:           bool = Field(default=False, description="Log detailed information during processing")
    list_formats:      bool = Field(default=False, description="List supported input formats and exit")
    list_normalizers:  bool = Field(default=False, description="List supported text normalizers and exit")
    list_output_formats: bool = Field(default=False, description="List supported output formats and exit")
    version:           bool = Field(default=False, description="Show version information and exit")
    max_batch_size:    PositiveInt = Field(default=100, description="Maximum number of files to process in a single batch.")  # TODO Make this dynamic somehow?
    retries:           PositiveInt = Field(default=0, description="Maximum number of retries for failed conversions")


    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary.

        Returns:
            A dictionary representation of the options.
        """
        model = self.model_dump()
        print(f"model: {model}")
        return model

    def print_options(self, type_: str = "defaults", return_string: bool = False) -> Optional[str]:
        """Pretty-print the options in a human-readable format.
        
        Args:
            type_: Type of options to print ('defaults', 'current', or 'argparse').
            Defaults will show the default values for each option.
            Current will show the current values set in the instance.

        Raises:
            ValueError: If an invalid type is specified.
        """
        string = ""
        match type_:
            case "current":
                title = "Current Options:\n"
                for name, field in self.items():
                    value = getattr(self, name)
                    description = field.description or "No description available"
                    string = f"{name}: {value} (Default: {field.get_default()})\n"
            case "defaults":
                title = "Default Options:\n"
                for name, field in self.items():
                    description = field.description or "No description available"
                    string += f"{name}: {description} (Default: {field.get_default()})\n"
            case "argparse":
                title = "Argparse Options:\n"
                for name, field in self.items():
                    description = field.description or "No description available"
                    string = f"{name}: {description} (Default: {field.get_default()})\n"
            case _:
                raise ValueError("Invalid type specified. Use 'defaults', 'current', or 'argparse'.")
        print(title, string)
        if return_string:
            return string

    def add_arguments_to_parser(self, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        """Assign the options to an argparse parser.

        Args:
            parser: The argparse parser to assign the options to.
            
        Returns:
            The configured argparse parser.
        """
        for name, field in self.items():
            # Get the actual default value
            if hasattr(field, 'default_factory') and field.default_factory is not None:
                default = field.default_factory()
            elif field.default is not None:
                default = field.default
            else:
                default = None

            # Handle different field types for argparse
            arg_kwargs = {
                'help': field.description,
                'default': default
            }

            # Handle type conversion based on annotation
            annotation =  field.annotation
            if annotation == bool:
                # For boolean fields, use store_true/store_false
                arg_kwargs['action'] = 'store_false' if default is True else 'store_true'
                del arg_kwargs['default'] # Remove default for action arguments
            elif hasattr(annotation, '__origin__') and annotation.__origin__ == list:
                # Handle list types
                arg_kwargs['nargs'] = '*'
                arg_kwargs['type'] = str  # Convert to strings, validation happens in Pydantic
            elif annotation == OutputFormat:
                # Handle enum types
                arg_kwargs['choices'] = [e.value for e in OutputFormat]
                arg_kwargs['type'] = str
            elif annotation in (DirectoryPath, FilePath):
                # Handle path types
                arg_kwargs['type'] = str
            elif annotation in (PositiveInt, int):
                arg_kwargs['type'] = int
            elif annotation in (PositiveFloat, NonNegativeFloat, float):
                arg_kwargs['type'] = float
            else:
                # Default to string type
                arg_kwargs['type'] = str

            # For required fields (no default), make them positional or required
            if name == 'input' and default is None:
                # Make input a positional argument or mark as required
                arg_kwargs['required'] = True

            # Add the argument
            flags = (f"--{field.alias}", f"-{field.alias[0]}",) if field.alias else (f"--{name}",)
            parser.add_argument(*flags, **arg_kwargs)

        return parser

    def keys(self) -> list[str]:
        """Get the keys of the options."""
        return list(self.model_fields.keys())

    def values(self) -> list[str | int | float]:
        """Get the values of the options."""
        return [getattr(self, key) for key in self.keys()]

    def items(self) -> list[tuple[str, str | int | float]]:
        """Get the items of the options as (key, value) pairs."""
        return [(key, getattr(self, key)) for key in self.keys()]
    
    def get(self, key: str, default: Optional[Any] = None) -> str | int | float | None:
        """Get an item by key, returning a default value if the key does not exist."""
        try:
            return self.__getitem__(key)
        except (KeyError, AttributeError):
            return default

    def __getitem__(self, key: str) -> str | int | float:
        """Get an item by key."""
        return getitem(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Set an item by key."""
        setitem(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the options."""
        return key in self.keys()
    
    def __iter__(self):
        """Make the options iterable."""
        return iter(self.keys())

    def __len__(self) -> int:
        """Get the number of options."""
        return len(self.keys())