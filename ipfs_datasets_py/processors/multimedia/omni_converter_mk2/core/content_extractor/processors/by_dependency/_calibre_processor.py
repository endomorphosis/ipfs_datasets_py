import subprocess
import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Any


# TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# TODO A lot of the code here is generic and can be moved to an orchestration class.

def check_calibre_installation() -> bool:
    """Check if Calibre is installed and accessible."""
    try:
        subprocess.run(['ebook-convert', '--version'], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_supported_formats() -> dict[str, list[str]]:
    """Get supported input and output formats from Calibre."""
    try:
        result = subprocess.run(['ebook-convert', '--help'], 
                               capture_output=True, text=True, check=True)
        # Parse the help output to extract supported formats
        # This is a simplified version - actual parsing would be more complex 
        # TODO LLM was lazy here! Implement actual parsing logic.
        return {
            'input': ['epub', 'mobi', 'azw', 'azw3', 'pdf', 'txt', 'docx', 'html'],
            'output': ['epub', 'mobi', 'azw3', 'pdf', 'txt', 'html', 'docx']
        }
    except subprocess.CalledProcessError:
        return {'input': [], 'output': []}

def validate_format(file_format: str, format_type: str = 'input') -> bool:
    """Validate if a format is supported by Calibre."""
    supported = get_supported_formats()
    return file_format.lower() in supported.get(format_type, [])

def build_conversion_command(input_file: str, output_file: str, 
                           options: Optional[dict[str, Any]] = None) -> list[str]:
    """Build the ebook-convert command with options."""
    cmd = ['ebook-convert', input_file, output_file]
    
    if options:
        for key, value in options.items():
            if value is True:
                cmd.append(f'--{key}')
            elif value is not False and value is not None:
                cmd.extend([f'--{key}', str(value)])
    
    return cmd

def convert_ebook(input_file: str, output_file: str, 
                 options: Optional[dict[str, Any]] = None) -> bool:
    """Convert an e-book from one format to another using Calibre."""
    if not check_calibre_installation():
        raise RuntimeError("Calibre is not installed or not accessible")
    
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Validate input format
    input_ext = Path(input_file).suffix[1:].lower()
    if not validate_format(input_ext, 'input'):
        raise ValueError(f"Unsupported input format: {input_ext}")
    
    # Validate output format
    output_ext = Path(output_file).suffix[1:].lower()
    if not validate_format(output_ext, 'output'):
        raise ValueError(f"Unsupported output format: {output_ext}")
    
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    try:
        cmd = build_conversion_command(input_file, output_file, options)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Conversion failed: {e.stderr}")

def convert_with_temp_files(input_data: bytes, input_format: str, 
                          output_format: str, 
                          options: Optional[dict[str, Any]] = None) -> bytes:
    """Convert e-book data using temporary files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        input_file = os.path.join(temp_dir, f"input.{input_format}")
        output_file = os.path.join(temp_dir, f"output.{output_format}")
        
        # Write input data to temporary file
        with open(input_file, 'wb') as f:
            f.write(input_data)
        
        # Perform conversion
        if convert_ebook(input_file, output_file, options):
            # Read converted data
            with open(output_file, 'rb') as f:
                return f.read()
        else:
            raise RuntimeError("Conversion failed")

def get_metadata(input_file: str) -> dict[str, Any]:
    """Extract metadata from an e-book file using Calibre."""
    if not check_calibre_installation():
        raise RuntimeError("Calibre is not installed or not accessible")
    
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    try:
        cmd = ['ebook-meta', input_file]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Parse metadata output (simplified parsing)
        metadata = {}
        for line in result.stdout.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip().lower()] = value.strip()
        
        return metadata
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to extract metadata: {e.stderr}")

def set_metadata(input_file: str, output_file: str, 
                metadata: dict[str, str]) -> bool:
    """Set metadata for an e-book file using Calibre."""
    if not check_calibre_installation():
        raise RuntimeError("Calibre is not installed or not accessible")
    
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Copy input to output first
    shutil.copy2(input_file, output_file)
    
    try:
        cmd = ['ebook-meta', output_file]
        
        # Add metadata options
        for key, value in metadata.items():
            if key.lower() in ['title', 'authors', 'publisher', 'language', 'series']:
                cmd.extend([f'--{key.lower()}', value])
        
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to set metadata: {e.stderr}")
    


