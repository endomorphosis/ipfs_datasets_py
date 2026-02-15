"""
Prompt loading utilities for LLM interactions.
Provides tools for loading and formatting prompts from YAML files.
"""
import os
from pathlib import Path
from typing import Any, Optional, Union

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = object
    Field = lambda *args, **kwargs: None  # noqa: E731

from logger import logger


class PromptTemplate(BaseModel if BaseModel != object else object):
    """
    Template for system and user prompts for LLM interactions.
    """
    system_prompt: str = "You are a helpful assistant."
    user_prompt: str = ""
    
    # Optional parameters
    temperature: float = 0.7
    max_tokens: int = 1000
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    
    def format(self, **kwargs) -> "PromptTemplate":
        """
        Format the prompts using the provided variables.
        
        Args:
            **kwargs: Variables to insert into the prompt templates
            
        Returns:
            Self with formatted prompts
        """
        try:
            self.system_prompt = self.system_prompt.format(**kwargs)
            self.user_prompt = self.user_prompt.format(**kwargs)
            return self
        except KeyError as e:
            logger.warning(f"Missing key in prompt formatting: {e}")
            return self
        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            return self


def is_yaml_available() -> bool:
    """
    Check if YAML library is available.
    
    Returns:
        True if YAML is available, False otherwise
    """
    return YAML_AVAILABLE


def safe_format(template: str, **kwargs) -> str:
    """
    Safely format a string template, ignoring missing keys.
    
    Args:
        template: String template to format
        **kwargs: Variables to insert into the template
        
    Returns:
        Formatted string
    """
    for key, value in kwargs.items():
        # Replace {key} with value if present
        placeholder = "{" + key + "}"
        if placeholder in template:
            template = template.replace(placeholder, str(value))
    return template


def load_prompt_from_yaml(
    prompt_path: Union[str, Path],
    default_prompt: Optional[PromptTemplate] = None
) -> PromptTemplate:
    """
    Load a prompt template from a YAML file.
    
    Args:
        prompt_path: Path to YAML file
        default_prompt: Default prompt to use if loading fails
        
    Returns:
        PromptTemplate instance
    """
    if not YAML_AVAILABLE:
        logger.error("YAML library not available. Cannot load prompt from YAML.")
        return default_prompt or PromptTemplate()
    
    try:
        with open(prompt_path, 'r') as file:
            data = yaml.safe_load(file)
            
            # Extract prompt fields
            template = PromptTemplate(
                system_prompt=data.get("system_prompt", "You are a helpful assistant."),
                user_prompt=data.get("user_prompt", ""),
                
                # Optional parameters
                temperature=data.get("temperature", 0.7),
                max_tokens=data.get("max_tokens", 1000),
                top_p=data.get("top_p", 1.0),
                frequency_penalty=data.get("frequency_penalty", 0.0),
                presence_penalty=data.get("presence_penalty", 0.0)
            )
            
            return template
    except Exception as e:
        logger.error(f"Error loading prompt from {prompt_path}: {e}")
        return default_prompt or PromptTemplate()


def load_prompt_by_name(
    name: str,
    prompts_dir: Union[str, Path],
    default_prompt: Optional[PromptTemplate] = None
) -> PromptTemplate:
    """
    Load a prompt template by name from the prompts directory.
    
    Args:
        name: Name of the prompt template
        prompts_dir: Directory containing prompt templates
        default_prompt: Default prompt to use if loading fails
        
    Returns:
        PromptTemplate instance
    """
    prompt_path = Path(prompts_dir) / f"{name}.yaml"
    return load_prompt_from_yaml(prompt_path, default_prompt)