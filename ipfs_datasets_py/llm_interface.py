"""
LLM Interface Module for Integration with GraphRAG

This module provides interfaces for integrating large language models with
the GraphRAG system. It includes mock implementations that will be replaced
with actual LLM integrations from ipfs_accelerate_py when available.

Main components:
- LLMInterface: Abstract base class for LLM interactions
- MockLLMInterface: Mock implementation for development
- LLMConfig: Configuration class for LLM settings
- PromptTemplate: Template class for structured prompts
- PromptLibrary: Manager for maintaining and versioning prompt templates
- AdaptivePrompting: Module for dynamically adjusting prompts based on context
"""

import json
import os
import re
import uuid
import time
import copy
import hashlib
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Tuple, Callable, Set

class LLMConfig:
    """Configuration for LLM interactions."""

    def __init__(
        self,
        model_name: str = "mock-llm",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        top_p: float = 0.9,
        context_window: int = 4096,
        supports_function_calling: bool = False,
        supports_vision: bool = False,
        supports_tools: bool = False,
        embedding_dimensions: int = 768
    ):
        """
        Initialize LLM configuration.

        Args:
            model_name: Name of the LLM model
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            top_p: Nucleus sampling parameter
            context_window: Maximum context window size
            supports_function_calling: Whether the model supports function calling
            supports_vision: Whether the model supports vision inputs
            supports_tools: Whether the model supports tool use
            embedding_dimensions: Dimensions of the embedding vectors
        """
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.context_window = context_window
        self.supports_function_calling = supports_function_calling
        self.supports_vision = supports_vision
        self.supports_tools = supports_tools
        self.embedding_dimensions = embedding_dimensions

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "context_window": self.context_window,
            "supports_function_calling": self.supports_function_calling,
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "embedding_dimensions": self.embedding_dimensions
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'LLMConfig':
        """Create config from dictionary."""
        return cls(**config_dict)


class PromptTemplate:
    """Template for structured prompts to LLMs."""

    def __init__(
        self,
        template: str,
        input_variables: List[str] = None,
        partial_variables: Dict[str, str] = None
    ):
        """
        Initialize prompt template.

        Args:
            template: String template with placeholders {variable_name}
            input_variables: List of variable names in the template
            partial_variables: Dictionary of variables with fixed values
        """
        self.template = template
        self.input_variables = input_variables or []
        self.partial_variables = partial_variables or {}

        # Extract input variables if not provided
        if not self.input_variables:
            # Find all {variable} patterns in the template
            pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
            self.input_variables = re.findall(pattern, template)

            # Remove partial variables
            self.input_variables = [
                var for var in self.input_variables
                if var not in self.partial_variables
            ]

    def format(self, **kwargs) -> str:
        """
        Format the template with provided variables.

        Args:
            **kwargs: Variable values to fill template

        Returns:
            Formatted string

        Raises:
            ValueError: If required variables are missing
        """
        # Check for missing variables
        missing_vars = [var for var in self.input_variables if var not in kwargs]
        if missing_vars:
            raise ValueError(f"Missing variables: {', '.join(missing_vars)}")

        # Combine provided variables with partial variables
        variables = {**self.partial_variables, **kwargs}

        # Format template
        return self.template.format(**variables)


