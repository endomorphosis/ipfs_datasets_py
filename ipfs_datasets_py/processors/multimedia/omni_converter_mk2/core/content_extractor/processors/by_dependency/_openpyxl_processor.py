"""
XLSX processor implementation using openpyxl.

This module provides a concrete implementation of DocumentProcessor for XLSX files
using the openpyxl library.
"""
from __future__ import annotations
from datetime import datetime
import io


from dependencies import dependencies
from types_ import Any, Callable, Configs, Logger, Content, Processor, Optional, DependencySpecificObject


from pathlib import Path

Path.home()

path_ = Path("/home/lizardperson/")


class SomeClass:

    def __init__(self, path: Path):
        self.path = path

    def get_path(self) -> Path:
        return self.path

    async def process(self, data: bytes, options: Optional[dict[str, Any]] = None) -> Content:
        pass

from functools import wraps


def _sample_decorator(func: Callable) -> Callable:
    """
    A sample decorator that can be used to modify the behavior of a function.
    
    Args:
        func: The function to be decorated.
        
    Returns:
        The modified function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Add custom behavior here
        print("Decorator applied!")
        return func(*args, **kwargs)
    return wrapper

@_sample_decorator
def add(x: int, y: int) -> int:
    return x + y 



# #### Pictures
# - Image: Chart1.png
# - Sheet Name: Charts
# - Dimensions: A1:D10
# - Summary: This is a pie chart that shows the quarterly sales growth as compared with the previous year. The largest growth is in Q4.
# - Text: "Sales Growth by Quarter", "Q1", "Q2", "Q3", "Q4", "2023", "Sales Growth", "Revenue", "125,000", "132,000", "145,000", "158,000", "Growth", "5.2%", "8.1%", "12.3%", "15.8%"
# ```

def format_data(data: bytes) -> DependencySpecificObject:
    """Turn bytes data into an openpyxl Workbook object.
    
    """
    # Create a file-like object from the bytes
    xlsx_file = io.BytesIO(data)

    # Open the XLSX file
    wb = dependencies.openpyxl.load_workbook(xlsx_file, read_only=True, data_only=True)

    return wb


def extract_text(data: DependencySpecificObject | bytes, options: dict[str, Any]) -> str:
    """
    Extract text from an XLSX document using openpyxl.

    Args:
        data: The binary data of the XLSX document.
        options: Processing options.
            - include_empty_cells: Whether to include empty cells (default: False)
            - max_rows: Maximum number of rows to extract per sheet (default: 1000)
    Returns:
        Extracted text from the XLSX document.

    Example Output:
    ```python
    {
        "include_empty_cells": False,
        "max_rows": 1000
    }
    ```

    Example of Formatted Output:
    ## Content
    ### Sheet: Cells
    ```markdown
        ## Content
        ### Sheet: Cells
        |---------|---------|--------|
        | Quarter | Revenue | Growth |
        |---------|---------|--------|
        | Q1      | $125,000| 5.2%   |
        | Q2      | $132,000| 8.1%   |
        | Q3      | $145,000| 12.3%  |
        | Q4      | $158,000| 15.8%  |
        |---------|---------|--------|
    ```
    """
    # Convert bytes to openpyxl Workbook object if it's not already
    wb = format_data(data) if isinstance(data, bytes) else data

    # Get options
    # TODO Make these values explicit in higher up in the dependency chain.
    include_empty_cells = options.get('include_empty_cells', False)
    max_rows = options.get('max_rows', 1000)
    
    # Extract text from each sheet
    sheet_texts = []
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Add the markdown headers
        sheet_texts.append(f"## Content")
        sheet_texts.append(f"### Sheet: {sheet_name}")

        # Extract data from cells
        rows = []
        row_count = 0
        
        for row in ws.iter_rows(max_row=max_rows):
            row_count += 1
            cells = []
            
            for cell in row:
                value = cell.value
                
                # Format the value as a string
                match value:
                    case None:
                        if include_empty_cells:
                            cells.append("")
                    case datetime():
                        cells.append(value.strftime("%Y-%m-%d %H:%M:%S"))
                    case str():
                        cells.append(str(value))
                    case _:
                        pass

            # Only add non-empty rows or rows with at least some content
            if any(cell.strip() for cell in cells):
                rows.append(cells)
        
        # Format as markdown table if we have data
        if rows:
            # Create table header separator
            if rows:
                num_cols = len(rows[0]) if rows else 0
                separator = "|" + "|".join(["-" * 9 for _ in range(num_cols)]) + "|"
                
                # Format rows as table
                table_rows = []
                for i, row in enumerate(rows):
                    # Pad row to match column count
                    padded_row = row + [""] * (num_cols - len(row))
                    formatted_row = "| " + " | ".join(f"{cell:<8}" for cell in padded_row) + " |"
                    table_rows.append(formatted_row)
                    
                    # Add separator after first row (header)
                    if i == 0:
                        table_rows.append(separator)
                
                sheet_texts.extend(table_rows)
        
        # Add notice if we hit the row limit
        if row_count >= max_rows:
            sheet_texts.append(f"\n[Row limit of {max_rows} reached. Additional rows not shown.]")
    
    # Join all sheets
    return "\n".join(sheet_texts)


def extract_metadata(data: DependencySpecificObject | bytes, options: Optional[dict[str, Any]]) -> dict[str, Any]:
    """
    Example of Formatted Output:
    ```markdown
        ## Metadata
        - XLSX Document: Sales Report Q4 2023
        - Creator: Jane Smith
        - Subject: Quarterly Sales Analysis
        - Created: 2023-12-15T10:30:00
        - Total Sheets: 3
        - Sheet Names: Summary, Sales Data, Charts
        - Number of Images: 2
    ```
    """
    # Convert bytes to openpyxl Workbook object if it's not already
    wb = format_data(data) if isinstance(data, bytes) else data

    # Extract document info
    metadata = {
        "file_size_bytes": len(data),
        "sheet_count": len(wb.sheetnames),
        "sheets": wb.sheetnames
    }

    # Extract document properties
    if hasattr(wb, "properties"):
        props = wb.properties
        prop_mappings = {
            "title": "title",
            "creator": "creator", 
            "subject": "subject",
            "keywords": "keywords",
            "category": "category",
            "description": "description",
            "lastModifiedBy": "last_modified_by",
            "revision": "revision"
        }
        
        # Map properties to metadata keys
        for prop_attr, meta_key in prop_mappings.items():
            if hasattr(props, prop_attr) and getattr(props, prop_attr):
                metadata[meta_key] = getattr(props, prop_attr)
        
        # Handle date properties separately
        for date_attr, meta_key in [("created", "creation_date"), ("modified", "modification_date")]:
            if hasattr(props, date_attr) and getattr(props, date_attr):
                date_val = getattr(props, date_attr)
                metadata[meta_key] = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)

    # Extract sheet statistics
    sheet_stats = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        
        # Get dimensions if available
        dimensions = "Unknown"
        if hasattr(ws, "calculate_dimension") and callable(getattr(ws, "calculate_dimension")):
            try:
                dimensions = ws.calculate_dimension()
            except:
                # Some sheets may not have data
                dimensions = "Empty or Error"
        
        sheet_stats.append({
            "name": sheet_name,
            "dimensions": dimensions,
            "sheet_state": ws.sheet_state
        })
    
    metadata["sheet_statistics"] = sheet_stats
    return metadata

def extract_structure(data: DependencySpecificObject | bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Example of Formatted Output:

    ## Structure
    - Sheet: Summary
        - Dimensions: A1:C5
        - Sample Data:
            - Q1    $125,000    5.2%
            - Q2    $132,000    8.1%
            - Q3    $145,000    12.3%
    - Sheet: Sales Data
        - Dimensions: A1:E100
        - Computed Fields:
            - 2023-10-01    Widget A    John Doe    $2,500    North
            - 2023-10-02    Widget B    Jane Smith    $3,200    South
            - 2023-10-03    Widget C    Bob Johnson    $1,800    East
    - Named Ranges:
        - SalesData: Sheet1!$A$1:$E$100

    """
    # Convert bytes to openpyxl Workbook object if it's not already
    wb = format_data(data) if isinstance(data, bytes) else data
    
    # Extract structure
    structure = []
    
    # Add workbook as a section
    structure.append({
        "type": "workbook",
        "content": "XLSX Workbook"
    })

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Add sheet structure
        sheet_structure = {
            "type": "sheet",
            "name": sheet_name,
        }
        
        # Add dimensions if available
        if hasattr(ws, "calculate_dimension") and callable(getattr(ws, "calculate_dimension")):
            try:
                sheet_structure["content"]["dimensions"] = ws.calculate_dimension()
            except:
                sheet_structure["content"]["dimensions"] = "Empty or Error"

        structure.append(sheet_structure)
        
        # Add named ranges if any are defined
        if hasattr(wb, "defined_names") and wb.defined_names:
            defined_names = []
            for name in wb.defined_names:
                if name.name.startswith('_'):  # Internal name
                    continue
                defined_names.append({
                    "name": name.name,
                    "destinations": list(name.destinations)
                })
            
            if defined_names:
                structure.append({
                    "type": "named_ranges",
                    "content": defined_names
                })

        # Get formulae from computed fields.
        if hasattr(ws, "computed_fields") and ws.computed_fields:
            computed_fields = []
            for field in ws.computed_fields:
                if hasattr(field, "name") and hasattr(field, "formula"):
                    computed_fields.append({
                        "name": field.name,
                        "formula": field.formula
                    })
            if computed_fields:
                structure.append({
                    "type": "computed_fields",
                    "content": computed_fields
                })

    return structure

def get_image_data(data: DependencySpecificObject | bytes, options: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Extract images and image metadata from the workbook.
    
    Args:
        wb: The openpyxl workbook object.
        
    Returns:
        A list of dictionaries containing the following.
        - image: The image in byte format.
        - sheet_name: The name of the sheet containing the image.
        - dimensions: The dimensions of the image in the sheet.
        - description: Optional description of the image.
    """
    images = []

    # Convert bytes to openpyxl Workbook object if it's not already
    wb = format_data(data) if isinstance(data, bytes) else data

    for sheet in wb.worksheets:
        for image in sheet._images:
            # Get the actual image data in byte format
            image_data = None
            try:
                image_data = image.ref
            except AttributeError:
                image_data = image._data()
            images.append({
                "image": image_data,
                "sheet_name": sheet.title,
                "dimensions": image.anchor._from,
                "description": getattr(image, "description", "")
            })
    
    return images

def get_version() -> str:
    """
    Get the version of openpyxl library.
    
    Returns:
        Version string of openpyxl.
    """
    try:
        return dependencies.openpyxl.__version__
    except AttributeError:
        return "unknown"
