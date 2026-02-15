#!/usr/bin/env


from __future__ import annotations
from __version__ import __version__

from argparse import Namespace
from pathlib import Path


#from pydantic_models.configs import Configs
from pydantic import (
    BaseModel, 
    Field, 
    field_serializer,
    HttpUrl, 
    model_validator,
    PrivateAttr,
    field_validator,
    ValidationError
)
import yaml


from configs.configs import Configs
from external_interface.config_parser.resources._print_configs_on_startup import _print_configs_on_startup


class ConfigParser:
    """
    Load, save, and parse external commands, from a config file, command line, or both.
    NOTE: The configuration file is hard-coded to be named 'config.yaml'. 
        If renamed or deleted, the program will attempt to create another using hard-coded default values.
        This includes mock-values for API keys and URLs.

    External Commands:
        input_folder (str): Path to the folder containing the files to be converted.
            Defaults to 'input', the name of the input folder in the working directory.
        output_folder (str): Path to the folder where the converted files will be saved.
            Defaults to 'output', the name of the output folder in the working directory.
        max_memory (int): Maximum amount of memory in Megabytes the program can use at any one time.
            Defaults to 1024 MB.
        conversion_timeout (int): Maximum amount of time in seconds an API-bounded conversion can run before it is terminated.
            Defaults to 30 seconds.
        log_level (str): Level of logging to be used.
            Defaults to 'INFO'.
        max_connections_per_api (int): Maximum number of concurrent API connections the program can have at any one time.
            Defaults to 3.
        max_threads (int): Maximum number of threads to be used for processing the program can use at any one time.
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

    Attributes:
    - configs_file_path: Optional[str]: The path to the config file.

    Methods:
    - load_and_parse_configs_file(): Load in a config file and parse it into an exportable Configs object.
    - parse_command_line(): Parse command line arguments into an exportable Configs object.
    - save_to_configs_file(): Save the current config settings to a config file.
    """

    def __init__(self):
        """
        Class Constructor. Initializes the ConfigParser object.

        Potential global issues:
         - Thread safety concerns across all methods
         - Memory leaks from improper resource handling
         - Inconsistent state between file and command line configs
         - Error handling and logging consistency
         - Security audit logging requirements
         - Configuration change notification system
         - Configuration version management
         - Backup and recovery procedures
         - Configuration inheritance and override rules
        """
        self._ROOT_DIR = Path(__file__).parent.parent
        if not self._ROOT_DIR.exists():
            raise FileNotFoundError(f"Cannot find the root directory:{self._ROOT_DIR}")

        self.configs_file_path: Path = self._ROOT_DIR / "configs.yaml"

        if not self.configs_file_path.exists():
            default_config = Configs()
            make_config_file = input("""
                Cannot find configs.yaml in root directory. Would you like to create a new config file from the program defaults? (Y/n): 
                """)
            if make_config_file.lower() == "y":
                
                self.save_current_config_settings_to_configs_file(default_config)
            else:
                raise FileNotFoundError(f"Config file not found at {self.configs_file_path}")


    def load_and_parse_configs_file(self) -> Configs:
        """
        Load in a config file and parse it into an exportable Configs object.
        
        Args:
            None.

        Returns:
            Configs: An exportable Configs object containing the parsed settings from the config file.

        Potential Issues:

            4. Version and compatibility issues:
                - Platform-specific path separator issues (e.g. Windows vs. Unix).

            5. Data integrity issues:
                - Circular references in config file.
                - Default values overriding explicit NULL values.

            7. Resource-related issues:
                - Race conditions if multiple processes try to read the config file simultaneously.

            8. Security-related issues:
                - Arguments containing sensitive data exposed in process list
                - Command injection vulnerabilities in argument parsing.
        """
        if not self.configs_file_path.exists():
            raise FileNotFoundError(f"Config file not found at {self.configs_file_path}")

        try:
            with open(self.configs_file_path, 'r', encoding='utf-8') as file:
                configs_dict = yaml.safe_load(file)

        except PermissionError:
            raise PermissionError(f"Permission denied when accessing config file at {self.configs_file_path}")
        except IOError as e:
            raise PermissionError(f"Unable to read config file at {self.configs_file_path}: {e}")
        except yaml.YAMLError:
            raise yaml.YAMLError(f"Invalid YAML format in config file at {self.configs_file_path}")

        if configs_dict is None or not configs_dict:
            raise ValueError(f"Config file at {self.configs_file_path} is empty or invalid YAML")

        try: 
            configs = Configs(**configs_dict)
            configs.model_validate()
        except TypeError as e:
            raise ValueError(f"Invalid configuration structure: {e}")

        _print_configs_on_startup(configs)
        return configs


    def parse_command_line(self, args: Namespace) -> Configs:
        """
        Parse command line arguments into an exportable Configs object.
        
        Args:
            None.

        Returns:
            Configs: An exportable Configs object containing the parsed settings from the config file.

        Potential Issues:

            2. Parsing and Formatting:
                - Unicode/special characters in arguments causing parsing errors.
                - Invalid escape sequences in argument values.
                - Case sensitivity issues in argument names.
                - Platform-specific argument parsing differences.

            3. Environmental and Path Issues:
                - Environment variables referenced in arguments don't exist.
                - Relative path resolution failures.

            4. Security Concerns:
                - Command injection vulnerabilities in argument parsing.

            5. Data Integrity:
                - Circular references in command line argument values.

        """
        configs = Configs(
            input_folder=args.input_folder,
            output_folder=args.output_folder,
            max_memory=args.max_memory,
            conversion_timeout=args.conversion_timeout,
            log_level=args.log_level,
            max_connections_per_api=args.max_connections_per_api,
            max_threads=args.max_threads,
            batch_size=args.batch_size,
            api_key=args.api_key,
            api_url=args.api_url,
            use_docintel=args.use_docintel,
            docintel_endpoint=args.docintel_endpoint,
            pool_refresh_rate=args.pool_refresh_rate,
            pool_health_check_rate=args.pool_health_check_rate
        )
        _print_configs_on_startup(configs)
        return configs


    def _save_to_yaml(self, configs: Configs) -> None:
        """
        Save the provided configs to a YAML file.

        This method attempts to write the provided Configs object to the YAML file
        specified by self.configs_file_path. It uses yaml.safe_dump to convert the
        config object to YAML format.
        NOTE Any existing file at self.configs_file_path will be overwritten.

        Args:
            configs (Configs): The configuration object to be saved.

        Returns:
            None

        Raises:
            IOError: If there's an error writing to the config file.
            yaml.YAMLError: If there's an error dumping the config to YAML format.
        """
        try:
            with open(self.configs_file_path, "w", encoding='utf-8') as file:
                yaml.safe_dump(
                    configs.model_dump(), 
                    file, 
                    default_flow_style=False
                )
        except IOError as e:
            print(f"Error writing to config file: {e}")
        except yaml.YAMLError as e:
            print(f"Error dumping config to YAML: {e}")


    def save_current_config_settings_to_configs_file(self, configs: Configs) -> None:
        """
        Save the current config settings to a config file 'config.yaml' in the current working directory.

        Args:
            configs (Configs): The current config settings to be saved

        Potential Issues:
            2. Permission and access issues:
                - Config file to be saved to is not writable.
                - Permission escalation attempts through symlinks.
                - Inability to maintain file permissions/ownership.
                - File locking issues in multi-process scenarios.

            3. Data integrity and validation:
                - No arguments are provided.

            5. Operational and process issues:
                - Backup/temporary file creation failures.
                - Version control conflicts.
                - Transaction atomicity failures during save.
        """
        try:
            configs.model_validate()
        except ValidationError:
            print("Invalid config settings provided.")

        if self.configs_file_path.exists():
            make_config_file = input("""
                configs.yaml already exists in root directory. Overwrite? (Y/n): 
                """)
            if make_config_file.lower() == "y":
                self._save_to_yaml(configs)
        else:
            self._save_to_yaml(configs)

