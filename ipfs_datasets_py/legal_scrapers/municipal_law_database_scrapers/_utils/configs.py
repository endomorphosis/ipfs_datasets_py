"""Configuration utilities for the municipal law database scrapers."""

from __future__ import annotations

import logging
import shutil
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


logger = logging.getLogger(__name__)


_SUPPORTED_FILE_TYPES = [
    "html",
    "json",
    "parquet",
]

_TOP_LEVEL_DIR = Path(__file__).parent.parent.parent.parent.parent.parent.parent


def _load_yaml_mapping(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _deep_merge_dicts(defaults: dict, overrides: dict) -> dict:
    merged: dict = dict(defaults)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

class Paths(BaseModel):
    _ROOT_DIR: DirectoryPath = _TOP_LEVEL_DIR
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


_paths_instance: Paths | None = None


def _ensure_paths_exist(current_paths: Paths) -> None:
    for _, path in current_paths:
        if path in {current_paths.ROOT_DIR, current_paths.HOME_DIR}:
            continue

        if path.suffix in (".csv", ".yaml", ".txt", ".json"):
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                if path.name in {"configs.yaml", "sql_configs.yaml"}:
                    example_path = current_paths.ROOT_DIR / f"{path.name}.example"
                    if example_path.exists():
                        shutil.copyfile(example_path, path)
                    else:
                        path.touch()
                else:
                    path.touch()
                logger.debug("Created file %s at %s", path.name, path)
        else:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                logger.debug("Created directory %s at %s", path.name, path)


def get_paths(*, ensure_exists: bool = True) -> Paths:
    """Return a cached :class:`Paths` instance.

    This module historically performed filesystem writes at import time. That
    made unit tests and import-time patching brittle, so path initialization is
    now lazy.
    """

    global _paths_instance
    if _paths_instance is None:
        _paths_instance = Paths()
    if ensure_exists:
        _ensure_paths_exist(_paths_instance)
    return _paths_instance


class _PathsProxy:
    def __getattr__(self, name: str):
        return getattr(get_paths(ensure_exists=True), name)


paths: Paths = _PathsProxy()  # type: ignore[assignment]


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
    normalized = value[1:] if value.startswith(".") else value
    if normalized not in _SUPPORTED_FILE_TYPES:
        raise NotImplementedError(
            f"File type '{value}' is not currently supported. Supported types are: {', '.join(_SUPPORTED_FILE_TYPES)}"
        )
    return normalized

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
        current_paths = get_paths(ensure_exists=True)
        defaults = _load_yaml_mapping(current_paths.ROOT_DIR / "configs.yaml.example")
        overrides = _load_yaml_mapping(current_paths.CONFIG_YAML_PATH)
        merged = _deep_merge_dicts(defaults, overrides)

        super().__init__(**merged)

        sql_defaults = _load_yaml_mapping(current_paths.ROOT_DIR / "sql_configs.yaml.example")
        sql_overrides = _load_yaml_mapping(current_paths.SQL_CONFIG_YAML_PATH)
        sql_merged = _deep_merge_dicts(sql_defaults, sql_overrides)
        self._sql = Sql(**sql_merged)

    @property
    def paths(self) -> Paths:
        return self._paths

    @property
    def sql(self) -> Sql:
        if self._sql is None:
            raise ValueError("SQL configuration for configs has not been set.")
        return self._sql



_configs_instance: Configs | None = None


def load_configs() -> Configs:
    """Load and return a cached :class:`Configs` instance.

    Raises a :class:`RuntimeError` if configuration cannot be loaded.
    """

    global _configs_instance
    if _configs_instance is None:
        try:
            _configs_instance = Configs()
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Error loading configurations: {e}") from e
    return _configs_instance


class _ConfigsProxy:
    def __getattr__(self, name: str):
        return getattr(load_configs(), name)


configs: Configs = _ConfigsProxy()  # type: ignore[assignment]
