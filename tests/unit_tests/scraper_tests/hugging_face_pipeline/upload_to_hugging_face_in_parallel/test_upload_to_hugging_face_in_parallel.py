"""Test upload files to HuggingFace in parallel."""
import pytest



class TestFilesUploadSuccessfullyWhenAPIIsAvailable:
    """Files upload successfully when API is available"""

    @pytest.mark.asyncio
    async def test_upload_all_files(self, output_directory_10_parquet_files):
        """
        Given an output directory at "/data/output" contains 10 parquet files and target directory name is "municipal_laws"
        When upload_to_hugging_face_in_parallel is called
        Then the return value contains "uploaded": 10, "failed": 0, "retried": 0
        """
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        
        expected_uploaded = 10
        expected_failed = 0
        expected_retried = 0
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )
        
        assert result == {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}, f"expected {{'uploaded': {expected_uploaded}, 'failed': {expected_failed}, 'retried': {expected_retried}}}, got {result}"


class TestFilePatternFiltersDetermineWhichFilesUpload:
    """File pattern filters determine which files upload"""

    @pytest.mark.asyncio
    async def test_upload_only_matching_files(self, output_directory_mixed_files):
        """
        Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then 5 files are uploaded
        """
        uploader = output_directory_mixed_files["uploader"]
        output_dir = output_directory_mixed_files["output_dir"]
        target_name = output_directory_mixed_files["target_name"]
        file_pattern = output_directory_mixed_files["file_pattern"]
        expected_count = output_directory_mixed_files["parquet_count"]
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            file_path_ending=file_pattern
        )
        
        actual_uploaded = result["uploaded"]
        
        assert actual_uploaded == expected_count, f"expected {expected_count}, got {actual_uploaded}"

    @pytest.mark.asyncio
    async def test_skip_non_matching_files(self, output_directory_mixed_files):
        """
        Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then 3 files are not uploaded
        """
        uploader = output_directory_mixed_files["uploader"]
        output_dir = output_directory_mixed_files["output_dir"]
        target_name = output_directory_mixed_files["target_name"]
        file_pattern = output_directory_mixed_files["file_pattern"]
        total_files = output_directory_mixed_files["parquet_count"] + output_directory_mixed_files["json_count"]
        expected_skipped = output_directory_mixed_files["json_count"]
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            file_path_ending=file_pattern
        )
        
        actual_uploaded = result["uploaded"]
        actual_skipped = total_files - actual_uploaded
        
        assert actual_skipped == expected_skipped, f"expected {expected_skipped}, got {actual_skipped}"


class TestRateLimiterControlsUploadTiming:
    """Rate limiter controls upload timing"""

    @pytest.mark.asyncio
    async def test_wait_when_tokens_exhausted(self, output_directory_20_files):
        """
        Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then the upload waits for tokens before proceeding
        """
        uploader = output_directory_20_files["uploader"]
        output_dir = output_directory_20_files["output_dir"]
        target_name = output_directory_20_files["target_name"]
        max_concurrency_value = output_directory_20_files["max_concurrency"]
        expected_wait_calls = 1
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )
        
        actual_wait_calls = uploader.rate_limiter.wait_for_token.call_count
        
        assert actual_wait_calls >= expected_wait_calls, f"expected {expected_wait_calls}, got {actual_wait_calls}"

    @pytest.mark.asyncio
    async def test_complete_upload_after_tokens_replenish(self, output_directory_20_files):
        """
        Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then 20 files are uploaded
        """
        uploader = output_directory_20_files["uploader"]
        output_dir = output_directory_20_files["output_dir"]
        target_name = output_directory_20_files["target_name"]
        max_concurrency_value = output_directory_20_files["max_concurrency"]
        expected_uploaded = output_directory_20_files["file_count"]
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )
        
        actual_uploaded = result["uploaded"]
        
        assert actual_uploaded == expected_uploaded, f"expected {expected_uploaded}, got {actual_uploaded}"


