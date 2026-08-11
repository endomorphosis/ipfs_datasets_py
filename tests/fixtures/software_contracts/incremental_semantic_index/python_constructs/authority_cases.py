"""Static-analysis fixture: this file must never be imported by a test."""
from ctypes import CDLL
from enum import Flag, IntEnum, StrEnum
from typing import TypedDict
from pydantic import BaseModel

Movie = TypedDict("Movie", {"title": str})

class Priority(IntEnum): LOW = 1
class Label(StrEnum): HOT = "hot"
class Options(Flag): FAST = 1

class Request(BaseModel):
    title: str

counter = 0

class Service:
    def __init__(self, engine):
        self.engine = engine
        self.values = []

    @property
    def value(self):
        return self.values[0]

    @value.setter
    def value(self, item):
        self.values[0] = item

    @value.deleter
    def value(self):
        del self.values[0]

    def run(self, payload):
        global counter
        counter += 1
        with self.engine.session() as session:
            try:
                return Request.model_validate(payload).model_dump()
            except (ValueError, TypeError):
                return {}

    @external_decorator
    def dynamic(self, name):
        return getattr(self, name)()

    def native(self):
        return CDLL("libmissing.so")

if enabled:
    def conditional():
        return "present"
