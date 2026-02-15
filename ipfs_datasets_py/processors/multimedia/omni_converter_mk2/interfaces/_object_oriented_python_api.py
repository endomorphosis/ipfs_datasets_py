from pathlib import Path
from typing import Optional, Any, Callable


from ._python_api import PythonAPI
from .options import Options

from pathlib import Path
from typing import Union, List, Optional, Any, Tuple
import os


class Convert(PythonAPI):
    """
    Public class for object-oriented access to the Omni-Converter.
    Similar to Pathlib's Path class, this class provides extensions to the API to make it
    certain operations more idiomatic and efficient.

    Methods:
        - walk_and_convert: Walk through a directory and convert all files.
        - estimate_file_count: Estimate the number of files in a directory that can potentially be converted.
        - convert: Convert a file or directory to text.
        - 
    """
    from configs import configs
    from batch_processor import make_batch_processor
    from monitors import make_resource_monitor, make_error_monitor, make_security_monitor

    def __new__(cls, *paths):
        path_signature = tuple(sorted(str(p) for p in paths))
        if path_signature not in cls._instances:
            cls._instances[path_signature] = super().__new__(cls)
        return cls._instances[path_signature]

    def __init__(self, *paths):
        """
        Initialize the Convert class.
        
        Args:
            *paths: Variable number of file or directory paths to convert.
                   If empty, the converter starts in "receiver" mode for >> operator.
        """
        resources = {
            "batch_processor": self.make_batch_processor(),
            "resource_monitor": self.make_resource_monitor(),
        }
        super().__init__(resources=resources, configs=self.configs)

        self.target_file = None
        self.target_dir = None

        self._sources: List[Path] = []
        self._conversion_chain: List[Tuple[Path, Optional[Path]]] = []
        self._current_outputs: List[Path] = []
        
        for path in paths:
            p = Path(path)
            self._sources.append(p)
            self._current_outputs.append(p)

    def __rshift__(self, target: Union[str, Path]) -> 'Convert':
        """
        Overload the '>>' operator to convert a file or directory.
        
        Args:
            target: The target path for conversion. Can be:
                   - A file path with extension (converts to that format)
                   - A directory path (keeps original names, changes format if specified)
                   - A format string (e.g., ".pdf" applies format to all files)
        
        Returns:
            Convert: A new Convert instance with the conversion results,
                    allowing for chaining operations.
        
        Example:
            Convert("input.txt") >> "output.pdf" >> "final_output/"
            Convert() >> "data.csv" >> "data.json"
            Convert("file1.doc", "file2.doc") >> ".pdf" >> "processed/"
        """
        target_path = Path(target)
        new_outputs = []
        
        # If this is an empty converter (receiver mode), add the target as a source
        if not self._current_outputs and not self._sources:
            self._sources.append(target_path)
            self._current_outputs.append(target_path)
            return self
        
        # Process each current output
        for source in self._current_outputs:
            if target_path.is_dir() or str(target).endswith('/'):
                # Target is a directory - maintain filename, possibly change extension
                output_dir = target_path
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Check if target has a specific extension pattern
                if '.' in target_path.name:
                    # Extract extension from directory name (e.g., "output.pdf/")
                    _, ext = os.path.splitext(target_path.name)
                    output_path = output_dir.parent / f"{source.stem}{ext}"
                else:
                    # Keep original extension
                    output_path = output_dir / source.name
            
            elif target.startswith('.'):
                # Target is just an extension
                output_path = source.with_suffix(target)
            
            else:
                # Target is a specific file path
                output_path = target_path
                
                # If multiple sources and single target file, append index
                if len(self._current_outputs) > 1:
                    index = self._current_outputs.index(source)
                    output_path = target_path.parent / f"{target_path.stem}_{index}{target_path.suffix}"
            
            # Use the existing convert method for actual conversion
            self.convert(path=str(source), output_path=str(output_path))
            
            # Track the conversion in the chain
            self._conversion_chain.append((source, output_path))
            new_outputs.append(output_path)
        
        # Create new instance with outputs as sources for chaining
        new_converter = Convert()
        new_converter._sources = self._sources.copy()
        new_converter._current_outputs = new_outputs
        new_converter._conversion_chain = self._conversion_chain.copy()
        
        # Update target file and directory
        if new_outputs:
            new_converter.target_file = str(new_outputs[0])
            new_converter.target_dir = str(new_outputs[0].parent)
        
        return new_converter

    def get_chain(self) -> List[Tuple[Path, Optional[Path]]]:
        """
        Get the full conversion chain.
        
        Returns:
            List of tuples containing (source, target) pairs for each conversion.
        """
        return self._conversion_chain.copy()
    
    def get_outputs(self) -> List[Path]:
        """
        Get the current output files.
        
        Returns:
            List of Path objects representing current outputs.
        """
        return self._current_outputs.copy()
    
    def __repr__(self) -> str:
        """String representation of the converter state."""
        if not self._sources:
            return "Convert()"
        
        sources_str = ", ".join(f'"{s}"' for s in self._sources)
        
        if self._conversion_chain:
            chain_str = " >> ".join(
                f'"{t}"' if t else f'"{s}"' 
                for s, t in self._conversion_chain
            )
            return f"Convert({sources_str}) >> {chain_str}"
        
        return f"Convert({sources_str})"

    def walk(self, path: str = None, recursive: bool = False) -> None:
        """
        Walk through a directory and convert all files it encounters.
        
        Args:
            path: The path to the directory to convert. If None, uses the current target directory.
            recursive: Whether to walk through subdirectories. Default is False.
        """
        # TODO Implement walk_and_convert method
        pass

    def iterconvert(self, path: str = None, recursive: bool = False) -> Any:
        """
        Iterate through files in a directory and convert them one by one.
        """
        pass

    def estimate_time(self, path: str = None, recursive: bool = False) -> float:
        """
        Estimate the time required to convert files in a directory that can potentially be converted.
        """
        pass

    def estimate_size(self, path: str = None, recursive: bool = False) -> int:
        """
        Estimate the size of files in a directory that can potentially be converted.
        """
        pass

    def estimate_file_count(self, path: str = None, recursive: bool = False) -> int:
        """
        Estimate the number of files in a directory that can potentially be converted.
        
        Args:
            path: The path to the directory to convert. If None, uses the current target directory.
            recursive: Whether to walk through subdirectories. Default is False.
        """
        # TODO Implement estimate_file_count method
        pass

    def can_convert(self, path: str = None, options: Optional[Options] = None) -> bool:
        """
        Check if the file can be converted.
        """
        pass

    def convert(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
        """
        Convert a file or directory to text.
        
        Args:
            path: The path to the file to convert.
            output_path: The path to save the converted file.
            options: Conversion options.
        """
        file_path = path or self.target_file
        return super().convert_file(
            file_path=file_path,
            output_path=output_path,
            options=options
        )

    def convert_and_compress(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
        """
        Convert a file or directory to text and compress the output to an archival format.
        """
        pass

    async def async_convert(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
        """
        Asynchronously convert a file or directory to text.
        """
        pass

    def preview(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
        """Preview first N bytes of conversion"""
        pass

    def dry_run(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
        """
        Perform a dry run of the conversion process.
        """
        pass

    def upload(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
        """
        Upload a converted file or directory to a website.
        NOTE: All credentials and configurations for the upload must be set in the options.

        Options include:
        - url: Custom URL to upload to.
        - github: Upload to GitHub repository.
        - s3: Upload to Amazon S3 bucket.
        - gcs: Upload to Google Cloud Storage bucket.
        - azure: Upload to Azure Blob Storage.
        - huggingface: Upload to Hugging Face Hub.
        """
        pass

    def glob(self, pattern: str) -> list[Path]:
        """
        Search for and convert files matching the pattern in the target directory.
        """
        pass

    def rglob(self, pattern: str) -> list[Path]:
        """
        Recursively search for and convert files matching the pattern in the target directory.
        """
        pass

Convert = Convert()
