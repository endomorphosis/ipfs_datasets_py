# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/llm/refactored_prompt_loader.py'

Files last updated: 1748487670.3685122

Stub file last updated: 2025-07-17 05:33:54

## PromptTemplate

```python
class PromptTemplate(BaseModel if BaseModel != object else object):
    """
    Template for system and user prompts for LLM interactions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format

```python
def format(self, **kwargs) -> "PromptTemplate":
    """
    Format the prompts using the provided variables.

Args:
    **kwargs: Variables to insert into the prompt templates
    
Returns:
    Self with formatted prompts
    """
```
* **Async:** False
* **Method:** True
* **Class:** PromptTemplate

## is_yaml_available

```python
def is_yaml_available() -> bool:
    """
    Check if YAML library is available.

Returns:
    True if YAML is available, False otherwise
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_prompt_by_name

```python
def load_prompt_by_name(name: str, prompts_dir: Union[str, Path], default_prompt: Optional[PromptTemplate] = None) -> PromptTemplate:
    """
    Load a prompt template by name from the prompts directory.

Args:
    name: Name of the prompt template
    prompts_dir: Directory containing prompt templates
    default_prompt: Default prompt to use if loading fails
    
Returns:
    PromptTemplate instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_prompt_from_yaml

```python
def load_prompt_from_yaml(prompt_path: Union[str, Path], default_prompt: Optional[PromptTemplate] = None) -> PromptTemplate:
    """
    Load a prompt template from a YAML file.

Args:
    prompt_path: Path to YAML file
    default_prompt: Default prompt to use if loading fails
    
Returns:
    PromptTemplate instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## safe_format

```python
def safe_format(template: str, **kwargs) -> str:
    """
    Safely format a string template, ignoring missing keys.

Args:
    template: String template to format
    **kwargs: Variables to insert into the template
    
Returns:
    Formatted string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
