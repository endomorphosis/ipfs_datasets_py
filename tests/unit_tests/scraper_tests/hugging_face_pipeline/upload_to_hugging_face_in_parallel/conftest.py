import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import sys
import anyio


class FixtureError(Exception):
    """Custom exception for fixture setup failures."""
    pass


@pytest.fixture(scope="session", autouse=True)
def mock_configs_module():
    """Mock the configs module to prevent loading config files during testing"""
    mock_module = MagicMock()
    mock_configs_class = MagicMock()
    mock_module.Configs = mock_configs_class
    mock_module.configs = MagicMock()
    
    sys.modules['ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.configs'] = mock_module
    yield mock_module
    if 'ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.configs' in sys.modules:
        del sys.modules['ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.configs']


@pytest.fixture
def mock_api():
    """Create a mock HfApi with sensible defaults"""
    api = Mock()
    api.list_repo_files = Mock(return_value=[])
    api.upload_folder = Mock(return_value=Mock())
    api.upload_file = Mock(return_value=Mock())
    return api


@pytest.fixture
def mock_rate_limiter():
    """Create a mock rate limiter that doesn't actually wait"""
    limiter = Mock()
    limiter.wait_for_token = Mock(return_value=0.0)
    limiter.request_limit_per_hour = 300
    limiter.tokens = 300
    return limiter


@pytest.fixture
def base_uploader(mock_api, mock_rate_limiter, tmp_path):
    """Create a basic uploader instance with mocked dependencies"""
    try:
        with patch('ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers.hugging_face_pipeline.login'):
            from ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers.hugging_face_pipeline import UploadToHuggingFaceInParallel
            
            configs = Mock()
            configs.REPO_ID = "test-repo"
            configs.HUGGING_FACE_USER_ACCESS_TOKEN = "hf_test_token"
            configs.TARGET_DIR_NAME = "municipal_laws"
            configs.paths = Mock()
            configs.paths.INPUT_FROM_SQL = tmp_path / "input"
            configs.paths.INPUT_FROM_SQL.mkdir(exist_ok=True)
            
            resources = {"logger": Mock()}
            
            uploader = UploadToHuggingFaceInParallel(resources=resources, configs=configs)
            uploader.api = mock_api
            uploader.rate_limiter = mock_rate_limiter
            
            return uploader
    except Exception as e:
        raise FixtureError(f"base_uploader fixture failed: {e}") from e


def create_file_structure(base_dir: Path, structure: dict[str, list[str]]) -> None:
    """
    Create a file structure from a dictionary.
    
    Args:
        base_dir: Base directory to create structure in
        structure: Dict mapping folder names to lists of file names
    """
    for folder_name, files in structure.items():
        folder = base_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            (folder / file_name).write_text(f"content_{file_name}")


@pytest.fixture
def output_directory_10_parquet_files(base_uploader, tmp_path):
    """Setup with 2 folders containing 5 parquet files each (10 total)"""
    try:
        target_name = "municipal_laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            "folder_0": [f"file_{i}.parquet" for i in range(5)],
            "folder_1": [f"file_{i}.parquet" for i in range(5)]
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "folder_count": 2,
            "file_count": 10
        }
    except Exception as e:
        raise FixtureError(f"output_directory_10_parquet_files failed: {e}") from e


@pytest.fixture
def output_directory_mixed_files(base_uploader, tmp_path):
    """Setup with 1 folder containing 5 parquet and 3 json files"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            "folder_0": [f"file_{i}.parquet" for i in range(5)] + [f"file_{i}.json" for i in range(3)]
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "file_pattern": ".parquet"
        }
    except Exception as e:
        raise FixtureError(f"output_directory_mixed_files failed: {e}") from e


@pytest.fixture
def output_directory_20_files(base_uploader, tmp_path):
    """Setup with 4 folders containing 5 files each (20 total)"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            f"folder_{i}": [f"file_{j}.parquet" for j in range(5)]
            for i in range(4)
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        # Set limited tokens for rate limiting tests
        base_uploader.rate_limiter.tokens = 5
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "max_concurrency": 10,
            "folder_count": 4
        }
    except Exception as e:
        raise FixtureError(f"output_directory_20_files failed: {e}") from e


@pytest.fixture
def api_fails_then_succeeds(base_uploader, tmp_path):
    """Setup API to fail once then succeed"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {"folder_0": [f"file_{i}.parquet" for i in range(3)]}
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        # Configure API to fail once then succeed
        base_uploader.api.upload_folder = Mock(
            side_effect=[Exception("API Error"), Mock()]
        )
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name
        }
    except Exception as e:
        raise FixtureError(f"api_fails_then_succeeds failed: {e}") from e


@pytest.fixture
def api_always_fails(base_uploader, tmp_path):
    """Setup API to always fail"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {"folder_0": [f"file_{i}.parquet" for i in range(3)]}
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        # Configure API to always fail
        base_uploader.api.upload_folder = Mock(side_effect=Exception("API Error"))
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "max_retries": 3
        }
    except Exception as e:
        raise FixtureError(f"api_always_fails failed: {e}") from e


@pytest.fixture
def output_directory_100_files(base_uploader, tmp_path):
    """Setup with 20 folders containing 5 files each (100 total)"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            f"folder_{i}": [f"file_{j}.parquet" for j in range(5)]
            for i in range(20)
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "max_concurrency": 5,
            "folder_count": 20
        }
    except Exception as e:
        raise FixtureError(f"output_directory_100_files failed: {e}") from e


@pytest.fixture
def output_directory_with_folders(base_uploader, tmp_path):
    """Setup with 2 folders containing 4 files each (8 total)"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            f"folder_{i}": [f"file_{j}.parquet" for j in range(4)]
            for i in range(2)
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "folder_count": 2,
            "total_files": 8
        }
    except Exception as e:
        raise FixtureError(f"output_directory_with_folders failed: {e}") from e


@pytest.fixture
def output_directory_mixed_results(base_uploader, tmp_path):
    """Setup with 4 folders where some succeed, some retry, some fail"""
    try:
        target_name = "laws"
        data_dir = base_uploader.sql_input / target_name
        data_dir.mkdir(parents=True, exist_ok=True)
        
        structure = {
            f"folder_{i}": [f"file_{j}.parquet" for j in range(5)]
            for i in range(4)
        }
        create_file_structure(data_dir, structure)
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        # Configure mixed results:
        # folder_0: succeeds immediately
        # folder_1: succeeds immediately
        # folder_2: fails once, then succeeds (retry)
        # folder_3: fails all 3 attempts (failure)
        responses = [
            Mock(),  # folder_0 success
            Mock(),  # folder_1 success
            Exception("API Error"),  # folder_2 first attempt
            Mock(),  # folder_2 retry success
            Exception("API Error"),  # folder_3 attempt 1
            Exception("API Error"),  # folder_3 attempt 2
            Exception("API Error"),  # folder_3 attempt 3
        ]
        
        base_uploader.api.upload_folder = Mock(side_effect=responses)
        
        return {
            "uploader": base_uploader,
            "output_dir": output_dir,
            "target_name": target_name,
            "expected_uploaded": 3,  # folders 0, 1, 2
            "expected_failed": 1,     # folder 3
            "expected_retried": 3     # folder 2 (1 retry) + folder 3 (2 retries) = 3 total retries
        }
    except Exception as e:
        raise FixtureError(f"output_directory_mixed_results failed: {e}") from e