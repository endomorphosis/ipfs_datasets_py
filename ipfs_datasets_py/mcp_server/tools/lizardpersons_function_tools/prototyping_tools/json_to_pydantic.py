import importlib.util
import json
import keyword
import re
from pathlib import Path
from typing import Any, Dict, Set
import traceback

from logger import mcp_logger

def _to_snake_case(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case"""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def _structure_signature(data: dict) -> tuple:
    """Create a hashable structure signature for deduplication"""
    return tuple(sorted((key, type(value).__name__) for key, value in data.items()))

def _sanitize_field_name(name: str) -> str:
    """Sanitize field names to be valid Python identifiers"""
    # Convert spaces and special characters to underscores
    name = re.sub(r'\W', '_', name)
    
    # Handle special cases
    if name.startswith("_"):
        # Remove all leading underscores and add a trailing underscore
        name = re.sub(r'^_+', '', name)
        if not name.endswith("_"):
            name = name + "_"
    elif name[0].isdigit():
        # Prepend 'a_' to names starting with digits
        name = "a_" + name
    
    # Handle Python keywords
    if keyword.iskeyword(name):
        name += "_"
    
    # Special handling for complex cases
    if name.startswith("a_") and "class" in name:
        # If it's a numeric-class combination, ensure it ends with an underscore
        if not name.endswith("_"):
            name += "_"
    
    return name


def _build_model(
    data: dict[str, Any],
    class_name: str,
    model_registry: dict,
    structure_map: dict,
    dependencies: Dict[str, Set[str]] = None,
    allow_optional_fields: bool = False
) -> str:
    """
    Builds a Pydantic model definition dynamically based on the provided data structure.

    Args:
        data (dict[str, Any]): The input dictionary representing the structure of the data.
        class_name (str): The name of the Pydantic model class to be generated.
        model_registry (dict): A registry to store generated model definitions by class name.
        structure_map (dict): A mapping of structure signatures to class names to avoid duplication.
        dependencies (Dict[str, Set[str]]): A graph of dependencies between models.
        allow_optional_fields (bool, optional): Whether to allow fields with `None` values to be marked as optional. Defaults to False.

    Returns:
        str: The generated Pydantic model definition as a string.
    """
    # Initialize dependencies graph if not provided
    if dependencies is None:
        dependencies = {}
    
    # Add this class to the dependencies graph
    if class_name not in dependencies:
        dependencies[class_name] = set()
        
    # Generate a unique structure key for deduplication
    structure_key = _structure_signature(data)
    if structure_key in structure_map:
        return structure_map[structure_key]

    # Map the structure key to the class name
    structure_map[structure_key] = class_name
    fields = []

    # Iterate through the dictionary to generate fields
    for key, value in data.items():
        safe_key = _sanitize_field_name(key)  # Sanitize the field name
        field_type, depends_on = _infer_type(
            value, model_registry, structure_map, safe_key, dependencies, allow_optional_fields
        )
        # Normalize the field_type outside the loop
        safe_key = re.sub(r"_{2,}", "_", safe_key)
        
        # Add dependencies to the graph
        if depends_on:
            dependencies[class_name].add(depends_on)
        
        # Handle fields for Field class.
        field_options = []

        # Make all fields optional if allowed
        if allow_optional_fields:
            field_type = f"Optional[{field_type}]"
            field_options.append("default=None")
        else:
            if value is None:
                field_type = f"Optional[{field_type}]"
                field_options.append("default=None")

        if key != safe_key:
            # If the key is not safe, we need to add an alias
            field_options.append(f"alias='{key}'")
        
        if field_options:
            field_options_str = ", ".join(field_options)
        else:
            field_options_str = ""

        # Generate alias code for the field
        alias_code = f" = Field({field_options_str})" if field_options_str else ""

        # Append the field definition
        fields.append(f"    {safe_key}: {field_type}{alias_code}")

    # Generate the model definition string, add it to the registry, and return the definition.
    model_def = f"class {class_name}(BaseModel):\n" + "\n".join(fields) if fields else f"class {class_name}(BaseModel):\n    pass"

    model_registry[class_name] = model_def
    return model_def


def _infer_type_dictionary_logic(
        value: dict[Any, Any],
        model_registry: dict,
        structure_map: dict,
        parent_key: str,
        dependencies: Dict[str, Set[str]],
        allow_optional_fields: bool
        ) -> tuple[str, str | None]:
    """
    Logic to infer the type of a dictionary value and update the model registry.
    """
    if value is None or not value:  # If the dictionary is None or empty
        return ("Optional[Dict[Any, Any]]", None)
    
    # Check if all keys are numeric strings
    if all(isinstance(k, str) and k.isdigit() for k in value.keys()):
        # Check if values are consistent type
        value_types = {type(v) for v in value.values()}
        if len(value_types) == 1 and list(value_types)[0] in (int, float):
            # This looks like a numeric array
            value_type = "int" if list(value_types)[0] is int else "float"
            return (f"Union[List[{value_type}], Dict[str, {value_type}]]", None)
    
    # For regular dictionaries, create a nested model
    class_name = f"{parent_key.capitalize()}"
    # Recursively build the nested model
    _build_model(value, class_name, model_registry, structure_map, dependencies, allow_optional_fields)
    return (class_name, class_name)  # Return the class name and dependency


def _infer_type_list_logic(
        value: list[Any],
        model_registry: dict,
        structure_map: dict,
        parent_key: str,
        dependencies: Dict[str, Set[str]],
        allow_optional_fields: bool
        ) -> tuple[str, str | None]:
    """
    Logic to infer the types of values in a list and update the model registry accordingly.
    """
    if value is None or not value:  # If the list is empty, default to a generic list of Any
        return ("List[Any]", None)

    inner_types = set()  # Collect the types of elements in the list
    inner_dependencies = set()
    for item in value:
        # Infer the type of each item in the list
        inner_type, dependency = _infer_type(
            item, model_registry, structure_map, parent_key, dependencies, allow_optional_fields
        )
        inner_types.add(inner_type)
        if dependency:
            inner_dependencies.add(dependency)

    # If the list contains multiple types, return a union of those types
    if len(inner_types) > 1:
        return (f"List[Union[{', '.join(sorted(inner_types))}]]", None)
    else:
        single_type = inner_types.pop() if inner_types else "Any"
        return (f"List[{single_type}]", inner_dependencies.pop() if inner_dependencies else None)


def _infer_type(
    value: Any,
    model_registry: dict,
    structure_map: dict,
    parent_key: str,
    dependencies: Dict[str, Set[str]],
    allow_optional_fields: bool
) -> tuple[str, str | None]:
    """
    Infers the Pydantic-compatible type of a given value and updates the model registry
    and structure map if necessary.

    Args:
        value (Any): The value whose type needs to be inferred. Can be a dict, list, or primitive type.
        model_registry (dict): A dictionary to store dynamically generated Pydantic models.
        structure_map (dict): A mapping of parent keys to their corresponding data structures.
        parent_key (str): The key associated with the current value, used for naming generated models.
        dependencies (Dict[str, Set[str]]): A graph of dependencies between models.
        allow_optional_fields (bool): Whether to allow fields to be optional in the generated models.

    Returns:
        tuple[str, str | None]: A tuple containing the inferred type string and any class it depends on.
    """
    # Match the type of the value to determine the appropriate Pydantic-compatible type
    match value:
        case dict():
            return _infer_type_dictionary_logic(
            value,
            model_registry,
            structure_map,
            parent_key,
            dependencies,
            allow_optional_fields
            )
        case list():
            return _infer_type_list_logic(
            value,
            model_registry,
            structure_map,
            parent_key,
            dependencies,
            allow_optional_fields
            )
        case str():
            return ("str", None)
        case bool():
            return ("bool", None)
        case int():
            return ("int", None)
        case float():
            return ("float", None)
        case None if allow_optional_fields:
            return ("Any", None)
        case _:
            # Default to Any if the type is not recognized.
            return ("Any", None)

def _topological_sort(dependency_graph: Dict[str, Set[str]]) -> list:
    """
    Performs a topological sort on the dependency graph to ensure classes are defined
    before they are used.
    
    Args:
        dependency_graph: Dictionary mapping class names to the set of classes they depend on.
        
    Returns:
        List of class names in topologically sorted order.
    """
    # Initialize structures for topological sort
    visited = set()
    temp_mark = set()
    result = []
    
    def visit(node):
        if node in temp_mark:
            # This is a cyclic dependency, skip to avoid infinite loop
            return

        if node not in visited:
            temp_mark.add(node)
            # Visit dependencies first
            for dependency in dependency_graph.get(node, set()):
                if dependency in dependency_graph:  # Only visit if it exists in the graph
                    visit(dependency)
            # Mark node as visited and add to result
            temp_mark.discard(node)  # Use discard to avoid KeyError
            visited.add(node)
            result.append(node)
    
    # Visit all nodes
    for node in list(dependency_graph.keys()):
        if node not in visited:
            visit(node)
            
    return result

def json_to_pydantic(
    json_data: str | dict[str, Any],
    output_dir: str,
    model_name: str = "GeneratedModel",
    allow_optional_fields: bool = True
) -> str:
    """
    Turn JSON data into a Pydantic model or series of models.
    Any nested structures will be converted into their own models and placed as fields their parent models.
    NOTE: Only POSIX-style paths are supported at this time.

    Args:
        json_data (str | dict): JSON data as a JSON string, JSON dictionary, or path to a JSON file.
            
        output_dir (str): Directory to save the generated model file.
        model_name (str): Name of the generated model class. Defaults to "GeneratedModel".
        allow_optional_fields (bool): If True, allows models fields to be optional. Defaults to True.
            TODO allow_optional_fields is broken, and needs to be fixed. Please keep it set to True.

    Returns:
        str: A success message that contains the path to the output file.

    Raises:
        FileNotFoundError: If the output directory does not exist.
        TypeError: If the input JSON is not a string, dictionary, or path to a JSON file.
        ValueError: 
            - If the input JSON is invalid.
            - If there is any error during model generation.
            - If importing the generated model fails.
            - If generated model fails to validate against the input JSON.
        IOError: If there is an error writing to the output file.
    """
    if not Path(output_dir).exists():
        raise FileNotFoundError(f"Output directory '{output_dir}' does not exist.")
    else:
        output_path = Path(output_dir) / f"{model_name}.py"

    if isinstance(json_data, str):
        try:
            if Path(json_data).is_file() and json_data.endswith(".json"):
                with open(json_data, "r") as f:
                    json_data = json.load(f)
            else:
                json_data = json.loads(json_data)
        except Exception as e:
            raise ValueError(f"Invalid JSON input: {e}") from e

    if not isinstance(json_data, dict):
        raise TypeError(
            "Input JSON must be a JSON string, JSON dictionary, "
            f"or a path to a json file, not '{type(json_data).__name__}'."
        )

    model_registry: dict = {}
    structure_map: dict = {}
    dependencies: Dict[str, Set[str]] = {}
    
    try:
        _build_model(json_data, model_name, model_registry, structure_map, dependencies, allow_optional_fields)
    except Exception as e:
        mcp_logger.exception(f"Error building model: {e}")
        raise ValueError(f"Error generating Pydantic model: {e}") from e

    # Sort models topologically to handle dependencies correctly
    try:
        sorted_class_names = _topological_sort(dependencies)
    except Exception as e:
        # Fallback to simple sorting if there's an issue with topological sort
        sorted_class_names = sorted(model_registry.keys())

    # Add the imports at the beginning of the file
    imports = [
        "from pydantic import BaseModel, Field",
        "from typing import List, Any, Union, Optional, Dict"
    ]
    
    # Concatenate model definitions in topologically sorted order
    model_definitions = []
    for class_name in sorted_class_names:
        if class_name in model_registry:
            model_definitions.append(model_registry[class_name])

    model_code = "\n".join(imports) + "\n\n" + "\n\n".join(model_definitions)

    try:
        with open(output_path.resolve(), "w") as file:
            file.write(model_code)
    except Exception as e:
        raise IOError(f"Error writing to output file {output_path}: {e}") from e

    return f"Model(s) generated successfully and saved to '{output_path}'"