
from pathlib import Path
from typing import Any, Type, Self


from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class ValidPath(Path):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Type[Any],
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(cls),
                core_schema.no_info_plain_validator_function(cls.validate),
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x),
            ),
        )
    
    @classmethod
    def validate(cls, value: Any) -> Self:
        if isinstance(value, str):
            return cls(value)
        elif isinstance(value, Path):
            return cls(str(value))
        else:
            raise ValueError(f"Cannot convert {value} to Path")
