"""Aliased model-kind constructs for inventory classification probes."""
from dataclasses import dataclass
from dataclasses import dataclass as record
from enum import IntEnum
from enum import IntEnum as IntegerEnum
from pydantic import BaseModel
from pydantic import BaseModel as ModelBase
from typing import TypedDict
from typing import TypedDict as DictionaryBase

class DirectEnum(IntEnum):
    VALUE = 1

class AliasedEnum(IntegerEnum):
    VALUE = 1

class DirectDictionary(TypedDict):
    value: int

class AliasedDictionary(DictionaryBase):
    value: int

@dataclass
class DirectRecord:
    value: int

@record
class AliasedRecord:
    value: int

class DirectModel(BaseModel):
    value: int

class AliasedModel(ModelBase):
    value: int

FunctionalMovie = DictionaryBase("FunctionalMovie", title=str, year=int, total=False)

def local_models():
    from dataclasses import dataclass as local_record
    from enum import IntEnum as LocalIntegerEnum
    from pydantic import BaseModel as LocalModelBase
    from typing import TypedDict as LocalDictionaryBase

    class LocalEnum(LocalIntegerEnum):
        VALUE = 1

    class LocalDictionary(LocalDictionaryBase):
        value: int

    @local_record
    class LocalRecord:
        value: int

    class LocalModel(LocalModelBase):
        value: int

    return LocalEnum, LocalDictionary, LocalRecord, LocalModel