class TestFailedUploadsRetryUntilSuccessOrMaxRetries:
    """Failed uploads retry until success or max retries"""

    @pytest.mark.asyncio
    async def test_retry_and_succeed(self, api_fails_then_succeeds):
        """
        Given the HuggingFace API returns error on first attempt
        And the API succeeds on second attempt
        When upload_to_hugging_face_in_parallel is called
        Then the return value contains "uploaded": 3, "failed": 0, "retried": 1
        """
        uploader = api_fails_then_succeeds["uploader"]
        output_dir = api_fails_then_succeeds["output_dir"]
        target_name = api_fails_then_succeeds["target_name"]
        expected_uploaded = api_fails_then_succeeds["file_count"]
        expected_failed = 0
        expected_retried = 1
        expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )
        
        assert result == expected_result, f"expected {expected_result}, got {result}"

    @pytest.mark.asyncio
    async def test_fail_after_max_retries(self, api_always_fails):
        """
        Given the HuggingFace API returns error on all attempts
        And max_retries is 3
        When upload_to_hugging_face_in_parallel is called
        Then the return value contains "uploaded": 0, "failed": 3, "retried": 3
        """
        uploader = api_always_fails["uploader"]
        output_dir = api_always_fails["output_dir"]
        target_name = api_always_fails["target_name"]
        file_count = api_always_fails["file_count"]
        expected_uploaded = 0
        expected_failed = file_count
        expected_retried = file_count
        expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )
        
        assert result == expected_result, f"expected {expected_result}, got {result}"


class TestMaxConcurrencyLimitsParallelUploads:
    """Max concurrency limits parallel uploads"""

    @pytest.mark.asyncio
    async def test_enforce_concurrency_limit(self, output_directory_100_files):
        """
        Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then no more than 5 uploads run at once
        """
        uploader = output_directory_100_files["uploader"]
        output_dir = output_directory_100_files["output_dir"]
        target_name = output_directory_100_files["target_name"]
        max_concurrency_value = output_directory_100_files["max_concurrency"]
        expected_max_concurrent = max_concurrency_value
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )
        
        actual_max_concurrent = max_concurrency_value
        
        assert actual_max_concurrent == expected_max_concurrent, f"expected {expected_max_concurrent}, got {actual_max_concurrent}"

    @pytest.mark.asyncio
    async def test_complete_all_uploads(self, output_directory_100_files):
        """
        Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
        When upload_to_hugging_face_in_parallel is called
        Then 100 files are uploaded
        """
        uploader = output_directory_100_files["uploader"]
        output_dir = output_directory_100_files["output_dir"]
        target_name = output_directory_100_files["target_name"]
        max_concurrency_value = output_directory_100_files["max_concurrency"]
        expected_uploaded = output_directory_100_files["file_count"]
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )
        
        actual_uploaded = result["uploaded"]
        
        assert actual_uploaded == expected_uploaded, f"expected {expected_uploaded}, got {actual_uploaded}"


class TestUploadModeDeterminesGranularity:
    """Upload mode determines granularity"""

    @pytest.mark.asyncio
    async def test_upload_files_individually(self, output_directory_with_folders):
        """
        Given upload_piecemeal is True
        When upload_to_hugging_face_in_parallel is called
        Then 8 files are uploaded individually
        """
        uploader = output_directory_with_folders["uploader"]
        output_dir = output_directory_with_folders["output_dir"]
        target_name = output_directory_with_folders["target_name"]
        upload_piecemeal_value = True
        expected_uploaded = output_directory_with_folders["total_files"]

        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            upload_piecemeal=upload_piecemeal_value
        )
        
        actual_uploaded = result["uploaded"]
        
        assert actual_uploaded == expected_uploaded, f"expected {expected_uploaded}, got {actual_uploaded}"

    @pytest.mark.asyncio
    async def test_upload_folders(self, output_directory_with_folders):
        """
        Given upload_piecemeal is False
        When upload_to_hugging_face_in_parallel is called
        Then 2 folders are uploaded
        """
        uploader = output_directory_with_folders["uploader"]
        output_dir = output_directory_with_folders["output_dir"]
        target_name = output_directory_with_folders["target_name"]
        upload_piecemeal_value = False
        expected_uploaded = output_directory_with_folders["folder_count"]

        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            upload_piecemeal=upload_piecemeal_value
        )
        
        actual_uploaded = result["uploaded"]
        
        assert actual_uploaded == expected_uploaded, f"expected {expected_uploaded}, got {actual_uploaded}"


class TestReturnValueProvidesUploadStatistics:
    """Return value provides upload statistics"""

    @pytest.mark.asyncio
    async def test_return_statistics_for_mixed_results(self, output_directory_mixed_results):
        """
        Given an output directory at "/data/output" contains 15 files and target directory name "laws"
        And 12 files upload on first attempt
        And 2 files upload on second attempt
        And 1 file fails after retries
        When upload_to_hugging_face_in_parallel is called
        Then the return value contains "uploaded": 14, "failed": 1, "retried": 2
        """
        uploader = output_directory_mixed_results["uploader"]
        output_dir = output_directory_mixed_results["output_dir"]
        target_name = output_directory_mixed_results["target_name"]
        expected_uploaded = 14
        expected_failed = 1
        expected_retried = 2
        expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )
        
        assert result == expected_result, f"expected {expected_result}, got {result}"