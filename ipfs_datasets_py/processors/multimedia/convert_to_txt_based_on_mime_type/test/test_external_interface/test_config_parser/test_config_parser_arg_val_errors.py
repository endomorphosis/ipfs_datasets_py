#!/usr/bin/env python3 -m pytest

import pytest
import yaml
from pathlib import Path
from typing import Any


from pydantic import ValidationError


from external_interface.config_parser.config_parser import ConfigParser, Configs


# NOTE Passed all these tests, but they also kept overwriting the configs.yaml file.
class TestConfigParserValidation:

    @pytest.fixture
    def setup_config_file(self, tmp_path: Path) -> None:

        """Helper to write test config to configs.yaml"""
        def _write_config(config_data: dict[str, Any]) -> None:
            with open('configs.yaml', 'w') as f:
                yaml.dump(config_data, f)

        return _write_config



    # # def test_empty_config(self, setup_config_file):
    # #     """Test handling of empty config file"""
    # #     setup_config_file({})
    # #     parser = ConfigParser()
    # #     with pytest.raises(AttributeError):
    # #         parser.load_and_parse_configs_file()

    # def test_invalid_types(self, setup_config_file):
    #     """Test handling of invalid types for each field"""
    #     invalid_configs = {
    #         "max_memory": "not_an_int",
    #         "conversion_timeout": "30s",
    #         "max_connections_per_api": 3.14,
    #         "max_threads": "four",
    #         "batch_size": -1024,
    #         "pool_refresh_rate": "1m",
    #         "pool_health_check_rate": True,
    #         "use_docintel": "yes"  # should be boolean
    #     }
    #     setup_config_file(invalid_configs)
    #     parser = ConfigParser()
    #     with pytest.raises(ValidationError):
    #         parser.load_and_parse_configs_file()

    # def test_invalid_ranges(self, setup_config_file):
    #     """Test handling of out-of-range values"""
    #     invalid_ranges = {
    #         "max_memory": -1024,
    #         "conversion_timeout": 0,
    #         "max_connections_per_api": -3,
    #         "max_threads": 0,
    #         "batch_size": -1,
    #         "pool_refresh_rate": -60,
    #         "pool_health_check_rate": -30
    #     }
    #     setup_config_file(invalid_ranges)
    #     parser = ConfigParser()
    #     with pytest.raises(ValidationError, match=r"Input should be.*"):
    #         parser.load_and_parse_configs_file()

    # def test_invalid_log_level(self, setup_config_file):
    #     """Test handling of invalid log level"""
    #     invalid_log = {
    #         "log_level": "SUPER_DEBUG"
    #     }
    #     setup_config_file(invalid_log)
    #     parser = ConfigParser()
    #     with pytest.raises(ValidationError, match="String should match pattern"):
    #         parser.load_and_parse_configs_file()

    # def test_invalid_urls(self, setup_config_file):
    #     """Test handling of invalid URLs"""
    #     invalid_urls = {
    #         "api_url": "not_a_url",
    #         "docintel_endpoint": "also_not_a_url"
    #     }
    #     setup_config_file(invalid_urls)
    #     parser = ConfigParser()
    #     with pytest.raises(ValidationError, match="Input should be a valid URL, relative URL without a base"):
    #         parser.load_and_parse_configs_file()

    # def test_missing_required_paired_values(self, setup_config_file):
    #     """Test handling of missing paired required values"""
    #     # Case 1: Missing API URL when key is provided
    #     missing_url = {
    #         "api_key": "12345678"
    #     }
    #     setup_config_file(missing_url)
    #     parser = ConfigParser()
    #     configs = parser.load_and_parse_configs_file()
    #     assert not configs.can_use_llm

    #     # Case 2: Missing DocIntel endpoint when use_docintel is True
    #     missing_endpoint = {
    #         "use_docintel": True
    #     }
    #     setup_config_file(missing_endpoint)
    #     parser = ConfigParser()
    #     configs = parser.load_and_parse_configs_file()
    #     assert not configs.can_use_docintel

    # def test_invalid_folder_paths(self, setup_config_file):
    #     """Test handling of invalid folder paths"""
    #     invalid_paths = {
    #         "input_folder": "/not/a/real/path/input",
    #         "output_folder": "C:\\invalid\\windows\\path\\output"
    #     }
    #     setup_config_file(invalid_paths)
    #     parser = ConfigParser()
    #     with pytest.raises(ValueError, match=r".*is invalid or does not exist.*"):
    #         parser.load_and_parse_configs_file()

    # # NOTE None of the settings in the YAML are inherently contradictory, especially with clamped ranges.
    # # However, I'm keeping this in case more configs are added in the future that DO conflict.
    # # def test_conflicting_settings(self, setup_config_file):
    # #     """Test handling of conflicting settings"""
    # #     conflicting_settings = {
    # #         "max_threads": 8,
    # #         "max_connections_per_api": 10  # Should not be greater than max_threads
    # #     }
    # #     setup_config_file(conflicting_settings)
    # #     parser = ConfigParser()
    # #     with pytest.raises(ValueError, match="Conflicting settings"):
    # #         parser.load_and_parse_configs_file()

    # def test_invalid_whitespace(self, setup_config_file):
    #     """Test handling of invalid whitespace in values"""
    #     invalid_whitespace = {
    #         "api_key": "123 456",  # Space in API key
    #         "log_level": "INFO ",  # Trailing space
    #         "input_folder": " input"  # Leading space
    #     }
    #     setup_config_file(invalid_whitespace)
    #     parser = ConfigParser()
    #     with pytest.raises(ValueError, match=r"Invalid whitespace present in values for"):
    #         parser.load_and_parse_configs_file()

    # # NOTE These are values are coerced into being all lower case EXCEPT for log_level
    # # def test_case_sensitivity(self, setup_config_file):
    # #     """Test handling of case-sensitive values"""
    # #     invalid_case = {
    # #         "log_level": "info",  # Should be "INFO"
    # #         "USE_DOCINTEL": True  # Should be "use_docintel"
    # #     }
    # #     setup_config_file(invalid_case)
    # #     parser = ConfigParser()
    # #     with pytest.raises(ValueError, match="Invalid case in config key or value"):
    # #         parser.load_and_parse_configs_file()

    # # NOTE Duplicate keys get stripped out as a side-effect of trimming the dictionary.
    # # def test_duplicate_keys(self, setup_config_file):
    # #     """Test handling of duplicate keys in YAML"""
    # #     # Note: This requires manual YAML string creation to test duplicate keys
    # #     yaml_content = """
    # #     max_memory: 1024
    # #     max_memory: 2048
    # #     """
    # #     with open('configs.yaml', 'w') as f:
    # #         f.write(yaml_content)
    # #     parser = ConfigParser()
    # #     with pytest.raises(ValueError, match=r"Multiple keys with the same name found in config file.*"):
    # #         parser.load_and_parse_configs_file()