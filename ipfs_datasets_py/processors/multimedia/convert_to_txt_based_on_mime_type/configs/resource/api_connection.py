
from typing import Any, TypeVar


import aiohttp
from pydantic import BaseModel, Field, PrivateAttr


SupportedProviders = TypeVar("SupportedProviders")
ModelType = TypeVar("ModelType")



class ApiConnection(BaseModel):
    """
    ApiConnection is a base class for making API requests to AI model providers. 
    It provides methods for sending requests and handling responses.
    NOTE This is primarily to avoid having to deal with a trillion SDKs for different APIs.
    New SDK schemas types can loaded as needed as Pydantic models from JSON files.
    """
    client: Any = None
    model: Any = None
    provider: SupportedProviders = None
    model_type: ModelType = None
    max_tokens: int = None
    api_key: str = None
    api_url: str = None
    api_version: str = None
    system_message: str = Field(default="You are a helpful assistant.")

    header: dict = None
    data: dict = None
    _messages: list[dict[str, str]] = PrivateAttr(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)
        self.data = {
            'model': self.model,
            'max_tokens': self.max_tokens,
        }
        self.header = {
            'content-type': 'application/json',
            'accept': 'application/json',
        }

    @property
    def messages(self) -> list[dict[str, str]]:
        return self._messages

    @messages.setter
    def messages(self, value: dict[str, str] | list[dict[str, str]]) -> None:
        if isinstance(value, dict):
            self._messages.append(value)
        elif isinstance(value, list):
            for dict_ in value:
                if isinstance(dict_, dict):
                    self._messages.append(dict_)
        else:
            raise ValueError("Invalid type for messages")

    async def get(self, *args, **kwargs) -> Any:
        """
        Get data from the API.
        """
        async with aiohttp.ClientSession() as session:
            session: aiohttp.ClientSession
            with session.get(*args, **kwargs) as response:
                response: aiohttp.ClientResponse
                return await response.json()

    async def post(self, *args, **kwargs) -> Any:
        """
        Post data to an API.
        """
        async with aiohttp.ClientSession() as session:
            session: aiohttp.ClientSession
            with session.post(*args, **kwargs) as response:
                response: aiohttp.ClientResponse
                return await response.json()
            return session.request(*args, **kwargs)

