from dataclasses import dataclass


@dataclass
class Payload:
    name: str
    enabled: bool = False


def serialize(payload: Payload) -> str:
    return payload.name


def deserialize(name: str) -> Payload:
    return Payload(name, enabled=True)
