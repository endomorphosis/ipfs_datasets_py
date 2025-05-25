# ipfs_datasets_py/mcp_server/tools/dataset_tools/process_dataset.py
"""
MCP tool for processing datasets.

This tool handles applying transformations and operations to datasets.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger
from datasets import Dataset, DatasetDict # Import Hugging Face Dataset classes

async def process_dataset(
    dataset_obj: Union[Dataset, DatasetDict], # Changed from dataset_id: str
    operations: List[Dict[str, Any]],
    output_id: Optional[str] = None # output_id is now just for naming, not for manager
) -> Dict[str, Any]:
    """
    Process a dataset with a series of operations.

    Args:
        dataset_obj: The Hugging Face Dataset or DatasetDict object to process.
        operations: List of operations to apply to the dataset.
        output_id: Optional ID for the resulting dataset (for naming in return).

    Returns:
        Dict containing information about the processed dataset.
    """
    try:
        # If it's a DatasetDict, assume 'train' split for processing
        if isinstance(dataset_obj, DatasetDict):
            processed_dataset = dataset_obj["train"]
        else:
            processed_dataset = dataset_obj

        logger.info(f"Processing dataset with {len(operations)} operations. Initial records: {len(processed_dataset)}")
        
        for i, operation in enumerate(operations):
            op_type = operation.get("type", "").lower()
            logger.info(f"Applying operation {i+1}/{len(operations)}: {op_type}")
            
            if op_type == "filter":
                column = operation.get("column")
                condition = operation.get("condition")
                value = operation.get("value")
                
                if column and condition:
                    if condition == "==":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] == value)
                    elif condition == "!=":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] != value)
                    elif condition == ">":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] > value)
                    elif condition == "<":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] < value)
                    elif condition == ">=":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] >= value)
                    elif condition == "<=":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] <= value)
                    elif condition == "in":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] in value)
                    elif condition == "not in":
                        processed_dataset = processed_dataset.filter(lambda x: x[column] not in value)
                    elif condition == "contains":
                        processed_dataset = processed_dataset.filter(lambda x: value in x[column])
                    elif condition == "starts_with":
                        processed_dataset = processed_dataset.filter(lambda x: x[column].startswith(value))
                    elif condition == "ends_with":
                        processed_dataset = processed_dataset.filter(lambda x: x[column].endswith(value))
            
            elif op_type == "select":
                columns = operation.get("columns", [])
                if columns:
                    processed_dataset = processed_dataset.select_columns(columns)
            
            elif op_type == "rename":
                column_mapping = operation.get("column_mapping", {})
                if column_mapping:
                    processed_dataset = processed_dataset.rename_columns(column_mapping)
            
            elif op_type == "sort":
                column = operation.get("column")
                ascending = operation.get("ascending", True)
                if column:
                    processed_dataset = processed_dataset.sort(column, reverse=not ascending)
            
            elif op_type == "limit":
                n = operation.get("n")
                if n is not None:
                    processed_dataset = processed_dataset.select(range(min(n, len(processed_dataset))))
            
            elif op_type == "map":
                function_name = operation.get("function")
                if function_name == "lower":
                    column = operation.get("column")
                    processed_dataset = processed_dataset.map(lambda x: {column: x[column].lower()}) # Map expects dict return
                elif function_name == "upper":
                    column = operation.get("column")
                    processed_dataset = processed_dataset.map(lambda x: {column: x[column].upper()})
                elif function_name == "trim":
                    column = operation.get("column")
                    processed_dataset = processed_dataset.map(lambda x: {column: x[column].strip()})
                
            elif op_type == "flatten":
                processed_dataset = processed_dataset.flatten()
            
            elif op_type == "unique":
                column = operation.get("column")
                if column:
                    processed_dataset = processed_dataset.unique(column)
        
        # Return information about the processed dataset
        return {
            "status": "success",
            "original_dataset_id": getattr(dataset_obj, "id", "N/A"), # Use original dataset_obj for ID
            "dataset_id": output_id if output_id else "processed_dataset", # Use output_id or a default
            "num_operations": len(operations),
            "num_records": len(processed_dataset),
            "schema": str(processed_dataset.features) if hasattr(processed_dataset, "features") else None,
            "processed_dataset_obj": processed_dataset # Return the actual processed dataset object
        }
    except Exception as e:
        logger.error(f"Error processing dataset: {e}")
        return {
            "status": "error",
            "message": str(e),
            "original_dataset_id": getattr(dataset_obj, "id", "N/A") # Use original dataset_obj for ID
        }
