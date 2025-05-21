# ipfs_datasets_py/mcp_server/tools/dataset_tools/process_dataset.py
"""
MCP tool for processing datasets.

This tool handles applying transformations and operations to datasets.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


async def process_dataset(
    dataset_id: str,
    operations: List[Dict[str, Any]],
    output_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a dataset with a series of operations.

    Args:
        dataset_id: The ID of the dataset to process
        operations: List of operations to apply to the dataset
        output_id: Optional ID for the resulting dataset. If not provided, a new ID will be generated.

    Returns:
        Dict containing information about the processed dataset
    """
    try:
        logger.info(f"Processing dataset {dataset_id} with {len(operations)} operations")
        
        # Import the dataset manager
        from ipfs_datasets_py import DatasetManager
        
        # Create a manager instance
        manager = DatasetManager()
        
        # Get the dataset
        dataset = manager.get_dataset(dataset_id)
        
        # Process each operation
        processed_dataset = dataset
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
                    processed_dataset = processed_dataset.map(lambda x: {**x, column: x[column].lower()})
                elif function_name == "upper":
                    column = operation.get("column")
                    processed_dataset = processed_dataset.map(lambda x: {**x, column: x[column].upper()})
                elif function_name == "trim":
                    column = operation.get("column")
                    processed_dataset = processed_dataset.map(lambda x: {**x, column: x[column].strip()})
                
            elif op_type == "flatten":
                processed_dataset = processed_dataset.flatten()
            
            elif op_type == "unique":
                column = operation.get("column")
                if column:
                    processed_dataset = processed_dataset.unique(column)
        
        # Save the processed dataset if needed
        if output_id:
            manager.add_dataset(processed_dataset, dataset_id=output_id)
            result_id = output_id
        else:
            result_id = manager.add_dataset(processed_dataset)
        
        # Return information about the processed dataset
        return {
            "status": "success",
            "original_dataset_id": dataset_id,
            "dataset_id": result_id,
            "num_operations": len(operations),
            "num_records": len(processed_dataset),
            "schema": str(processed_dataset.schema) if hasattr(processed_dataset, "schema") else None
        }
    except Exception as e:
        logger.error(f"Error processing dataset: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id
        }