class LLMInterface:
    """Abstract base class for LLM interactions."""

    def __init__(self, config: LLMConfig):
        """
        Initialize LLM interface.

        Args:
            config: LLM configuration
        """
        self.config = config

    def generate(self,
                prompt: str,
                **kwargs) -> Dict[str, Any]:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            **kwargs: Additional parameters

        Returns:
            Response dictionary with text and metadata

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement generate()")

    def generate_with_structured_output(self,
                                      prompt: str,
                                      output_schema: Dict[str, Any],
                                      **kwargs) -> Dict[str, Any]:
        """
        Generate structured output from prompt.

        Args:
            prompt: Input prompt
            output_schema: JSON schema for output
            **kwargs: Additional parameters

        Returns:
            Dictionary matching the output schema

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement generate_with_structured_output()")

    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate embedding vector for text.

        Args:
            text: Input text

        Returns:
            Embedding vector

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement embed_text()")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        Generate embedding vectors for a batch of texts.

        Args:
            texts: List of input texts

        Returns:
            Array of embedding vectors

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement embed_batch()")

    def tokenize(self, text: str) -> List[int]:
        """
        Tokenize text into token IDs.

        Args:
            text: Input text

        Returns:
            List of token IDs

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement tokenize()")

    def count_tokens(self, text: str) -> int:
        """
        Count number of tokens in text.

        Args:
            text: Input text

        Returns:
            Number of tokens

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement count_tokens()")


class MockLLMInterface(LLMInterface):
    """Mock implementation of LLM interface for development."""

    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize mock LLM interface.

        Args:
            config: LLM configuration (uses default if None)
        """
        super().__init__(config or LLMConfig())

        # Simple vocabulary for token counting
        self._vocab = set()
        self._word_pattern = re.compile(r'\b\w+\b')

        # Default responses for different prompt patterns
        self._default_responses = {
            "summarize": "This is a summary of the provided information.",
            "explain": "This is an explanation of the concept mentioned.",
            "compare": "Here's a comparison between the items mentioned.",
            "analyze": "Analysis shows several key insights about the topic.",
            "question": "The answer to your question is based on the available information."
        }

        # Response latency simulation (seconds)
        self.latency = 0.1

    def generate(self,
                prompt: str,
                **kwargs) -> Dict[str, Any]:
        """
        Generate mock text response from prompt.

        Args:
            prompt: Input prompt
            **kwargs: Additional parameters

        Returns:
            Response dictionary with text and metadata
        """
        # Parse kwargs
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

        # Simulate thinking time proportional to prompt length and parameters
        prompt_length = len(prompt)
        thinking_time = min(2.0, 0.1 + prompt_length / 10000 + temperature * 0.5)
        time.sleep(min(thinking_time, self.latency))

        # Generate deterministic but variable response based on prompt
        response_text = self._generate_response_for_prompt(prompt, max_tokens)

        return {
            "text": response_text,
            "usage": {
                "prompt_tokens": self.count_tokens(prompt),
                "completion_tokens": self.count_tokens(response_text),
                "total_tokens": self.count_tokens(prompt) + self.count_tokens(response_text)
            },
            "model": self.config.model_name,
            "id": f"mock-{uuid.uuid4()}",
            "created": int(time.time())
        }

    def generate_with_structured_output(self,
                                      prompt: str,
                                      output_schema: Dict[str, Any],
                                      **kwargs) -> Dict[str, Any]:
        """
        Generate mock structured output from prompt.

        Args:
            prompt: Input prompt
            output_schema: JSON schema for output
            **kwargs: Additional parameters

        Returns:
            Dictionary matching the output schema
        """
        # Simulate thinking time
        time.sleep(min(0.2, self.latency))

        # Create a mock output matching the schema
        result = self._generate_mock_data_for_schema(output_schema)

        # Add prompt influence
        prompt_lower = prompt.lower()
        for key in result:
            if isinstance(result[key], str) and key in prompt_lower:
                # Extract phrase after the key mention
                pattern = f"{key}[\\s:]+(.*?)(?:\\.|\\n|$)"
                matches = re.search(pattern, prompt_lower)
                if matches:
                    relevant_text = matches.group(1).strip()
                    result[key] = f"Response about {key}: {relevant_text}"

        return result

    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate mock embedding vector for text.

        Args:
            text: Input text

        Returns:
            Mock embedding vector
        """
        # Generate deterministic but variable embedding based on text
        hash_val = hash(text) % 10000
        random_state = np.random.RandomState(hash_val)

        # Create a vector with the right dimensionality
        vector = random_state.rand(self.config.embedding_dimensions)

        # Normalize to unit length
        return vector / np.linalg.norm(vector)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        Generate mock embedding vectors for a batch of texts.

        Args:
            texts: List of input texts

        Returns:
            Array of mock embedding vectors
        """
        # Generate embeddings for each text
        embeddings = [self.embed_text(text) for text in texts]

        # Stack into a single array
        return np.vstack(embeddings)

    def tokenize(self, text: str) -> List[int]:
        """
        Tokenize text into mock token IDs.

        Args:
            text: Input text

        Returns:
            List of mock token IDs
        """
        # Very simple tokenization by words
        words = self._word_pattern.findall(text.lower())

        # Update vocabulary
        self._vocab.update(words)

        # Assign token IDs based on vocabulary index
        vocab_list = sorted(list(self._vocab))
        token_ids = [vocab_list.index(word) if word in vocab_list else 0 for word in words]

        return token_ids

    def count_tokens(self, text: str) -> int:
        """
        Count number of tokens in text.

        Args:
            text: Input text

        Returns:
            Approximate number of tokens
        """
        # Simplified tokenization: count words and add 20% for punctuation/special tokens
        word_count = len(self._word_pattern.findall(text))
        return int(word_count * 1.2)

    def _generate_response_for_prompt(self, prompt: str, max_tokens: int) -> str:
        """
        Generate deterministic but variable response based on prompt.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate

        Returns:
            Generated response
        """
        prompt_lower = prompt.lower()

        # Determine the type of response based on prompt
        response_type = None
        for keyword, response in self._default_responses.items():
            if keyword in prompt_lower:
                response_type = keyword
                break

        if not response_type:
            response_type = "question"  # Default

        # Base response
        base_response = self._default_responses[response_type]

        # Adjust based on topic detection
        topics = self._extract_topics(prompt)
        if topics:
            topic_str = ", ".join(topics[:3])
            response = f"{base_response} The key topics are {topic_str}. "

            # Add details about each detected topic
            for topic in topics[:2]:
                response += f"Regarding {topic}, the analysis shows it's an important aspect to consider. "
        else:
            response = base_response

        # Add GraphRAG specific content if detected
        if "graph" in prompt_lower or "knowledge" in prompt_lower:
            response += " The knowledge graph connections reveal additional context that enhances understanding."

        if "document" in prompt_lower or "cross-document" in prompt_lower:
            response += " By analyzing multiple documents together, we can identify complementary information and resolve contradictions."

        # Ensure response is within max_tokens
        words = response.split()
        token_estimate = int(len(words) * 1.2)  # Rough estimate

        if token_estimate > max_tokens:
            # Truncate to fit
            max_words = int(max_tokens / 1.2)
            truncated_words = words[:max_words]
            response = " ".join(truncated_words) + "..."

        return response

    def _extract_topics(self, text: str) -> List[str]:
        """
        Extract potential topics from text.

        Args:
            text: Input text

        Returns:
            List of potential topics
        """
        # Look for capitalized phrases as potential topics
        topic_pattern = r'\b[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*\b'
        topics = re.findall(topic_pattern, text)

        # Filter out common words and short topics
        filtered_topics = [
            topic for topic in topics
            if len(topic) > 3 and topic.lower() not in {
                "the", "and", "for", "with", "what", "where", "when", "how", "why"
            }
        ]

        return filtered_topics

    def _generate_mock_data_for_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate mock data matching a JSON schema.

        Args:
            schema: JSON schema

        Returns:
            Dictionary matching the schema
        """
        result = {}

        # Process properties
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            # Skip if not required and randomly decide to include
            if prop_name not in schema.get("required", []) and np.random.random() > 0.7:
                continue

            # Generate value based on type
            prop_type = prop_schema.get("type", "string")

            if prop_type == "string":
                result[prop_name] = f"Mock {prop_name}"

            elif prop_type == "number" or prop_type == "integer":
                result[prop_name] = np.random.randint(1, 100)
                if prop_type == "number":
                    result[prop_name] += np.random.random()

            elif prop_type == "boolean":
                result[prop_name] = np.random.choice([True, False])

            elif prop_type == "array":
                items_schema = prop_schema.get("items", {})
                items_type = items_schema.get("type", "string")

                if items_type == "string":
                    result[prop_name] = [f"Item {i}" for i in range(3)]
                elif items_type == "number" or items_type == "integer":
                    result[prop_name] = list(np.random.randint(1, 100, 3))
                elif items_type == "object":
                    result[prop_name] = [
                        self._generate_mock_data_for_schema(items_schema)
                        for _ in range(2)
                    ]

            elif prop_type == "object":
                result[prop_name] = self._generate_mock_data_for_schema(prop_schema)

        return result


class LLMInterfaceFactory:
    """Factory for creating LLM interfaces."""

    @staticmethod
    def create(model_name: str = "mock-llm", **kwargs) -> LLMInterface:
        """
        Create an LLM interface instance.

        Args:
            model_name: Name of the LLM model
            **kwargs: Additional configuration parameters

        Returns:
            LLM interface instance

        Raises:
            ValueError: If model is not supported
        """
        # Create config
        config = LLMConfig(model_name=model_name, **kwargs)

        # Create appropriate interface
        if model_name.startswith("mock-"):
            return MockLLMInterface(config)
        else:
            try:
                # Try to import real implementation from ipfs_accelerate_py
                from ipfs_accelerate_py.llm_integration import RealLLMInterface
                return RealLLMInterface(config)
            except ImportError:
                print("Warning: ipfs_accelerate_py not available. Using mock implementation.")
                return MockLLMInterface(config)


class PromptMetadata:
    """Metadata for prompt templates."""

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        author: str = "system",
        created_at: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        model_requirements: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize prompt metadata.

        Args:
            name: Name of the prompt template
            version: Semantic version of the prompt template
            description: Description of the prompt template
            author: Author of the prompt template
            created_at: Creation timestamp
            tags: List of tags for categorization
            model_requirements: Requirements for models to use this prompt
        """
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.created_at = created_at or datetime.now()
        self.tags = tags or []
        self.model_requirements = model_requirements or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
            "model_requirements": self.model_requirements
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PromptMetadata':
        """Create metadata from dictionary."""
        created_at = datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else None
        return cls(
            name=data.get("name", "unnamed"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "system"),
            created_at=created_at,
            tags=data.get("tags", []),
            model_requirements=data.get("model_requirements", {})
        )


