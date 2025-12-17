"""Configuration utilities for the municipal law database scrapers."""
import logging
from pathlib import Path
from typing import Annotated as Ann, Optional


from pydantic import (
    AfterValidator as AV, 
    BaseModel, 
    BeforeValidator as BV, 
    DirectoryPath,
    Field, 
    PrivateAttr, 
    SecretStr
)
import yaml


_SUPPORTED_FILE_TYPES = [
    "html",
    "json",
    "parquet",
]


class Paths(BaseModel):
    _ROOT_DIR: DirectoryPath = Path(__file__).parent.parent
    _HOME_DIR: DirectoryPath = _ROOT_DIR.parent
    _OUTPUT_TO_HUGGING_FACE_DIR: DirectoryPath = _ROOT_DIR / "output_to_hugging_face"
    _INPUT_FROM_SQL: DirectoryPath = _ROOT_DIR / "input_from_sql"
    _HASHES_CSV_PATH: DirectoryPath = _ROOT_DIR / "hashes.csv"
    _CONFIG_YAML_PATH: DirectoryPath = _ROOT_DIR / "configs.yaml"
    _SQL_CONFIG_YAML_PATH: DirectoryPath = _ROOT_DIR / "sql_configs.yaml"

    def __iter__(self):
        for attr, value in self.__dict__.items():
            value: Path
            yield (attr, value)

    @property
    def ROOT_DIR(self):
        return self._ROOT_DIR

    @property
    def HOME_DIR(self):
        return self._HOME_DIR

    @property
    def OUTPUT_TO_HUGGING_FACE_DIR(self):
        return self._OUTPUT_TO_HUGGING_FACE_DIR

    @property
    def HASHES_CSV_PATH(self):
        return self._HASHES_CSV_PATH

    @property
    def CONFIG_YAML_PATH(self):
        return self._CONFIG_YAML_PATH

    @property
    def SQL_CONFIG_YAML_PATH(self):
        return self._SQL_CONFIG_YAML_PATH

    @property
    def INPUT_FROM_SQL(self):
        return self._INPUT_FROM_SQL

# Iterate over Paths Enum
try:
    paths = Paths()
    for _, path in paths:
        if path not in {paths.ROOT_DIR, paths.HOME_DIR}:  # Use set for efficiency
            if path.suffix in ('.csv', '.yaml', '.txt', '.json'):  # Use .suffix instead of endswith()
                if not path.parent.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.touch()
                    print(f"Created file {path.name} at {path}")
            else:
                if not path.exists():
                    path.mkdir(parents=True, exist_ok=True)
                    print(f"Created directory {path.name} at {path}")
except Exception as e:
    raise RuntimeError(f"Error initializing paths: {e}") from e


def _make_log_level_an_int(value: str|int) -> int:
    if isinstance(value, int):
        return value
    else:
        match value.upper():
            case "DEBUG":
                return logging.DEBUG
            case "INFO":
                return logging.INFO
            case "WARNING":
                return logging.WARNING
            case "ERROR":
                return logging.ERROR
            case "CRITICAL":
                return logging.CRITICAL
            case _:
                raise ValueError(f"Invalid log level: {value}")

def _check_if_this_type_is_supported(value: str) -> str:
    if value not in _SUPPORTED_FILE_TYPES:
        raise NotImplementedError(
            f"File type '{value}' is not currently supported. Supported types are: {', '.join(_SUPPORTED_FILE_TYPES)}"
        )
    return value

class Tables(BaseModel):
    """Tables in the database"""
    DATA_TABLE_NAMES: list[str]
    METADATA_TABLE_NAMES: list[str]
    

class Sql(BaseModel):
    """SQL database connection details"""
    HOST: str
    USER: str
    PORT: int
    PASSWORD: str
    DATABASE_NAME: str
    OUTPUT_FOLDER: str = "input_from_sql"
    LIMIT: int = 100000
    BATCH_SIZE: int = 5000
    PARTITION_COLUMN: str = "id"
    COMPRESSION_TYPE: str = "gzip"
    SQL_TYPE: str = "mysql"

    _tables: Optional[Tables] = None

    def __init__(self, **data):
        tables_data = data.pop("TABLES")
        super().__init__(**data)
        self._tables = Tables(**tables_data)

    @property
    def tables(self) -> Tables:
        if self._tables is None:
            raise ValueError("Tables configuration for configs has not been set.")
        return self._tables

class Configs(BaseModel):
    """General configuration for the program"""
    HUGGING_FACE_USER_ACCESS_TOKEN: str
    REPO_ID: str
    TARGET_DIR_NAME: str

    BATCH_SIZE: int = Field(default=100, ge=1, le=5000)
    CLEAR_HASHES_CSV: bool = Field(default=True)
    FILE_PATH_ENDING: Ann[
        str, AV(_check_if_this_type_is_supported)
    ] = Field(default="parquet")

    HUGGING_FACE_UPLOAD_CONCURRENCY_LIMIT: int = Field(default=4, ge=1, le=10)
    LOG_LEVEL: Ann[
        int, BV(_make_log_level_an_int)
    ] = Field(default=logging.INFO, ge=logging.DEBUG, le=logging.CRITICAL)
    GET_FROM_SQL: bool = Field(default=False)
    OPENAI_API_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""))

    _paths: Paths = PrivateAttr(default_factory=Paths)
    _sql: Optional[Sql] = None

    def __init__(self, **data):
        print("Loading general configs...")
        try:
            with open(paths.CONFIG_YAML_PATH, "r") as f:
                data = dict(yaml.safe_load(f))
        except Exception as e:
            raise RuntimeError(f"Error loading general configs from {paths.CONFIG_YAML_PATH}: {e}") from e
        super().__init__(**data)

        print("General configs loaded. Loading Sql configs...")
        try:
            with open(paths.SQL_CONFIG_YAML_PATH, "r") as f:
                sql_data = dict(yaml.safe_load(f))
        except Exception as e:
            raise RuntimeError(f"Error loading SQL configs from {paths.SQL_CONFIG_YAML_PATH}: {e}") from e

        self._sql = Sql(**sql_data)

        print("Sql Configs loaded.")
        print("All configs loaded successfully.")

    @property
    def paths(self) -> Paths:
        return self._paths

    @property
    def sql(self) -> Sql:
        if self._sql is None:
            raise ValueError("SQL configuration for configs has not been set.")
        return self._sql

try:
    configs = Configs()
except Exception as e:
    raise RuntimeError(f"Error loading configurations: {e}") from e
