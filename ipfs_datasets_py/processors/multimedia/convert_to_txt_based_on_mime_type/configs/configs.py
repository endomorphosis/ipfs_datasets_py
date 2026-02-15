#!/usr/bin/venv python3
from __future__ import annotations
from __version__ import __version__






from enum import Enum
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Optional, Self


import duckdb
from duckdb import DuckDBPyConnection
from pydantic import (
    AliasChoices,
    AfterValidator as AV,
    BeforeValidator as BV,
    BaseModel, 
    DirectoryPath,
    Field, 
    FilePath,
    model_validator,
    PrivateAttr,
    SecretStr,
    ValidationError,
)

from logger.logger import Logger

from .playwright.proxy_launch_configs import ProxyLaunchConfigs
from .playwright.browser_launch_configs import BrowserLaunchConfigs
from .types.valid_path import ValidPath

from external_interface.config_parser.resources._normalize_dict_keys_and_values import (
    normalize_dict_keys_and_values
)
from external_interface.config_parser.resources._check_for_invalid_keys import _check_for_invalid_keys

def convert_log_level(value: str | int) -> int:
    """
    Convert a string log level to its corresponding integer value.
    """
    if isinstance(value, int):
        if value < 0 or value > 50:
            raise ValueError("Invalid log level. Must be between 0 and 50.")
    elif isinstance(value, str):
        if value.upper() not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("Invalid log level. Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL.")
    else:
        raise ValueError("Invalid log level. Must be a string or an integer.")

    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    return log_levels.get(value.upper(), logging.DEBUG) if isinstance(value, str) else value



def check_config_yaml_version(value: str) -> str:
    if value != __version__:
        raise ValueError(f"Config file version {value} does not match the program version {__version__}. Either update/re-generate your config.yaml file, or use the command line.")
    return value



