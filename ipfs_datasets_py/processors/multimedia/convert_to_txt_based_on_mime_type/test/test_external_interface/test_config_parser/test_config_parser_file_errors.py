# #!/usr/bin/env python3 -m pytest

# import argparse
# from unittest.mock import patch


# import pytest
# import yaml


# from external_interface.config_parser.config_parser import ConfigParser
# from pydantic_models.configs import Configs


# @pytest.fixture
# def valid_config_dict():
#     """Valid configuration dictionary with all default values"""
#     dict_ = {
#         "input_folder": "input",
#         "output_folder": "output",
#         "max_memory": 1024,
#         "conversion_timeout": 30,
#         "log_level": "INFO",
#         "max_connections_per_api": 3,
#         "max_threads": 4,
#         "batch_size": 1024,
#         "api_key": "abcde12345",
#         "api_url": "http://www.example.com",
#         "use_docintel": False,
#         "docintel_endpoint": "http://www.example2.com",
#         "version": "0.1.0",
#         "help": False,
#         "pool_refresh_rate": 60,
#         "pool_health_check_rate": 30
#     }
#     return Configs(**dict_)


# @pytest.fixture
# def minimal_valid_config_dict():
#     """Minimal valid configuration with only required fields"""
#     dict_ = {
#         "input_folder": "input",
#         "output_folder": "output"
#     }
#     return Configs(**dict_)


# @pytest.fixture
# def invalid_config_dicts():
#     """Dictionary of various invalid configurations for testing"""
#     return {
#         "missing_required": {
#             "input_folder": "input",
#             "output_folder": "output"
#         },
#         "invalid_types": {
#             "api_key": 6.4,
#             "api_url": False,
#             "max_memory": "not_an_integer",
#             "max_threads": 3.14
#         },
#         "out_of_range": {
#             "api_key": "abcde12345&&&&&#####$$$$$````",
#             "api_url": "wwwwwwwwwwwwww.example.com",
#             "max_connections_per_api": -1,
#             "max_threads": 0
#         },
#         "invalid_pairwise": {
#             "api_key": "abcde12345",
#             "api_url": "",  # Empty URL
#             "use_docintel": True,
#             "docintel_endpoint": ""  # Empty endpoint despite use_docintel=True
#         }
#     }


# @pytest.fixture
# def valid_config_file(tmp_path):
#     """Creates a valid configs file for testing"""
#     config_path = tmp_path / "configs.yaml"
#     config_content = {
#         "input_folder": "test_input",
#         "output_folder": "test_output",
#         "max_memory": 2048,
#         "conversion_timeout": 60,
#         "log_level": "DEBUG",
#         "max_connections_per_api": 5,
#         "max_threads": 8,
#         "batch_size": 512,
#         "api_key": "test_key_123",
#         "api_url": "https://test.example.com",
#         "use_docintel": True,
#         "docintel_endpoint": "https://test.example2.com",
#         "pool_refresh_rate": 30,
#         "pool_health_check_rate": 15
#     }
#     config_path.write_text(yaml.dump(config_content))
#     return config_path


# @pytest.fixture
# def command_line_args():
#     """Dictionary of various command line argument combinations"""
#     return {
#         "minimal": [
#             "--input-folder", "cli_input",
#             "--output-folder", "cli_output",
#         ],
#         "full": [
#             "--input-folder", "cli_input",
#             "--output-folder", "cli_output",
#             "--max-memory", "4096",
#             "--conversion-timeout", "90",
#             "--log-level", "WARNING",
#             "--max-connections-per-api", "10",
#             "--max-threads", "16",
#             "--batch-size", "256",
#             "--llm-api-key", "cli_test_key",
#             "--llm-api-url", "https://cli.example.com",
#             "--use-docintel",
#             "--docintel-endpoint", "https://cli.example2.com",
#             "--pool-refresh-rate", "45",
#             "--pool-health-check-rate", "20"
#         ],
#         "help": ["--help"],
#         "version": ["--version"]
#     }


# @pytest.fixture
# def mock_environment_vars():
#     """Dictionary of environment variables for testing"""
#     return {
#         "api_key": "env_test_key",
#         "api_url": "https://env.example.com",
#         "MAX_MEMORY": "8192",
#         "LOG_LEVEL": "ERROR"
#     }


# ##### TEST BASIC FUNCTIONALITY #####

# # NOTE This test works.
# # def test_load_valid_config_file(valid_config_file):
# #     parser = ConfigParser()
# #     parser.configs_file_path = valid_config_file
# #     configs = parser.load_and_parse_configs_file()
# #     assert configs is not None

