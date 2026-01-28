"""
Jsonnet Utilities Module

Provides utilities for converting between Jsonnet and other data formats.
Jsonnet is a data templating language that extends JSON with variables,
functions, and comprehensions.
"""

import json
import os
from typing import Dict, List, Optional, Union, Any

# Check for dependencies
try:
    import _jsonnet
    HAVE_JSONNET = True
except ImportError:
    HAVE_JSONNET = False

try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False


class JsonnetConverter:
    """
    Converter for Jsonnet format to/from other formats.
    
    This class provides methods for converting between Jsonnet and:
    - JSON
    - JSONL (JSON Lines)
    - Python dictionaries/lists
    """
    
    def __init__(self):
        """Initialize the JsonnetConverter."""
        if not HAVE_JSONNET:
            raise ImportError(
                "jsonnet library is required for Jsonnet conversion. "
                "Install it with: pip install jsonnet"
            )
    
    def jsonnet_to_json(self, jsonnet_str: str, ext_vars: Optional[Dict[str, str]] = None,
                       tla_vars: Optional[Dict[str, str]] = None) -> str:
        """
        Evaluate Jsonnet string to JSON.
        
        Args:
            jsonnet_str (str): Jsonnet template string
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            str: Evaluated JSON string
            
        Raises:
            RuntimeError: If Jsonnet evaluation fails
        """
        try:
            ext_vars = ext_vars or {}
            tla_vars = tla_vars or {}
            
            json_str = _jsonnet.evaluate_snippet(
                "snippet",
                jsonnet_str,
                ext_vars=ext_vars,
                tla_vars=tla_vars
            )
            return json_str
        except Exception as e:
            raise RuntimeError(f"Failed to evaluate Jsonnet: {str(e)}")
    
    def jsonnet_file_to_json(self, jsonnet_path: str, ext_vars: Optional[Dict[str, str]] = None,
                            tla_vars: Optional[Dict[str, str]] = None) -> str:
        """
        Evaluate Jsonnet file to JSON.
        
        Args:
            jsonnet_path (str): Path to Jsonnet file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            str: Evaluated JSON string
            
        Raises:
            RuntimeError: If Jsonnet evaluation fails
            FileNotFoundError: If Jsonnet file doesn't exist
        """
        if not os.path.exists(jsonnet_path):
            raise FileNotFoundError(f"Jsonnet file not found: {jsonnet_path}")
        
        try:
            ext_vars = ext_vars or {}
            tla_vars = tla_vars or {}
            
            json_str = _jsonnet.evaluate_file(
                jsonnet_path,
                ext_vars=ext_vars,
                tla_vars=tla_vars
            )
            return json_str
        except Exception as e:
            raise RuntimeError(f"Failed to evaluate Jsonnet file: {str(e)}")
    
    def jsonnet_to_dict(self, jsonnet_str: str, ext_vars: Optional[Dict[str, str]] = None,
                       tla_vars: Optional[Dict[str, str]] = None) -> Union[Dict, List]:
        """
        Evaluate Jsonnet string to Python dict/list.
        
        Args:
            jsonnet_str (str): Jsonnet template string
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            Union[Dict, List]: Evaluated Python object
        """
        json_str = self.jsonnet_to_json(jsonnet_str, ext_vars, tla_vars)
        return json.loads(json_str)
    
    def jsonnet_file_to_dict(self, jsonnet_path: str, ext_vars: Optional[Dict[str, str]] = None,
                            tla_vars: Optional[Dict[str, str]] = None) -> Union[Dict, List]:
        """
        Evaluate Jsonnet file to Python dict/list.
        
        Args:
            jsonnet_path (str): Path to Jsonnet file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            Union[Dict, List]: Evaluated Python object
        """
        json_str = self.jsonnet_file_to_json(jsonnet_path, ext_vars, tla_vars)
        return json.loads(json_str)
    
    def json_to_jsonnet(self, json_str: str, pretty: bool = True) -> str:
        """
        Convert JSON string to Jsonnet format.
        
        Note: This creates a simple Jsonnet template that returns the JSON.
        For more sophisticated templates, manual authoring is recommended.
        
        Args:
            json_str (str): JSON string to convert
            pretty (bool): Whether to pretty-print the output
            
        Returns:
            str: Jsonnet template string
        """
        # Parse JSON to ensure it's valid
        data = json.loads(json_str)
        
        # Re-serialize with proper formatting
        if pretty:
            json_formatted = json.dumps(data, indent=2)
        else:
            json_formatted = json.dumps(data)
        
        # Wrap in Jsonnet (which is just JSON for simple cases)
        return json_formatted
    
    def dict_to_jsonnet(self, data: Union[Dict, List], pretty: bool = True) -> str:
        """
        Convert Python dict/list to Jsonnet format.
        
        Args:
            data (Union[Dict, List]): Python object to convert
            pretty (bool): Whether to pretty-print the output
            
        Returns:
            str: Jsonnet template string
        """
        if pretty:
            return json.dumps(data, indent=2)
        else:
            return json.dumps(data)
    
    def jsonnet_to_jsonl(self, jsonnet_str: str, output_path: str,
                        ext_vars: Optional[Dict[str, str]] = None,
                        tla_vars: Optional[Dict[str, str]] = None) -> str:
        """
        Convert Jsonnet to JSONL (JSON Lines) format.
        
        The Jsonnet template should evaluate to an array of objects.
        Each object will be written as a separate line in the JSONL file.
        
        Args:
            jsonnet_str (str): Jsonnet template string
            output_path (str): Path to output JSONL file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            str: Path to the created JSONL file
            
        Raises:
            ValueError: If Jsonnet doesn't evaluate to an array
        """
        # Evaluate Jsonnet to Python object
        data = self.jsonnet_to_dict(jsonnet_str, ext_vars, tla_vars)
        
        # Ensure it's a list/array
        if not isinstance(data, list):
            raise ValueError("Jsonnet must evaluate to an array for JSONL conversion")
        
        # Write to JSONL
        with open(output_path, 'w') as f:
            for record in data:
                json_line = json.dumps(record)
                f.write(json_line + '\n')
        
        return output_path
    
    def jsonnet_file_to_jsonl(self, jsonnet_path: str, output_path: str,
                             ext_vars: Optional[Dict[str, str]] = None,
                             tla_vars: Optional[Dict[str, str]] = None) -> str:
        """
        Convert Jsonnet file to JSONL (JSON Lines) format.
        
        Args:
            jsonnet_path (str): Path to Jsonnet file
            output_path (str): Path to output JSONL file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            str: Path to the created JSONL file
        """
        # Evaluate Jsonnet file to Python object
        data = self.jsonnet_file_to_dict(jsonnet_path, ext_vars, tla_vars)
        
        # Ensure it's a list/array
        if not isinstance(data, list):
            raise ValueError("Jsonnet must evaluate to an array for JSONL conversion")
        
        # Write to JSONL
        with open(output_path, 'w') as f:
            for record in data:
                json_line = json.dumps(record)
                f.write(json_line + '\n')
        
        return output_path
    
    def jsonl_to_jsonnet(self, jsonl_path: str, output_path: Optional[str] = None,
                        pretty: bool = True) -> str:
        """
        Convert JSONL file to Jsonnet format.
        
        Args:
            jsonl_path (str): Path to JSONL file
            output_path (str, optional): Path to output Jsonnet file. If None, returns string.
            pretty (bool): Whether to pretty-print the output
            
        Returns:
            str: Jsonnet template string or path to output file
        """
        # Read JSONL file
        records = []
        with open(jsonl_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    records.append(json.loads(line))
        
        # Convert to Jsonnet
        jsonnet_str = self.dict_to_jsonnet(records, pretty)
        
        # Write to file if output path provided
        if output_path:
            with open(output_path, 'w') as f:
                f.write(jsonnet_str)
            return output_path
        
        return jsonnet_str
    
    def jsonnet_to_arrow(self, jsonnet_str: str, ext_vars: Optional[Dict[str, str]] = None,
                        tla_vars: Optional[Dict[str, str]] = None) -> 'pa.Table':
        """
        Convert Jsonnet to Arrow table.
        
        Args:
            jsonnet_str (str): Jsonnet template string
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            pa.Table: Arrow table
            
        Raises:
            ImportError: If PyArrow is not available
            ValueError: If Jsonnet doesn't evaluate to an array
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for Arrow conversion")
        
        # Evaluate Jsonnet to Python object
        data = self.jsonnet_to_dict(jsonnet_str, ext_vars, tla_vars)
        
        # Ensure it's a list/array
        if not isinstance(data, list):
            raise ValueError("Jsonnet must evaluate to an array for Arrow conversion")
        
        # Convert to Arrow table
        return pa.Table.from_pylist(data)
    
    def jsonnet_file_to_arrow(self, jsonnet_path: str, ext_vars: Optional[Dict[str, str]] = None,
                             tla_vars: Optional[Dict[str, str]] = None) -> 'pa.Table':
        """
        Convert Jsonnet file to Arrow table.
        
        Args:
            jsonnet_path (str): Path to Jsonnet file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            
        Returns:
            pa.Table: Arrow table
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for Arrow conversion")
        
        # Evaluate Jsonnet file to Python object
        data = self.jsonnet_file_to_dict(jsonnet_path, ext_vars, tla_vars)
        
        # Ensure it's a list/array
        if not isinstance(data, list):
            raise ValueError("Jsonnet must evaluate to an array for Arrow conversion")
        
        # Convert to Arrow table
        return pa.Table.from_pylist(data)
    
    def jsonnet_to_parquet(self, jsonnet_str: str, output_path: str,
                          ext_vars: Optional[Dict[str, str]] = None,
                          tla_vars: Optional[Dict[str, str]] = None,
                          compression: str = 'snappy') -> str:
        """
        Convert Jsonnet to Parquet format.
        
        Args:
            jsonnet_str (str): Jsonnet template string
            output_path (str): Path to output Parquet file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            compression (str): Compression codec ('snappy', 'gzip', 'brotli', etc.)
            
        Returns:
            str: Path to the created Parquet file
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for Parquet conversion")
        
        import pyarrow.parquet as pq
        
        # Convert to Arrow table
        table = self.jsonnet_to_arrow(jsonnet_str, ext_vars, tla_vars)
        
        # Write to Parquet
        pq.write_table(table, output_path, compression=compression)
        
        return output_path
    
    def jsonnet_file_to_parquet(self, jsonnet_path: str, output_path: str,
                               ext_vars: Optional[Dict[str, str]] = None,
                               tla_vars: Optional[Dict[str, str]] = None,
                               compression: str = 'snappy') -> str:
        """
        Convert Jsonnet file to Parquet format.
        
        Args:
            jsonnet_path (str): Path to Jsonnet file
            output_path (str): Path to output Parquet file
            ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
            tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
            compression (str): Compression codec ('snappy', 'gzip', 'brotli', etc.)
            
        Returns:
            str: Path to the created Parquet file
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for Parquet conversion")
        
        import pyarrow.parquet as pq
        
        # Convert to Arrow table
        table = self.jsonnet_file_to_arrow(jsonnet_path, ext_vars, tla_vars)
        
        # Write to Parquet
        pq.write_table(table, output_path, compression=compression)
        
        return output_path


# Convenience functions for direct use
def jsonnet_to_json(jsonnet_str: str, ext_vars: Optional[Dict[str, str]] = None,
                   tla_vars: Optional[Dict[str, str]] = None) -> str:
    """
    Evaluate Jsonnet string to JSON.
    
    Args:
        jsonnet_str (str): Jsonnet template string
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        
    Returns:
        str: Evaluated JSON string
    """
    converter = JsonnetConverter()
    return converter.jsonnet_to_json(jsonnet_str, ext_vars, tla_vars)


def jsonnet_file_to_json(jsonnet_path: str, ext_vars: Optional[Dict[str, str]] = None,
                        tla_vars: Optional[Dict[str, str]] = None) -> str:
    """
    Evaluate Jsonnet file to JSON.
    
    Args:
        jsonnet_path (str): Path to Jsonnet file
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        
    Returns:
        str: Evaluated JSON string
    """
    converter = JsonnetConverter()
    return converter.jsonnet_file_to_json(jsonnet_path, ext_vars, tla_vars)


def jsonnet_to_jsonl(jsonnet_str: str, output_path: str,
                    ext_vars: Optional[Dict[str, str]] = None,
                    tla_vars: Optional[Dict[str, str]] = None) -> str:
    """
    Convert Jsonnet to JSONL format.
    
    Args:
        jsonnet_str (str): Jsonnet template string
        output_path (str): Path to output JSONL file
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        
    Returns:
        str: Path to the created JSONL file
    """
    converter = JsonnetConverter()
    return converter.jsonnet_to_jsonl(jsonnet_str, output_path, ext_vars, tla_vars)


def jsonnet_file_to_jsonl(jsonnet_path: str, output_path: str,
                         ext_vars: Optional[Dict[str, str]] = None,
                         tla_vars: Optional[Dict[str, str]] = None) -> str:
    """
    Convert Jsonnet file to JSONL format.
    
    Args:
        jsonnet_path (str): Path to Jsonnet file
        output_path (str): Path to output JSONL file
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        
    Returns:
        str: Path to the created JSONL file
    """
    converter = JsonnetConverter()
    return converter.jsonnet_file_to_jsonl(jsonnet_path, output_path, ext_vars, tla_vars)


def jsonl_to_jsonnet(jsonl_path: str, output_path: Optional[str] = None,
                    pretty: bool = True) -> str:
    """
    Convert JSONL file to Jsonnet format.
    
    Args:
        jsonl_path (str): Path to JSONL file
        output_path (str, optional): Path to output Jsonnet file
        pretty (bool): Whether to pretty-print the output
        
    Returns:
        str: Jsonnet template string or path to output file
    """
    converter = JsonnetConverter()
    return converter.jsonl_to_jsonnet(jsonl_path, output_path, pretty)


def jsonnet_to_parquet(jsonnet_str: str, output_path: str,
                      ext_vars: Optional[Dict[str, str]] = None,
                      tla_vars: Optional[Dict[str, str]] = None,
                      compression: str = 'snappy') -> str:
    """
    Convert Jsonnet to Parquet format.
    
    Args:
        jsonnet_str (str): Jsonnet template string
        output_path (str): Path to output Parquet file
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        compression (str): Compression codec
        
    Returns:
        str: Path to the created Parquet file
    """
    converter = JsonnetConverter()
    return converter.jsonnet_to_parquet(jsonnet_str, output_path, ext_vars, tla_vars, compression)


def jsonnet_file_to_parquet(jsonnet_path: str, output_path: str,
                           ext_vars: Optional[Dict[str, str]] = None,
                           tla_vars: Optional[Dict[str, str]] = None,
                           compression: str = 'snappy') -> str:
    """
    Convert Jsonnet file to Parquet format.
    
    Args:
        jsonnet_path (str): Path to Jsonnet file
        output_path (str): Path to output Parquet file
        ext_vars (Dict[str, str], optional): External variables to pass to Jsonnet
        tla_vars (Dict[str, str], optional): Top-level arguments to pass to Jsonnet
        compression (str): Compression codec
        
    Returns:
        str: Path to the created Parquet file
    """
    converter = JsonnetConverter()
    return converter.jsonnet_file_to_parquet(jsonnet_path, output_path, ext_vars, tla_vars, compression)
