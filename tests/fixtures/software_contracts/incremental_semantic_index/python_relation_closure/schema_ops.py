"""Static-analysis fixture: never import or execute this module."""
import json
from dataclasses import asdict, dataclass
from pydantic import BaseModel
from typing import TypedDict

@dataclass
class Payload:
    value: int

class Patch(TypedDict):
    value: int

class Request(BaseModel):
    value: int

def encode(payload: Payload) -> str:
    return json.dumps(asdict(payload))

def decode(raw: str) -> Patch:
    return json.loads(raw)

def parse_request(raw: str) -> Request:
    return Request.model_validate_json(raw)