# # def test_parse_minimal_command_line(command_line_args):
# #     parser = ConfigParser()
# #     arg_parser = argparse.ArgumentParser()
# #     arg_parser.add_argument('--input-folder', required=True)
# #     arg_parser.add_argument('--output-folder', required=True)
# #     args = arg_parser.parse_args(command_line_args['minimal'])

# #     with patch.object(parser, 'parse_command_line', return_value=vars(args)):
# #         configs = parser.parse_command_line(args)
# #         assert configs is not None
# #         assert configs['input_folder'] == 'cli_input'
# #         assert configs['output_folder'] == 'cli_output'

# # NOTE This saves over the configs in the folder. I've tested it, it works.
# # def test_save_config(tmp_path, valid_config_dict):
# #     parser = ConfigParser()
# #     parser.configs_file_path = tmp_path / "configs.yaml"
# #     parser.save_current_config_settings_to_configs_file(valid_config_dict)
# #     assert parser.configs_file_path.exists()

# #### TEST ERROR HANDLING #####

# #### load_and_parse_configs_file() File-related/Permission Errors####

# # def test_config_file_not_found(tmp_path):
# #     parser = ConfigParser()
# #     parser.configs_file_path = tmp_path / "non_existent.yaml"
# #     with pytest.raises(FileNotFoundError):
# #         parser.load_and_parse_configs_file()

# # def test_empty_config_file(tmp_path):
# #     config_path = tmp_path / "empty.yaml"
# #     config_path.touch()  # Creates empty file
# #     parser = ConfigParser()
# #     parser.configs_file_path = config_path
# #     with pytest.raises(ValueError, match="Config file .* is empty or invalid YAML"):
# #         parser.load_and_parse_configs_file()

# # TODO Figure out a way to reliably test permission errors. They're such a bitch to set up!
# # def test_permission_denied_config_file(tmp_path):
# #     mock = mock_open()
# #     mock.side_effect = PermissionError("Permission denied")
    
# #     with patch('builtins.open', mock):
# #         config_path = tmp_path / "dummy.yaml"
# #         parser = ConfigParser()
# #         parser.configs_file_path = config_path
# #         with pytest.raises(PermissionError, match="Permission denied"):
# #             parser.load_and_parse_configs_file()

# # def test_config_file_malformed(tmp_path):
# #     config_path = tmp_path / "configs.yaml"
# #     config_path.write_text("This is not valid YAML: :")
# #     parser = ConfigParser()
# #     parser.configs_file_path = config_path
# #     with pytest.raises(yaml.YAMLError):
# #         parser.load_and_parse_configs_file()


# # def test_invalid_yaml_config_file(tmp_path):
# #     config_path = tmp_path / "invalid.yaml"
# #     config_path.write_text("invalid: yaml: content: :")  # Invalid YAML syntax
# #     parser = ConfigParser()
# #     parser.configs_file_path = config_path
# #     with pytest.raises(yaml.YAMLError, match="Invalid YAML format in config file"):
# #         parser.load_and_parse_configs_file()


# # def test_config_file_invalid_types(tmp_path):
# #     config_path = tmp_path / "invalid_types.yaml"
# #     test_cases = [
# #         ("just a string", "string instead of mapping"),
# #         ("42", "number instead of mapping"),
# #         ("[1, 2, 3]", "list instead of mapping"),
# #         ("true", "boolean instead of mapping")
# #     ]
    
# #     parser = ConfigParser()
# #     parser.configs_file_path = config_path
    
# #     for yaml_content, case_desc in test_cases:
# #         config_path.write_text(yaml_content)
# #         with pytest.raises(ValueError, match=r"Invalid configuration structure.*"), \
# #              pytest.raises(TypeError, match=".*mapping"):
# #             parser.load_and_parse_configs_file()


# # NOTE Not necessary, as the configs.yaml file is hardcoded to be named 'configs.yaml'
# # The program will prompt the user to make another if it can't find it.
# # def test_multiple_config_files(tmp_path):
# #     config_path1 = tmp_path / "configs1.yaml"
# #     config_path2 = tmp_path / "configs2.yaml"
# #     config_path1.touch()
# #     config_path2.touch()
    
# #     with patch('os.getcwd', return_value=str(tmp_path)):
# #         parser = ConfigParser()
# #         with pytest.raises(ValueError, match="Multiple config files found"):
# #             parser.load_and_parse_configs_file()

# #### load_and_parse_configs_file() Argument Validation Issues ####





# #### load_and_parse_configs_file() Version and compatibility Issues ####

# #### load_and_parse_configs_file() Data Integrity Issues ####

# #### load_and_parse_configs_file() Environmental Issues ####

# #### load_and_parse_configs_file() Resource-related Issues ####

# #### load_and_parse_configs_file() Security-related Issues ####


# #### parse_command_line() ####


# #### save_current_config_settings_to_configs_file() #### 

