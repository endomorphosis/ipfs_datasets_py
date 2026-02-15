import os
from typing import Any, Optional

def get_output_path(
        input_path: str, 
        output_dir: Optional[str], 
        options: dict[str, Any]
        ) -> Optional[str]:
    """
    Get the output path for a file.
    
    Args:
        input_path: Path to the input file.
        output_dir: Directory to write output to.
        options: Processing options.
        
    Returns:
        Path to write output to, or None if output should not be written.
    """
    if not output_dir:
        return None

    # Get base filename without extension
    base_name = os.path.basename(input_path)
    base_name_without_ext = os.path.splitext(base_name)[0]
    
    # Create output path
    output_name = f"{base_name_without_ext}.{options['format']}"
    output_path = os.path.join(output_dir, output_name)
    
    return output_path