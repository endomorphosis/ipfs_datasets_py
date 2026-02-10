# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/prototyping_tools/json_to_pydantic.py'

Files last updated: 1749503602.2843401

Stub file last updated: 2025-07-07 01:10:14

## _build_model

```python
def _build_model(data: dict[str, Any], class_name: str, model_registry: dict, structure_map: dict, dependencies: Dict[str, Set[str]] = None, allow_optional_fields: bool = False) -> str:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _infer_type

```python
def _infer_type(value: Any, model_registry: dict, structure_map: dict, parent_key: str, dependencies: Dict[str, Set[str]], allow_optional_fields: bool) -> tuple[str, str | None]:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _infer_type_dictionary_logic

```python
def _infer_type_dictionary_logic(value: dict[Any, Any], model_registry: dict, structure_map: dict, parent_key: str, dependencies: Dict[str, Set[str]], allow_optional_fields: bool) -> tuple[str, str | None]:
    """
    Logic to infer the type of a dictionary value and update the model registry.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _infer_type_list_logic

```python
def _infer_type_list_logic(value: list[Any], model_registry: dict, structure_map: dict, parent_key: str, dependencies: Dict[str, Set[str]], allow_optional_fields: bool) -> tuple[str, str | None]:
    """
    Logic to infer the types of values in a list and update the model registry accordingly.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _sanitize_field_name

```python
def _sanitize_field_name(name: str) -> str:
    """
    Sanitize field names to be valid Python identifiers
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _structure_signature

```python
def _structure_signature(data: dict) -> tuple:
    """
    Create a hashable structure signature for deduplication
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _to_snake_case

```python
def _to_snake_case(name: str) -> str:
    """
    Convert camelCase or PascalCase to snake_case
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _topological_sort

```python
def _topological_sort(dependency_graph: Dict[str, Set[str]]) -> list:
    """
    Performs a topological sort on the dependency graph to ensure classes are defined
before they are used.

Args:
    dependency_graph: Dictionary mapping class names to the set of classes they depend on.
    
Returns:
    List of class names in topologically sorted order.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## json_to_pydantic

```python
def json_to_pydantic(json_data: str | dict[str, Any], output_dir: str, model_name: str = "GeneratedModel", allow_optional_fields: bool = True) -> str:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## visit

```python
def visit(node):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
