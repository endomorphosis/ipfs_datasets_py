from enum import Enum
from typing import Any, Callable, Coroutine


from pydantic import BaseModel


from configs.configs import Configs, Paths
from .api_connection import ApiConnection


import json
from pydantic import BaseModel, Field, PrivateAttr


class SupportedTransformersModels(BaseModel):
    model: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_json(cls, file_path: str) -> 'SupportedTransformersModels':
        """
        Load the SupportedTransformersModels from a JSON file.

        Args:
            file_path (str): The path to the JSON file.

        Returns:
            SupportedTransformersModels: An instance of the class with data loaded from the JSON file.

        Raises:
            FileNotFoundError: If the specified file is not found.
            json.JSONDecodeError: If the JSON file is invalid.
        """
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
            return cls(model=data)
        except FileNotFoundError:
            raise FileNotFoundError(f"The file {file_path} was not found.")
        except json.JSONDecodeError:
            raise json.JSONDecodeError(f"The file {file_path} contains invalid JSON.")

class SupportedProviders(Enum):
    COHERE = "cohere"
    OLLAMA = "ollama"
    TRANSFORMERS = "transformers"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class ModelType(Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    SPEECH_TO_TEXT = "speech_to_text"
    MULTIMODAL = "Multimodal"
    CLASSIFIER = "classifier"


import aiohttp
from aiohttp import ClientResponse


class ApiManager():
    
    def __init__(self, resources: dict[str, Callable|Coroutine]=None, configs: BaseModel = None):
        self.resources = resources
        self.configs = configs

        self.max_connections_per_api: int = configs.non_system_resources_max_connections_per_api
        self.available_api_connections: list = []

        self.max_connections_per_api: int = configs.max_connections_per_api if configs.can_use_llm else 0
        self.connections_in_use: int = 0
        self.supported_models: BaseModel = SupportedTransformersModels.from_json(
            Paths.PROJECT_ROOT / "mapped_models.json"
        )

    def acquire(self) -> ApiConnection:
        """
        Create an API connection based on the configuration.
        This configuration is determined by the kind of API specified in the Config file.
        NOTE: Certain types of APIs will necessarily limit the number of connections that can be made.
            For example, to avoid overloading graphics cards, connections to a Transformers model
            will be limited to one.

        Returns:
            ApiConnection: An instance of the ApiConnection class.
            The class is a Pydantic BaseModel with the following attributes.
            - client: The client object for an API. 
                For external APIs, this is the client object for a specific provider e.g. OpenAI. 
                For internal APIs, this is a URL to a local host e.g. Ollama, 
                    or None if the the Model is loaded directly e.g. Transformers.
            - model: The model object for an API. 
                For external APIs, this is the model's name as a string.
                For internal APIs, this can be either the model's name as a string or the model object itself.
            - provider: The provider of the API. Currently supported providers are: 
                Anthropic, Cohere, Ollama, OpenAI, and Transformers.
            - model_type: The type of the model. Currently supported model types are: 
                LLM, Embedding, Speech-to-text, Multimodal, and Classifier
        """
        pass

    def receive_request_from_external_resource_manager(self) -> None:
        """
        
        """
        pass

    def out(self) -> list[ApiConnection]:
        """
        
        """
        pass