class TemplateVersion:
    """Version information for a prompt template."""

    def __init__(
        self,
        template: PromptTemplate,
        metadata: PromptMetadata,
        performance_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize template version.

        Args:
            template: The prompt template
            metadata: Metadata for the template
            performance_metrics: Metrics for template performance
        """
        self.template = template
        self.metadata = metadata
        self.performance_metrics = performance_metrics or {}
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute a hash of the template content."""
        content = f"{self.template.template}:{self.metadata.version}"
        return hashlib.md5(content.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert version to dictionary."""
        return {
            "template": {
                "text": self.template.template,
                "input_variables": self.template.input_variables,
                "partial_variables": self.template.partial_variables
            },
            "metadata": self.metadata.to_dict(),
            "performance_metrics": self.performance_metrics,
            "hash": self.hash
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TemplateVersion':
        """Create version from dictionary."""
        template_data = data.get("template", {})
        template = PromptTemplate(
            template=template_data.get("text", ""),
            input_variables=template_data.get("input_variables", []),
            partial_variables=template_data.get("partial_variables", {})
        )

        metadata = PromptMetadata.from_dict(data.get("metadata", {}))

        return cls(
            template=template,
            metadata=metadata,
            performance_metrics=data.get("performance_metrics", {})
        )


class PromptLibrary:
    """Manager for maintaining and versioning prompt templates."""

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize prompt library.

        Args:
            storage_path: Path for persistent storage of templates
        """
        self._templates: Dict[str, List[TemplateVersion]] = {}
        self._storage_path = storage_path
        self._cache: Dict[str, PromptTemplate] = {}

        # Load templates if storage path is provided
        if storage_path and os.path.exists(storage_path):
            self._load_from_storage()

    def add_template(
        self,
        name: str,
        template: str,
        input_variables: Optional[List[str]] = None,
        partial_variables: Optional[Dict[str, str]] = None,
        version: str = "1.0.0",
        description: str = "",
        author: str = "system",
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Add a new template to the library.

        Args:
            name: Name of the template
            template: The template string
            input_variables: List of input variables
            partial_variables: Dictionary of partial variables
            version: Version string
            description: Description of the template
            author: Author of the template
            tags: List of tags

        Returns:
            Template identifier
        """
        prompt_template = PromptTemplate(
            template=template,
            input_variables=input_variables,
            partial_variables=partial_variables
        )

        metadata = PromptMetadata(
            name=name,
            version=version,
            description=description,
            author=author,
            tags=tags
        )

        template_version = TemplateVersion(
            template=prompt_template,
            metadata=metadata
        )

        # Add to templates
        if name not in self._templates:
            self._templates[name] = []

        self._templates[name].append(template_version)

        # Update cache
        cache_key = f"{name}:{version}"
        self._cache[cache_key] = prompt_template

        # Save to storage if path is provided
        if self._storage_path:
            self._save_to_storage()

        return template_version.hash

    def get_template(self, name: str, version: Optional[str] = None) -> PromptTemplate:
        """
        Get a template by name and version.

        Args:
            name: Name of the template
            version: Version of the template (uses latest if None)

        Returns:
            The prompt template

        Raises:
            ValueError: If template is not found
        """
        if name not in self._templates:
            raise ValueError(f"Template {name} not found")

        if version:
            # Check cache first
            cache_key = f"{name}:{version}"
            if cache_key in self._cache:
                return self._cache[cache_key]

            # Find version
            for template_version in self._templates[name]:
                if template_version.metadata.version == version:
                    # Update cache
                    self._cache[cache_key] = template_version.template
                    return template_version.template

            raise ValueError(f"Version {version} of template {name} not found")
        else:
            # Get latest version
            latest = self._templates[name][-1]

            # Update cache
            cache_key = f"{name}:{latest.metadata.version}"
            self._cache[cache_key] = latest.template

            return latest.template

    def get_all_templates(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all templates in the library.

        Returns:
            Dictionary of template metadata
        """
        result = {}

        for name, versions in self._templates.items():
            result[name] = [
                {
                    "version": v.metadata.version,
                    "description": v.metadata.description,
                    "author": v.metadata.author,
                    "created_at": v.metadata.created_at.isoformat(),
                    "tags": v.metadata.tags,
                    "hash": v.hash
                }
                for v in versions
            ]

        return result

    def find_templates_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """
        Find templates by tag.

        Args:
            tag: Tag to search for

        Returns:
            List of template metadata
        """
        result = []

        for name, versions in self._templates.items():
            for version in versions:
                if tag in version.metadata.tags:
                    result.append({
                        "name": name,
                        "version": version.metadata.version,
                        "description": version.metadata.description,
                        "author": version.metadata.author,
                        "created_at": version.metadata.created_at.isoformat(),
                        "tags": version.metadata.tags,
                        "hash": version.hash
                    })

        return result

    def update_performance_metrics(
        self,
        name: str,
        version: str,
        metrics: Dict[str, Any]
    ) -> None:
        """
        Update performance metrics for a template.

        Args:
            name: Name of the template
            version: Version of the template
            metrics: Performance metrics

        Raises:
            ValueError: If template is not found
        """
        if name not in self._templates:
            raise ValueError(f"Template {name} not found")

        found = False
        for template_version in self._templates[name]:
            if template_version.metadata.version == version:
                template_version.performance_metrics.update(metrics)
                found = True
                break

        if not found:
            raise ValueError(f"Version {version} of template {name} not found")

        # Save to storage if path is provided
        if self._storage_path:
            self._save_to_storage()

    def _save_to_storage(self) -> None:
        """Save templates to storage."""
        if not self._storage_path:
            return

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)

        # Convert templates to dictionary
        data = {}
        for name, versions in self._templates.items():
            data[name] = [v.to_dict() for v in versions]

        # Save to file
        with open(self._storage_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_from_storage(self) -> None:
        """Load templates from storage."""
        if not self._storage_path or not os.path.exists(self._storage_path):
            return

        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)

            # Convert dictionary to templates
            for name, versions_data in data.items():
                self._templates[name] = []
                for version_data in versions_data:
                    template_version = TemplateVersion.from_dict(version_data)
                    self._templates[name].append(template_version)

                    # Update cache
                    cache_key = f"{name}:{template_version.metadata.version}"
                    self._cache[cache_key] = template_version.template
        except Exception as e:
            print(f"Error loading templates: {e}")


class AdaptivePrompting:
    """Module for dynamically adjusting prompts based on context."""

    def __init__(
        self,
        library: PromptLibrary,
        metrics_tracker: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize adaptive prompting module.

        Args:
            library: Prompt library
            metrics_tracker: Tracker for monitoring prompt performance
        """
        self.library = library
        self.metrics_tracker = metrics_tracker or {}
        self._context_features: Dict[str, Any] = {}
        self._rules: List[Dict[str, Any]] = []

    def add_rule(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        template_selector: Callable[[Dict[str, Any]], Tuple[str, Optional[str]]],
        priority: int = 0
    ) -> None:
        """
        Add a rule for prompt selection.

        Args:
            name: Name of the rule
            condition: Function that checks if rule applies
            template_selector: Function that selects template and version
            priority: Priority of the rule (higher = more important)
        """
        self._rules.append({
            "name": name,
            "condition": condition,
            "template_selector": template_selector,
            "priority": priority
        })

        # Sort rules by priority (descending)
        self._rules.sort(key=lambda x: x["priority"], reverse=True)

    def update_context(self, features: Dict[str, Any]) -> None:
        """
        Update context features for prompt selection.

        Args:
            features: Dictionary of context features
        """
        self._context_features.update(features)

    def select_prompt(
        self,
        task: str,
        default_template: str,
        default_version: Optional[str] = None
    ) -> PromptTemplate:
        """
        Select a prompt template based on context and rules.

        Args:
            task: The task for which to select a template
            default_template: Default template name
            default_version: Default template version

        Returns:
            The selected prompt template
        """
        # Add task to context
        context = copy.deepcopy(self._context_features)
        context["task"] = task

        # Apply rules
        for rule in self._rules:
            if rule["condition"](context):
                template_name, template_version = rule["template_selector"](context)
                try:
                    return self.library.get_template(template_name, template_version)
                except ValueError:
                    # If template not found, continue to next rule
                    continue

        # Fall back to default
        try:
            return self.library.get_template(default_template, default_version)
        except ValueError:
            # If default not found, use a simple template
            return PromptTemplate(
                template=f"Perform the task: {task}. Context: {json.dumps(context)}",
                input_variables=[]
            )

    def track_performance(
        self,
        template_name: str,
        template_version: str,
        metrics: Dict[str, Any]
    ) -> None:
        """
        Track performance of a template.

        Args:
            template_name: Name of the template
            template_version: Version of the template
            metrics: Performance metrics
        """
        # Record metrics
        key = f"{template_name}:{template_version}"
        if key not in self.metrics_tracker:
            self.metrics_tracker[key] = []

        metrics["timestamp"] = datetime.now().isoformat()
        self.metrics_tracker[key].append(metrics)

        # Update library with aggregated metrics
        aggregated = self._aggregate_metrics(key)
        self.library.update_performance_metrics(
            template_name, template_version, aggregated
        )

    def _aggregate_metrics(self, key: str) -> Dict[str, Any]:
        """
        Aggregate metrics for a template.

        Args:
            key: Template key

        Returns:
            Aggregated metrics
        """
        metrics = self.metrics_tracker.get(key, [])
        if not metrics:
            return {}

        # Aggregate numeric metrics
        result = {}
        for metric_name in metrics[0].keys():
            if metric_name == "timestamp":
                continue

            if all(isinstance(m.get(metric_name), (int, float)) for m in metrics):
                values = [m.get(metric_name) for m in metrics if metric_name in m]
                if values:
                    result[f"{metric_name}_avg"] = sum(values) / len(values)
                    result[f"{metric_name}_min"] = min(values)
                    result[f"{metric_name}_max"] = max(values)
                    result[f"{metric_name}_latest"] = values[-1]

        return result


# GraphRAG prompt templates for various reasoning tasks
class GraphRAGPromptTemplates:
    """Pre-defined prompt templates for GraphRAG reasoning tasks."""

    def __init__(self, library: Optional[PromptLibrary] = None):
        """
        Initialize GraphRAG prompt templates.

        Args:
            library: Optional prompt library to store templates
        """
        self.library = library or PromptLibrary()
        self._initialize_templates()

    def _initialize_templates(self):
        """Initialize predefined templates and add them to the library."""
        # Template for cross-document reasoning
        self.library.add_template(
            name="cross_document_reasoning",
            template="""
            You are an AI assistant performing cross-document reasoning using a knowledge graph.

            QUERY: {query}

            RELEVANT DOCUMENTS:
            {documents}

            EVIDENCE CONNECTIONS:
            {connections}

            REASONING DEPTH: {reasoning_depth}

            Your task is to synthesize information across these documents to answer the query.
            Consider how the documents relate to each other and identify complementary or contradictory information.
            Provide a well-reasoned answer based on the evidence.

            ANSWER:
            """,
            input_variables=["query", "documents", "connections", "reasoning_depth"],
            description="Template for cross-document reasoning with knowledge graphs",
            tags=["graphrag", "cross-document", "reasoning"]
        )

        # Template for academic-style cross-document reasoning
        self.library.add_template(
            name="cross_document_reasoning",
            template="""
            You are a scholarly research assistant performing cross-document reasoning using an academic knowledge graph.

            RESEARCH QUESTION: {query}

            RELEVANT PAPERS:
            {documents}

            EVIDENCE CONNECTIONS:
            {connections}

            REASONING DEPTH: {reasoning_depth}

            Your task is to synthesize information across these papers to answer the research question.
            Consider how the documents relate to each other and identify complementary, contradictory, or corroborating information.
            Provide a well-reasoned answer based on the evidence, highlighting any knowledge gaps that warrant further research.

            Format your answer in an academic style with clear sections:
            1. Summary of findings
            2. Synthesis of evidence
            3. Limitations and contradictions
            4. Research implications

            ANSWER:
            """,
            input_variables=["query", "documents", "connections", "reasoning_depth"],
            version="1.1.0",
            description="Academic-focused template for cross-document reasoning",
            tags=["graphrag", "cross-document", "reasoning", "academic"]
        )

        # Template for document evidence chain analysis
        self.library.add_template(
            name="evidence_chain_analysis",
            template="""
            Analyze the evidence chain between the following documents:

            DOCUMENT 1: {doc1}

            DOCUMENT 2: {doc2}

            CONNECTING ENTITY: {entity}

            ENTITY TYPE: {entity_type}

            DOC1 CONTEXT: {doc1_context}

            DOC2 CONTEXT: {doc2_context}

            Analyze how these documents relate through this entity. Identify whether the information is complementary,
            contradictory, or identical. Generate an inference about what this connection tells us.

            ANALYSIS:
            """,
            input_variables=["doc1", "doc2", "entity", "entity_type", "doc1_context", "doc2_context"],
            description="Template for analyzing evidence chains between documents",
            tags=["graphrag", "evidence-chain", "document-connection"]
        )

        # Template for knowledge gap identification
        self.library.add_template(
            name="knowledge_gap_identification",
            template="""
            Identify knowledge gaps between these documents about the entity:

            ENTITY: {entity}

            DOCUMENT 1 INFORMATION:
            {doc1_info}

            DOCUMENT 2 INFORMATION:
            {doc2_info}

            Identify specific knowledge gaps where one document provides information that the other does not.

            KNOWLEDGE GAPS:
            """,
            input_variables=["entity", "doc1_info", "doc2_info"],
            description="Template for identifying knowledge gaps between documents",
            tags=["graphrag", "knowledge-gaps", "document-comparison"]
        )

        # Template for deep inference generation
        self.library.add_template(
            name="deep_inference",
            template="""
            Generate deep inferences based on the following information:

            ENTITY: {entity_name} ({entity_type})

            DOCUMENT 1: {doc1_title}
            INFORMATION: {doc1_info}

            DOCUMENT 2: {doc2_title}
            INFORMATION: {doc2_info}

            RELATIONSHIP: The information is {relation_type}

            KNOWLEDGE GAPS: {knowledge_gaps}

            Generate insightful inferences about what this connection reveals, potential implications,
            and broader context that may not be explicitly stated in either document.

            INFERENCES:
            """,
            input_variables=[
                "entity_name", "entity_type", "doc1_title", "doc1_info",
                "doc2_title", "doc2_info", "relation_type", "knowledge_gaps"
            ],
            description="Template for generating deep inferences from document connections",
            tags=["graphrag", "deep-inference", "implications"]
        )

        # Template for transitive relationship analysis
        self.library.add_template(
            name="transitive_analysis",
            template="""
            Analyze this chain of relationships between entities:

            RELATIONSHIP CHAIN:
            {relationship_chain}

            Identify potential transitive relationships that may exist between the first and last entity in this chain.
            Consider what these indirect connections imply.

            TRANSITIVE RELATIONSHIP ANALYSIS:
            """,
            input_variables=["relationship_chain"],
            description="Template for analyzing transitive relationships in entity chains",
            tags=["graphrag", "transitive-relationships", "chain-analysis"]
        )

    def CROSS_DOCUMENT_REASONING(self) -> PromptTemplate:
        """Get cross-document reasoning template."""
        return self.library.get_template("cross_document_reasoning")

    def EVIDENCE_CHAIN_ANALYSIS(self) -> PromptTemplate:
        """Get evidence chain analysis template."""
        return self.library.get_template("evidence_chain_analysis")

    def KNOWLEDGE_GAP_IDENTIFICATION(self) -> PromptTemplate:
        """Get knowledge gap identification template."""
        return self.library.get_template("knowledge_gap_identification")

    def DEEP_INFERENCE(self) -> PromptTemplate:
        """Get deep inference template."""
        return self.library.get_template("deep_inference")

    def TRANSITIVE_ANALYSIS(self) -> PromptTemplate:
        """Get transitive analysis template."""
        return self.library.get_template("transitive_analysis")