class Configs(BaseModel):
    """
    Configs for the program. These should be considered as constants.

    Attributes:
        input_folder (str): Path to the folder containing the files to be converted.
            Defaults to 'input', the name of the input folder in the working directory.
        output_folder (str): Path to the folder where the converted files will be saved.
            Defaults to 'output', the name of the output folder in the working directory.
        max_program_memory (int): Maximum amount of memory in Megabytes the program can use at any one time.
            Defaults to 1024 MB.
        conversion_timeout (int): Maximum amount of time in seconds an API-bounded conversion can run before it is terminated.
            Defaults to 30 seconds.
        log_level (str): Level of logging to be used.
            Defaults to 'INFO'.
        max_connections_per_api (int): Maximum number of concurrent API connections the program can have at any one time.
            Defaults to 3.
        max_cpu_cores (int): Maximum number of threads to be used for processing in the program can use at any one time.
            Defaults to 4.
        batch_size (int): Number of files to be processed in a single batch.
            Defaults to 1024.
        api_key (str): API key for the LLM API.
            Defaults to 'abcde123456'.
        api_url (str): URL for the LLM API.
            Defaults to 'www.example.com'.
        use_docintel (bool): Use Document Intelligence to extract text instead of offline conversion. Requires a valid Document Intelligence Endpoint.
            Defaults to False.
        docintel_endpoint (str): Document Intelligence Endpoint. Required if using Document Intelligence.
            Defaults to 'www.example2.com'.
        version (str): (CLI only) Version of the program.
            Defaults to '0.1.0'.
        help (bool): (CLI only) Show help message and exit.
            Defaults to False.
        pool_refresh_rate (int): Refresh rate in seconds for refreshing resources in the Pools.
            Defaults to 60 seconds.
        pool_health_check_rate (int): Health check rate in seconds for checking resources in the Pools.
            Defaults to 30 seconds.
        print_configs_on_startup (bool): Print the program configs to console on start-up. Sensitive values like API keys will be [REDACTED]. 
            Defaults to False.
    """
    # Paths
    input_folder:            DirectoryPath = Field(default="input")
    output_folder:           DirectoryPath = Field(default="output")
    config_yaml:             FilePath      = Field(default="config.yaml")
    
    max_program_memory:      int = Field(default=1024, ge=128, le=16384, # Between 128MB and 16GB
                                        alias=AliasChoices('MAX_PROGRAM_MEMORY', 'max_program_memory')
                                    )
    max_connections_per_api: int = Field(default=3, ge=1, le=10)
    max_cpu_cores:           int = Field(default=4, ge=1, le=32)
    conversion_timeout:      int = Field(default=30, ge=1, le=300)  # Between 1 and 300 seconds
    max_workers:             int = Field(default=4, ge=1)
    max_queue_size:          int = Field(default=1024, ge=1, le=4096)
    batch_size:              int = Field(default=1024, ge=1, le=4096, alias='batch_size')
    pool_refresh_rate:       int = Field(default=60, ge=1, le=3600)  # Between 1 second and 1 hour
    pool_health_check_rate:  int = Field(default=30, ge=1, le=1800)  # Between 1 second and 30 minutes
    concurrency_limit:       int = Field(default=10, ge=1, le=100)
    
    budget_in_usd:           float = Field(default=25.0, ge=0.0)

    api_key:                 SecretStr = Field(default="abcde123456", min_length=8)
    api_url:                 str       = Field(default="http://www.example.com")
    docintel_endpoint:       str       = Field(default="http://www.example2.com")

    log_level:     Annotated[str | int, AV(convert_log_level)]   = Field(default=logging.DEBUG)
    version:       Annotated[str, AV(check_config_yaml_version)] = Field(default=__version__, pattern=r"^\d+\.\d+\.\d+$")

    use_docintel:             bool = Field(default=False)
    print_configs_on_startup: bool = Field(default=False)

    _logger:           Logger = PrivateAttr(default=None)
    _can_use_llm:      bool = PrivateAttr(default=True)
    _can_use_docintel: bool = PrivateAttr(default=True)


    def __init__(self, **data):
        keys_to_check = ["docintel_endpoint", "api_url", "api_key", "log_level"]
        data = normalize_dict_keys_and_values(data)
        _check_for_invalid_keys(data, keys_to_check)

        super().__init__(**data)

    @model_validator(mode='after')
    def check_for_mock_api_values(self) -> Self:
        if self.api_url == "http://www.example.com":
            print("WARNING: The default LLM API URL is NOT a valid API endpoint. Please update the config file with an actual LLM API endpoint.")
            self._can_use_llm = False
        if self.api_url == "abcde123456":
            print("WARNING: The default LLM API key is NOT a valid API key. Please update the config file with an actual LLM API key.")
            self._can_use_llm = False
        return self

    @model_validator(mode='after')
    def check_for_docintel_endpoint(self) -> Self:
        if self.use_docintel is True and self.docintel_endpoint == "http://www.example2.com":
            print("WARNING: The default Document Intelligence Endpoint is NOT a valid endpoint. Please update the config file with an actual Document Intelligence Endpoint.")
            self._can_use_docintel = False
        return self

    @property
    def can_use_llm(self) -> bool:
        return self._can_use_llm

    @property
    def can_use_docintel(self) -> bool:
        return self._can_use_docintel

    # @property
    # def logger(self) -> Logger:
    #     return self._logger


    # def make_logger(self, name: str, log_level: Optional[int] = None) -> Logger:
    #     """
    #     Create and return a Logger instance.
    #     This Logger class is custom and can be found in the 'logger' folder.

    #     Args:
    #         name (str): The name of the logger.
    #         log_level (Optional[int]): The log level to use. If None, uses the log level from the config.

    #     Returns:
    #         Logger: An instance of the Logger class.
    #     """
    #     _log_level = log_level if log_level is not None else self.log_level
    #     self._logger = Logger(name, _log_level)
    #     return self._logger


    # def make_duck_db(self, db_path: Optional[Path] = None) -> DuckDBPyConnection:
    #     """
    #     Create and return a DuckDB connection.

    #     Args:
    #         db_path (Optional[Path]): The path to the database file. If None, uses an in-memory database.

    #     Returns:
    #         DuckDBPyConnection: A connection to the DuckDB database.
    #     """
    #     _path = db_path if db_path is not None else ':memory:'
    #     return duckdb.connect(_path)
    
configs = Configs()