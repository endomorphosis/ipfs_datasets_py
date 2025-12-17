import pytest
from pathlib import Path
from unittest.mock import Mock



try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as e:
    raise ImportError(f"Required packages for testing are not installed. Please install pandas and pyarrow: {e}")


class FixtureError(Exception):
    """Custom exception for fixture setup failures."""
    pass


@pytest.fixture
def constants(tmp_path):
    """Given a HuggingFace repository exists with ID "test-repo" 
    And the user has a valid access token
    And the rate limiter allows 300 requests per hour
    """
    return {
        "repository_id": "test-repo",
        "user_access_token": "hf_test_token_12345",
        "rate_limiter_300_per_hour": 300,
        "inputs_from_sql": tmp_path / "input_from_sql"
    }



@pytest.fixture
def hugging_face_repository(repository_id, user_access_token, rate_limiter_300_per_hour):
    """
    Given a HuggingFace repository exists with ID "test-repo"
    And the user has a valid access token
    And the rate limiter allows 300 requests per hour
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers.hugging_face_pipeline import UploadToHuggingFaceInParallel
        
        configs = Mock()
        configs.REPO_ID = repository_id
        configs.HUGGING_FACE_USER_ACCESS_TOKEN = user_access_token
        configs.paths = Mock()
        configs.paths.INPUT_FROM_SQL = Path("/data/input")
        
        resources = {}
        
        uploader = UploadToHuggingFaceInParallel(resources=resources, configs=configs)
        uploader.rate_limiter = Mock()
        uploader.rate_limiter.request_limit_per_hour = rate_limiter_300_per_hour
        uploader.api = Mock()
        
        return uploader
    except Exception as e:
        raise FixtureError(f"hugging_face_repository fixture setup failed: {e}") from e


@pytest.fixture
def rate_limiter_with_limited_tokens(hugging_face_repository):
    """Given the rate limiter has 5 tokens"""
    try:
        token_count = 5
        hugging_face_repository.rate_limiter.tokens = token_count
        return hugging_face_repository
    except Exception as e:
        raise FixtureError(f"rate_limiter_with_limited_tokens fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_with_files(hugging_face_repository, tmp_path):
    """Given an output directory at "/data/output" contains 3 files and target directory name "laws" """
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        file_count = 3
        for i in range(file_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"content_{i}")
        
        target_name = "laws"
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "file_count": file_count
        }
    except Exception as e:
        raise FixtureError(f"output_directory_with_files fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_with_folders(hugging_face_repository, tmp_path):
    """Given an output directory at "/data/output" contains 8 files in 2 folders and target directory name "laws" """
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        folder_count = 2
        files_per_folder = 4
        total_files = 8
        
        for i in range(folder_count):
            folder_path = output_dir / f"folder_{i}"
            folder_path.mkdir()
            for j in range(files_per_folder):
                file_path = folder_path / f"file_{j}.parquet"
                file_path.write_text(f"content_{i}_{j}")
        
        target_name = "laws"
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "folder_count": folder_count,
            "total_files": total_files
        }
    except Exception as e:
        raise FixtureError(f"output_directory_with_folders fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_10_parquet_files(hugging_face_repository, tmp_path):
    """Setup output directory with 10 parquet files"""
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        file_count = 10
        for i in range(file_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"content_{i}")
        
        target_name = "municipal_laws"
        
        hugging_face_repository.api.upload_folder = Mock(return_value=Mock())
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "file_count": file_count
        }
    except Exception as e:
        raise FixtureError(f"output_directory_10_parquet_files fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_mixed_files(hugging_face_repository, tmp_path):
    """Setup output directory with 5 parquet and 3 json files"""
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        parquet_count = 5
        json_count = 3
        
        for i in range(parquet_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"parquet_content_{i}")
        
        for i in range(json_count):
            file_path = output_dir / f"file_{i}.json"
            file_path.write_text(f"json_content_{i}")
        
        target_name = "laws"
        file_pattern = ".parquet"
        
        hugging_face_repository.api.upload_folder = Mock(return_value=Mock())
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "file_pattern": file_pattern,
            "parquet_count": parquet_count,
            "json_count": json_count
        }
    except Exception as e:
        raise FixtureError(f"output_directory_mixed_files fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_20_files(rate_limiter_with_limited_tokens, tmp_path):
    """Setup output directory with 20 files"""
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        file_count = 20
        for i in range(file_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"content_{i}")
        
        target_name = "laws"
        max_concurrency_value = 10
        
        rate_limiter_with_limited_tokens.api.upload_folder = Mock(return_value=Mock())
        rate_limiter_with_limited_tokens.rate_limiter.wait_for_token = Mock(return_value=0.1)
        
        return {
            "uploader": rate_limiter_with_limited_tokens,
            "output_dir": output_dir,
            "target_name": target_name,
            "max_concurrency": max_concurrency_value,
            "file_count": file_count
        }
    except Exception as e:
        raise FixtureError(f"output_directory_20_files fixture setup failed: {e}") from e


@pytest.fixture
def api_fails_then_succeeds(output_directory_with_files):
    """Setup API to fail once then succeed"""
    try:
        uploader = output_directory_with_files["uploader"]
        
        fail_count = 1
        success_response = Mock()
        
        uploader.api.upload_folder = Mock(side_effect=[Exception("API Error")] * fail_count + [success_response] * 10)
        
        output_directory_with_files["fail_count"] = fail_count
        
        return output_directory_with_files
    except Exception as e:
        raise FixtureError(f"api_fails_then_succeeds fixture setup failed: {e}") from e


@pytest.fixture
def api_always_fails(output_directory_with_files):
    """Setup API to always fail"""
    try:
        uploader = output_directory_with_files["uploader"]
        
        uploader.api.upload_folder = Mock(side_effect=Exception("API Error"))
        
        max_retries_value = 3
        output_directory_with_files["max_retries"] = max_retries_value
        
        return output_directory_with_files
    except Exception as e:
        raise FixtureError(f"api_always_fails fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_100_files(hugging_face_repository, tmp_path):
    """Setup output directory with 100 files"""
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        file_count = 100
        for i in range(file_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"content_{i}")
        
        target_name = "laws"
        max_concurrency_value = 5
        
        hugging_face_repository.api.upload_folder = Mock(return_value=Mock())
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "max_concurrency": max_concurrency_value,
            "file_count": file_count
        }
    except Exception as e:
        raise FixtureError(f"output_directory_100_files fixture setup failed: {e}") from e


@pytest.fixture
def output_directory_mixed_results(hugging_face_repository, tmp_path):
    """Setup output directory with 15 files and mixed upload results"""
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        file_count = 15
        for i in range(file_count):
            file_path = output_dir / f"file_{i}.parquet"
            file_path.write_text(f"content_{i}")
        
        target_name = "laws"
        
        success_first_attempt = 12
        success_second_attempt = 2
        fail_after_retries = 1
        
        responses = []
        responses.extend([Mock()] * success_first_attempt)
        responses.extend([Exception("API Error"), Mock()] * success_second_attempt)
        responses.extend([Exception("API Error")] * (fail_after_retries * 4))
        
        hugging_face_repository.api.upload_folder = Mock(side_effect=responses)
        
        return {
            "uploader": hugging_face_repository,
            "output_dir": output_dir,
            "target_name": target_name,
            "file_count": file_count,
            "success_first": success_first_attempt,
            "success_second": success_second_attempt,
            "failed": fail_after_retries
        }
    except Exception as e:
        raise FixtureError(f"output_directory_mixed_results fixture setup failed: {e}") from e
