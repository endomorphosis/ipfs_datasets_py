from dataclasses import dataclass


@dataclass
class Payload:
    name: str


def serialize(payload: Payload) -> str:
    return payload.name


def deserialize(name: str) -> Payload:
    return Payload(name)
