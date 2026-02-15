
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import ClassVar, Self


from pydantic import BaseModel, field_validator, computed_field


from external_interface.file_paths_manager.mime_type import MimeType
from external_interface.file_paths_manager.supported_mime_types import (
    SupportedMimeTypes,
    SupportedApplicationTypes,
    SupportedAudioTypes,
    SupportedImageTypes,
    SupportedTextTypes,
    SupportedVideoTypes
)

from pydantic_models.file_paths_manager.file_path import FilePath
from pydantic_models.configs import Configs

from utils.common.get_cid import get_cid
from utils.file_paths_manager.md5_checksum import md5_checksum


class FilePathAndMetadata(BaseModel):
    """
    A model representing a file path and its associated metadata.

    Attributes:
       file_path (FilePath): The path to the file.
       cid (str): Content Identifier (CID) of the file's path.

    Properties:
        file_name (str): The name of the file without the extension.
        file_extension (str): The extension of the file, including the dot.
        mime_type (MimeType): The mime type of the file, as determined by its extension.
        file_size (int): The size of the file in bytes.
        checksum (str): The MD5 checksum of the file.
        created_timestamp (datetime): The creation timestamp of the file.
        modified_timestamp (datetime): The last modification timestamp of the file.

    Example JSON:
    >>> {
           "cid": "Qm...",
           "file_path": "/path/to/file.txt",
           "metadata":{
                "size": 12345,
                "file_extension": ".txt",
                "mime_type": "text/plain",
                "created": "2023-10-01T12:34:56Z",
                "modified": "2023-10-02T12:34:56Z"
            }
        }
    """
    max_program_memory: ClassVar[int] = None
    file_path: FilePath
    cid: str = None

    @classmethod
    def set_max_program_memory(cls, value: int):
        cls.max_program_memory = value

    def __init__(self, **data):
        if 'max_program_memory' in data:
            self.__class__.max_program_memory = data.pop('max_program_memory')
        super().__init__(**data)
        self.cid = get_cid(self.file_path)

    @field_validator("file_path", mode="after")
    @classmethod
    def check_if_file_is_under_the_size_limit(cls, value: FilePath) -> Self:
        file_size = value.file_path.stat().st_size
        max_file_size = cls.max_program_memory
        if file_size > max_file_size:
            raise ValueError(f"File size ({file_size} bytes) exceeds {max_file_size} bytes of memory allocated to the program.")
        return value.file_path

    @computed_field(return_type=str)
    @property
    def file_name(self):
        return self.file_path.stem

    @computed_field(return_type=str)
    @property
    def file_extension(self) -> str:
        return self.file_path.suffix

    @computed_field(return_type=MimeType)
    @cached_property
    def mime_type(self) -> MimeType:
        file_extension = self.file_path.suffix.lower()
        if file_extension in SupportedApplicationTypes:
            return MimeType.APPLICATION
        elif file_extension in SupportedAudioTypes:
            return MimeType.AUDIO
        elif file_extension in SupportedImageTypes:
            return MimeType.IMAGE
        elif file_extension in SupportedTextTypes:
            return MimeType.TEXT
        elif file_extension in SupportedVideoTypes:
            return MimeType.VIDEO
        else:
            raise ValueError(f"Unsupported file extension: {file_extension}")

    @computed_field(return_type=int)
    @cached_property
    def file_size(self) -> int:
        self.file_path: Path
        return self.file_path.stat().st_size

    @computed_field(return_type=str)
    @cached_property
    def checksum(self) -> str:
        return md5_checksum(self.file_path)
    
    @computed_field(return_type=datetime)
    @cached_property
    def created_timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.file_path.stat().st_birthtime)

    @computed_field(return_type=datetime)
    @cached_property
    def modified_timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.file_path.stat().st_mtime)