"""
Universal Data Format Converter

A package-wide utility for converting data between all supported formats:
- JSON
- JSONL (JSON Lines)
- JSON-LD (JSON Linked Data)
- JSON-LD-LOGIC (JSON-LD with formal logic annotations)
- Parquet
- IPLD (InterPlanetary Linked Data)
- CAR (Content Addressable aRchive)
- Arrow Tables
- HuggingFace Datasets
- CSV
- Pandas DataFrames

This module provides a unified interface for data format conversion
across the entire ipfs_datasets_py package.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# Check for dependencies
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False
    logger.warning("PyArrow not available. Parquet and Arrow features disabled.")

try:
    import pandas as pd
    HAVE_PANDAS = True
except ImportError:
    HAVE_PANDAS = False
    logger.warning("Pandas not available. DataFrame features disabled.")

try:
    from datasets import Dataset, DatasetDict
    HAVE_HF_DATASETS = True
except ImportError:
    HAVE_HF_DATASETS = False
    logger.warning("HuggingFace datasets not available.")


class UniversalDataConverter:
    """
    Universal data format converter supporting all ipfs_datasets_py formats.
    
    This class provides a centralized, package-wide utility for converting
    data between various formats. It ensures consistency across the entire
    codebase and avoids niche implementations.
    
    Supported Formats:
        - JSON: Standard JSON format
        - JSONL: JSON Lines (newline-delimited JSON)
        - JSON-LD: JSON Linked Data with @context
        - JSON-LD-LOGIC: JSON-LD with formal logic annotations
        - Parquet: Apache Parquet columnar format
        - IPLD: InterPlanetary Linked Data
        - CAR: Content Addressable aRchive
        - Arrow: Apache Arrow tables
        - HuggingFace: HuggingFace Dataset objects
        - CSV: Comma-separated values
        - DataFrame: Pandas DataFrame
    
    Example:
        >>> converter = UniversalDataConverter()
        >>> converter.convert_file("data.json", "data.parquet", "json", "parquet")
        >>> converter.convert_file("data.jsonl", "data.json-ld", "jsonl", "jsonld")
    """
    
    def __init__(self):
        """Initialize the UniversalDataConverter."""
        self.supported_formats = [
            "json", "jsonl", "jsonld", "jsonld-logic",
            "parquet", "ipld", "car", "arrow", "csv",
            "dataframe", "huggingface", "dict", "list"
        ]
    
    def convert(self, data: Any, from_format: str, to_format: str, **kwargs) -> Any:
        """
        Convert data from one format to another.
        
        Args:
            data: Input data in the source format
            from_format: Source format (json, jsonl, parquet, etc.)
            to_format: Target format (json, jsonl, parquet, etc.)
            **kwargs: Additional format-specific options
        
        Returns:
            Converted data in the target format
        
        Raises:
            ValueError: If format is not supported
            ImportError: If required dependencies are not available
        
        Example:
            >>> data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
            >>> parquet_data = converter.convert(data, "list", "parquet")
        """
        from_format = from_format.lower()
        to_format = to_format.lower()
        
        # Validate formats
        if from_format not in self.supported_formats:
            raise ValueError(f"Unsupported source format: {from_format}")
        if to_format not in self.supported_formats:
            raise ValueError(f"Unsupported target format: {to_format}")
        
        # If formats are the same, return data as-is
        if from_format == to_format:
            return data
        
        # Convert to intermediate format (dict/list)
        intermediate = self._to_intermediate(data, from_format, **kwargs)
        
        # Convert from intermediate to target format
        result = self._from_intermediate(intermediate, to_format, **kwargs)
        
        return result
    
    def convert_file(self, input_path: str, output_path: str,
                    from_format: Optional[str] = None,
                    to_format: Optional[str] = None,
                    **kwargs) -> str:
        """
        Convert a file from one format to another.
        
        Args:
            input_path: Path to input file
            output_path: Path to output file
            from_format: Source format (auto-detected if None)
            to_format: Target format (auto-detected if None)
            **kwargs: Additional format-specific options
        
        Returns:
            Path to the created output file
        
        Example:
            >>> converter.convert_file("data.json", "data.parquet")
            >>> converter.convert_file("data.jsonl", "data.json-ld", to_format="jsonld")
        """
        # Auto-detect formats from file extensions
        if from_format is None:
            from_format = self._detect_format(input_path)
        if to_format is None:
            to_format = self._detect_format(output_path)
        
        logger.info(f"Converting {input_path} from {from_format} to {to_format}")
        
        # Load input data
        data = self.load(input_path, from_format, **kwargs)
        
        # Convert to target format
        converted_data = self.convert(data, from_format, to_format, **kwargs)
        
        # Save output data
        self.save(converted_data, output_path, to_format, **kwargs)
        
        return output_path
    
    def load(self, path: str, format: str, **kwargs) -> Any:
        """
        Load data from a file in the specified format.
        
        Args:
            path: Path to the file
            format: Format of the file
            **kwargs: Format-specific loading options
        
        Returns:
            Loaded data
        """
        format = format.lower()
        
        if format == "json":
            return self._load_json(path, **kwargs)
        elif format == "jsonl":
            return self._load_jsonl(path, **kwargs)
        elif format == "jsonld":
            return self._load_jsonld(path, **kwargs)
        elif format == "jsonld-logic":
            return self._load_jsonld_logic(path, **kwargs)
        elif format == "parquet":
            return self._load_parquet(path, **kwargs)
        elif format == "csv":
            return self._load_csv(path, **kwargs)
        elif format == "car":
            return self._load_car(path, **kwargs)
        elif format == "ipld":
            return self._load_ipld(path, **kwargs)
        else:
            raise ValueError(f"Cannot load format: {format}")
    
    def save(self, data: Any, path: str, format: str, **kwargs) -> str:
        """
        Save data to a file in the specified format.
        
        Args:
            data: Data to save
            path: Path to save to
            format: Format to save in
            **kwargs: Format-specific saving options
        
        Returns:
            Path to the saved file
        """
        format = format.lower()
        
        # Create output directory if needed
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        
        if format == "json":
            return self._save_json(data, path, **kwargs)
        elif format == "jsonl":
            return self._save_jsonl(data, path, **kwargs)
        elif format == "jsonld":
            return self._save_jsonld(data, path, **kwargs)
        elif format == "jsonld-logic":
            return self._save_jsonld_logic(data, path, **kwargs)
        elif format == "parquet":
            return self._save_parquet(data, path, **kwargs)
        elif format == "csv":
            return self._save_csv(data, path, **kwargs)
        elif format == "car":
            return self._save_car(data, path, **kwargs)
        elif format == "ipld":
            return self._save_ipld(data, path, **kwargs)
        else:
            raise ValueError(f"Cannot save format: {format}")
    
    def _detect_format(self, path: str) -> str:
        """Detect format from file extension."""
        ext = Path(path).suffix.lower()
        
        format_map = {
            ".json": "json",
            ".jsonl": "jsonl",
            ".json-ld": "jsonld",
            ".jsonld": "jsonld",
            ".parquet": "parquet",
            ".pq": "parquet",
            ".csv": "csv",
            ".car": "car",
            ".ipld": "ipld",
        }
        
        return format_map.get(ext, "json")
    
    def _to_intermediate(self, data: Any, format: str, **kwargs) -> Union[List[Dict], Dict]:
        """Convert from source format to intermediate dict/list format."""
        if format in ["dict", "list"]:
            return data
        elif format == "json":
            if isinstance(data, str):
                return json.loads(data)
            return data
        elif format == "jsonl":
            if isinstance(data, str):
                lines = data.strip().split("\n")
                return [json.loads(line) for line in lines if line.strip()]
            return data
        elif format == "jsonld":
            # JSON-LD is JSON with @context
            if isinstance(data, str):
                return json.loads(data)
            return data
        elif format == "jsonld-logic":
            # JSON-LD-LOGIC is JSON-LD with logic annotations
            if isinstance(data, str):
                return json.loads(data)
            return data
        elif format == "parquet":
            if not HAVE_ARROW:
                raise ImportError("PyArrow required for Parquet support")
            if isinstance(data, pa.Table):
                return data.to_pylist()
            elif isinstance(data, str):
                # Assume it's a file path
                table = pq.read_table(data)
                return table.to_pylist()
            return data
        elif format == "arrow":
            if not HAVE_ARROW:
                raise ImportError("PyArrow required for Arrow support")
            if isinstance(data, pa.Table):
                return data.to_pylist()
            return data
        elif format == "dataframe":
            if not HAVE_PANDAS:
                raise ImportError("Pandas required for DataFrame support")
            if isinstance(data, pd.DataFrame):
                return data.to_dict("records")
            return data
        elif format == "huggingface":
            if not HAVE_HF_DATASETS:
                raise ImportError("HuggingFace datasets required")
            if isinstance(data, (Dataset, DatasetDict)):
                if isinstance(data, DatasetDict):
                    data = data[kwargs.get("split", "train")]
                return [dict(item) for item in data]
            return data
        elif format == "csv":
            if not HAVE_PANDAS:
                raise ImportError("Pandas required for CSV support")
            if isinstance(data, str):
                # Assume it's a file path
                df = pd.read_csv(data)
                return df.to_dict("records")
            return data
        else:
            return data
    
    def _from_intermediate(self, data: Union[List[Dict], Dict], format: str, **kwargs) -> Any:
        """Convert from intermediate dict/list format to target format."""
        if format in ["dict", "list"]:
            return data
        elif format == "json":
            return data  # Already in dict/list format
        elif format == "jsonl":
            return data  # Already in list format
        elif format == "jsonld":
            # Add @context if not present
            return self._add_jsonld_context(data, **kwargs)
        elif format == "jsonld-logic":
            # Add @context and logic annotations
            return self._add_logic_annotations(data, **kwargs)
        elif format == "parquet":
            if not HAVE_ARROW:
                raise ImportError("PyArrow required for Parquet support")
            # Convert to Arrow table
            if not isinstance(data, list):
                data = [data]
            table = pa.Table.from_pylist(data)
            return table
        elif format == "arrow":
            if not HAVE_ARROW:
                raise ImportError("PyArrow required for Arrow support")
            if not isinstance(data, list):
                data = [data]
            return pa.Table.from_pylist(data)
        elif format == "dataframe":
            if not HAVE_PANDAS:
                raise ImportError("Pandas required for DataFrame support")
            if not isinstance(data, list):
                data = [data]
            return pd.DataFrame(data)
        elif format == "huggingface":
            if not HAVE_HF_DATASETS:
                raise ImportError("HuggingFace datasets required")
            if not isinstance(data, list):
                data = [data]
            return Dataset.from_dict(self._list_to_dict_of_lists(data))
        elif format == "csv":
            # CSV data is just the list of dicts
            return data
        else:
            return data
    
    def _load_json(self, path: str, **kwargs) -> Union[Dict, List]:
        """Load JSON file."""
        with open(path, 'r') as f:
            return json.load(f)
    
    def _save_json(self, data: Any, path: str, **kwargs) -> str:
        """Save JSON file."""
        indent = kwargs.get("indent", 2)
        with open(path, 'w') as f:
            json.dump(data, f, indent=indent)
        return path
    
    def _load_jsonl(self, path: str, **kwargs) -> List[Dict]:
        """Load JSONL file."""
        records = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
    
    def _save_jsonl(self, data: Any, path: str, **kwargs) -> str:
        """Save JSONL file."""
        if not isinstance(data, list):
            data = [data]
        with open(path, 'w') as f:
            for record in data:
                f.write(json.dumps(record) + "\n")
        return path
    
    def _load_jsonld(self, path: str, **kwargs) -> Union[Dict, List]:
        """Load JSON-LD file."""
        with open(path, 'r') as f:
            return json.load(f)
    
    def _save_jsonld(self, data: Any, path: str, **kwargs) -> str:
        """Save JSON-LD file."""
        # Ensure @context is present
        data = self._add_jsonld_context(data, **kwargs)
        indent = kwargs.get("indent", 2)
        with open(path, 'w') as f:
            json.dump(data, f, indent=indent)
        return path
    
    def _load_jsonld_logic(self, path: str, **kwargs) -> Union[Dict, List]:
        """Load JSON-LD-LOGIC file."""
        with open(path, 'r') as f:
            return json.load(f)
    
    def _save_jsonld_logic(self, data: Any, path: str, **kwargs) -> str:
        """Save JSON-LD-LOGIC file with formal logic annotations."""
        # Add both @context and logic annotations
        data = self._add_logic_annotations(data, **kwargs)
        indent = kwargs.get("indent", 2)
        with open(path, 'w') as f:
            json.dump(data, f, indent=indent)
        return path
    
    def _load_parquet(self, path: str, **kwargs) -> List[Dict]:
        """Load Parquet file."""
        if not HAVE_ARROW:
            raise ImportError("PyArrow required for Parquet support")
        table = pq.read_table(path)
        return table.to_pylist()
    
    def _save_parquet(self, data: Any, path: str, **kwargs) -> str:
        """Save Parquet file."""
        if not HAVE_ARROW:
            raise ImportError("PyArrow required for Parquet support")
        
        # Convert to Arrow table
        if isinstance(data, pa.Table):
            table = data
        elif isinstance(data, list):
            table = pa.Table.from_pylist(data)
        elif isinstance(data, dict):
            table = pa.Table.from_pylist([data])
        elif HAVE_PANDAS and isinstance(data, pd.DataFrame):
            table = pa.Table.from_pandas(data)
        else:
            raise ValueError(f"Cannot convert {type(data)} to Parquet")
        
        # Write to Parquet
        compression = kwargs.get("compression", "snappy")
        pq.write_table(table, path, compression=compression)
        return path
    
    def _load_csv(self, path: str, **kwargs) -> List[Dict]:
        """Load CSV file."""
        if not HAVE_PANDAS:
            raise ImportError("Pandas required for CSV support")
        df = pd.read_csv(path)
        return df.to_dict("records")
    
    def _save_csv(self, data: Any, path: str, **kwargs) -> str:
        """Save CSV file."""
        if not HAVE_PANDAS:
            raise ImportError("Pandas required for CSV support")
        
        # Convert to DataFrame
        if isinstance(data, pd.DataFrame):
            df = data
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
        else:
            raise ValueError(f"Cannot convert {type(data)} to CSV")
        
        df.to_csv(path, index=False)
        return path
    
    def _load_car(self, path: str, **kwargs) -> List[Dict]:
        """Load CAR file."""
        try:
            from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
            utils = DataInterchangeUtils()
            table = utils.import_table_from_car(path)
            
            # Convert to list of dicts
            if hasattr(table, 'to_pylist'):
                return table.to_pylist()
            elif hasattr(table, 'to_pydict'):
                return [dict(zip(table.column_names, row)) 
                       for row in zip(*table.to_pydict().values())]
            else:
                # Mock table
                return table.to_pydict()
        except ImportError:
            raise ImportError("CAR conversion utilities not available")
    
    def _save_car(self, data: Any, path: str, **kwargs) -> str:
        """Save CAR file."""
        try:
            from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
            
            # Convert to Arrow table first
            if not isinstance(data, pa.Table):
                if isinstance(data, list):
                    table = pa.Table.from_pylist(data)
                elif isinstance(data, dict):
                    table = pa.Table.from_pylist([data])
                else:
                    raise ValueError(f"Cannot convert {type(data)} to CAR")
            else:
                table = data
            
            # Export to CAR
            utils = DataInterchangeUtils()
            utils.export_table_to_car(table, path)
            return path
        except ImportError:
            raise ImportError("CAR conversion utilities not available")
    
    def _load_ipld(self, path: str, **kwargs) -> List[Dict]:
        """Load IPLD data."""
        try:
            from ipfs_datasets_py.ipld.storage import IPLDStorage
            storage = IPLDStorage()
            # Load CID from file and retrieve data
            with open(path, 'r') as f:
                cid = f.read().strip()
            data = storage.get_json(cid)
            return data if isinstance(data, list) else [data]
        except ImportError:
            raise ImportError("IPLD storage utilities not available")
    
    def _save_ipld(self, data: Any, path: str, **kwargs) -> str:
        """Save IPLD data."""
        try:
            from ipfs_datasets_py.ipld.storage import IPLDStorage
            storage = IPLDStorage()
            
            # Store data and get CID
            if isinstance(data, list):
                cid = storage.put_json(data)
            elif isinstance(data, dict):
                cid = storage.put_json(data)
            else:
                raise ValueError(f"Cannot convert {type(data)} to IPLD")
            
            # Save CID to file
            with open(path, 'w') as f:
                f.write(str(cid))
            return path
        except ImportError:
            raise ImportError("IPLD storage utilities not available")
    
    def _add_jsonld_context(self, data: Union[Dict, List], **kwargs) -> Union[Dict, List]:
        """Add @context to JSON-LD data if not present."""
        # Use provided context or default to a generic schema.org context
        context = kwargs.get("context", {
            "@vocab": "http://schema.org/"
        })
        
        if isinstance(data, dict):
            if "@context" not in data:
                # Add context without overwriting existing data
                data = {"@context": context, **data}
            # If @context already exists, data is left unchanged
        elif isinstance(data, list):
            # Wrap list in a container with @context
            data = {
                "@context": context,
                "@graph": data
            }
        
        return data
    
    def _add_logic_annotations(self, data: Union[Dict, List], **kwargs) -> Union[Dict, List]:
        """Add formal logic annotations to JSON-LD data."""
        # First add JSON-LD context
        data = self._add_jsonld_context(data, **kwargs)
        
        # Add logic-specific context
        logic_context = {
            "logic": "http://www.w3.org/ns/logic#",
            "fol": "http://www.w3.org/ns/logic/fol#",
            "modal": "http://www.w3.org/ns/logic/modal#",
            "deontic": "http://www.w3.org/ns/logic/deontic#",
        }
        
        if isinstance(data, dict):
            if "@context" in data:
                if isinstance(data["@context"], dict):
                    data["@context"].update(logic_context)
                elif isinstance(data["@context"], list):
                    data["@context"].append(logic_context)
            
            # Add logic metadata
            if "logic:annotations" not in data:
                data["logic:annotations"] = {
                    "fol:axioms": [],
                    "fol:rules": [],
                    "modal:operators": [],
                    "deontic:obligations": [],
                    "deontic:permissions": [],
                    "deontic:prohibitions": []
                }
        
        return data
    
    def _list_to_dict_of_lists(self, data: List[Dict]) -> Dict[str, List]:
        """Convert list of dicts to dict of lists (for HuggingFace datasets)."""
        if not data:
            return {}
        
        keys = data[0].keys()
        result = {key: [] for key in keys}
        
        for record in data:
            for key in keys:
                result[key].append(record.get(key))
        
        return result


# Create a global instance for package-wide use
_converter_instance = None

def get_converter() -> UniversalDataConverter:
    """
    Get the global UniversalDataConverter instance.
    
    Returns:
        UniversalDataConverter: The global converter instance
    
    Example:
        >>> from ipfs_datasets_py.utils.data_format_converter import get_converter
        >>> converter = get_converter()
        >>> converter.convert_file("data.json", "data.parquet")
    """
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = UniversalDataConverter()
    return _converter_instance


# Convenience functions for common conversions
def convert_to_json(data: Any, from_format: str, **kwargs) -> Union[Dict, List]:
    """Convert data to JSON format."""
    return get_converter().convert(data, from_format, "json", **kwargs)

def convert_to_jsonl(data: Any, from_format: str, **kwargs) -> List[Dict]:
    """Convert data to JSONL format."""
    return get_converter().convert(data, from_format, "jsonl", **kwargs)

def convert_to_jsonld(data: Any, from_format: str, **kwargs) -> Union[Dict, List]:
    """Convert data to JSON-LD format."""
    return get_converter().convert(data, from_format, "jsonld", **kwargs)

def convert_to_parquet(data: Any, from_format: str, **kwargs) -> 'pa.Table':
    """Convert data to Parquet format."""
    return get_converter().convert(data, from_format, "parquet", **kwargs)

def convert_to_ipld(data: Any, from_format: str, **kwargs) -> Any:
    """Convert data to IPLD format."""
    return get_converter().convert(data, from_format, "ipld", **kwargs)

def convert_to_car(data: Any, from_format: str, **kwargs) -> Any:
    """Convert data to CAR format."""
    return get_converter().convert(data, from_format, "car", **kwargs)
