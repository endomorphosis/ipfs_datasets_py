# """Test upload files to HuggingFace in parallel."""
# import pytest



# class TestFilesUploadSuccessfullyWhenAPIIsAvailable:
#     """Files upload successfully when API is available"""

#     @pytest.mark.asyncio
#     async def test_upload_all_files(self, output_directory_10_parquet_files):
#         """
#         Given an output directory at "/data/output" contains 10 parquet files and target directory name is "municipal_laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then the return value contains "uploaded": 2, "failed": 0, "retried": 0 (2 folders containing 10 files total)
#         """
#         uploader = output_directory_10_parquet_files["uploader"]
#         output_dir = output_directory_10_parquet_files["output_dir"]
#         target_name = output_directory_10_parquet_files["target_name"]
        
#         expected_uploaded = 2  # 2 folders
#         expected_failed = 0
#         expected_retried = 0
#         expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name
#         )
        
#         assert result == expected_result, f"expected {expected_result}, got {result}"


# class TestFilePatternFiltersDetermineWhichFilesUpload:
#     """File pattern filters determine which files upload"""

#     @pytest.mark.asyncio
#     async def test_upload_only_matching_files(self, output_directory_mixed_files):
#         """
#         Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then 1 folder is uploaded (containing the matching parquet files)
#         """
#         uploader = output_directory_mixed_files["uploader"]
#         output_dir = output_directory_mixed_files["output_dir"]
#         target_name = output_directory_mixed_files["target_name"]
#         file_pattern = output_directory_mixed_files["file_pattern"]
#         expected_count = 1  # 1 folder containing parquet files

#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             file_path_ending=file_pattern
#         )

#         assert result["uploaded"] == expected_count, f"expected {expected_count}, got {result["uploaded"]}"

#     @pytest.mark.asyncio
#     async def test_skip_non_matching_files(self, output_directory_mixed_files):
#         """
#         Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then 1 folder is uploaded
#         """
#         uploader = output_directory_mixed_files["uploader"]
#         output_dir = output_directory_mixed_files["output_dir"]
#         target_name = output_directory_mixed_files["target_name"]
#         file_pattern = output_directory_mixed_files["file_pattern"]
#         expected_uploaded = 1  # Still 1 folder uploaded
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             file_path_ending=file_pattern
#         )

#         assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result["uploaded"]}"


# class TestRateLimiterControlsUploadTiming:
#     """Rate limiter controls upload timing"""

#     @pytest.mark.asyncio
#     async def test_wait_when_tokens_exhausted(self, output_directory_20_files):
#         """
#         Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then the upload waits for tokens before proceeding
#         """
#         uploader = output_directory_20_files["uploader"]
#         output_dir = output_directory_20_files["output_dir"]
#         target_name = output_directory_20_files["target_name"]
#         max_concurrency_value = output_directory_20_files["max_concurrency"]
#         expected_wait_calls = 1
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             max_concurrency=max_concurrency_value
#         )
        
#         actual_wait_calls = uploader.rate_limiter.wait_for_token.call_count
        
#         assert actual_wait_calls >= expected_wait_calls, f"expected {expected_wait_calls}, got {actual_wait_calls}"


#     @pytest.mark.asyncio
#     async def test_complete_upload_after_tokens_replenish(self, output_directory_20_files):
#         """
#         Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then 4 folders are uploaded (20 files in 4 folders)
#         """
#         uploader = output_directory_20_files["uploader"]
#         output_dir = output_directory_20_files["output_dir"]
#         target_name = output_directory_20_files["target_name"]
#         max_concurrency_value = output_directory_20_files["max_concurrency"]
#         folder_count = output_directory_20_files["folder_count"]
#         expected_uploaded = folder_count  # 4 folders containing 20 files total
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             max_concurrency=max_concurrency_value
#         )

#         assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result["uploaded"]}"


# class TestFailedUploadsRetryUntilSuccessOrMaxRetries:
#     """Failed uploads retry until success or max retries"""

#     @pytest.mark.asyncio
#     async def test_retry_and_succeed(self, api_fails_then_succeeds):
#         """
#         Given the HuggingFace API returns error on first attempt
#         And the API succeeds on second attempt
#         When upload_to_hugging_face_in_parallel is called
#         Then the return value contains "uploaded": 1, "failed": 0, "retried": 1 (1 folder)
#         """
#         uploader = api_fails_then_succeeds["uploader"]
#         output_dir = api_fails_then_succeeds["output_dir"]
#         target_name = api_fails_then_succeeds["target_name"]
#         expected_uploaded = 1  # 1 folder containing 3 files
#         expected_failed = 0
#         expected_retried = 1
#         expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name
#         )
        
#         assert result == expected_result, f"expected {expected_result}, got {result}"

#     @pytest.mark.asyncio
#     async def test_fail_after_max_retries(self, api_always_fails):
#         """
#         Given the HuggingFace API returns error on all attempts
#         And max_retries is 3
#         When upload_to_hugging_face_in_parallel is called
#         Then the return value contains "uploaded": 0, "failed": 1, "retried": 3 (1 folder)
#         """
#         uploader = api_always_fails["uploader"]
#         output_dir = api_always_fails["output_dir"]
#         target_name = api_always_fails["target_name"]
#         expected_uploaded = 0
#         expected_failed = 1  # 1 folder failed
#         expected_retried = 3
#         expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name
#         )
        
#         assert result == expected_result, f"expected {expected_result}, got {result}"


# class TestMaxConcurrencyLimitsParallelUploads:
#     """Max concurrency limits parallel uploads"""

#     @pytest.mark.asyncio
#     async def test_enforce_concurrency_limit(self, output_directory_100_files):
#         """
#         Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then no more than 5 uploads run at once
#         """
#         raise NotImplementedError
#         # uploader = output_directory_100_files["uploader"]
#         # output_dir = output_directory_100_files["output_dir"]
#         # target_name = output_directory_100_files["target_name"]
#         # max_concurrency_value = output_directory_100_files["max_concurrency"]
#         # expected_max_concurrent = max_concurrency_value
        
#         # result = await uploader.upload_to_hugging_face_in_parallel(
#         #     output_dir=output_dir,
#         #     target_dir_name=target_name,
#         #     max_concurrency=max_concurrency_value
#         # )
        
#         # actual_max_concurrent = max_concurrency_value
        
#         # assert actual_max_concurrent == expected_max_concurrent, f"expected {expected_max_concurrent}, got {actual_max_concurrent}"

#     @pytest.mark.asyncio
#     async def test_complete_all_uploads(self, output_directory_100_files):
#         """
#         Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
#         When upload_to_hugging_face_in_parallel is called
#         Then 20 folders are uploaded (100 files in 20 folders)
#         """
#         uploader = output_directory_100_files["uploader"]
#         output_dir = output_directory_100_files["output_dir"]
#         target_name = output_directory_100_files["target_name"]
#         max_concurrency_value = output_directory_100_files["max_concurrency"]
#         folder_count = output_directory_100_files["folder_count"]
#         expected_uploaded = folder_count  # 20 folders containing 100 files total
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             max_concurrency=max_concurrency_value
#         )

#         assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result["uploaded"]}"


# class TestUploadModeDeterminesGranularity:
#     """Upload mode determines granularity"""

#     @pytest.mark.asyncio
#     async def test_upload_files_individually(self, output_directory_with_folders):
#         """
#         Given upload_piecemeal is True
#         When upload_to_hugging_face_in_parallel is called
#         Then 8 files are uploaded individually
#         """
#         uploader = output_directory_with_folders["uploader"]
#         output_dir = output_directory_with_folders["output_dir"]
#         target_name = output_directory_with_folders["target_name"]
#         upload_piecemeal_value = True
#         expected_uploaded = output_directory_with_folders["total_files"]

#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             upload_piecemeal=upload_piecemeal_value
#         )

#         assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result["uploaded"]}"

#     @pytest.mark.asyncio
#     async def test_upload_folders(self, output_directory_with_folders):
#         """
#         Given upload_piecemeal is False
#         When upload_to_hugging_face_in_parallel is called
#         Then 2 folders are uploaded
#         """
#         uploader = output_directory_with_folders["uploader"]
#         output_dir = output_directory_with_folders["output_dir"]
#         target_name = output_directory_with_folders["target_name"]
#         upload_piecemeal_value = False
#         expected_uploaded = output_directory_with_folders["folder_count"]

#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name,
#             upload_piecemeal=upload_piecemeal_value
#         )

#         assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result["uploaded"]}"


# class TestReturnValueProvidesUploadStatistics:
#     """Return value provides upload statistics"""

#     @pytest.mark.asyncio
#     async def test_return_statistics_for_mixed_results(self, output_directory_mixed_results):
#         """
#         Given an output directory at "/data/output" contains 15 files and target directory name "laws"
#         And 12 files upload on first attempt
#         And 2 files upload on second attempt
#         And 1 file fails after retries
#         When upload_to_hugging_face_in_parallel is called
#         Then the return value contains "uploaded": 14, "failed": 1, "retried": 2
#         """
#         uploader = output_directory_mixed_results["uploader"]
#         output_dir = output_directory_mixed_results["output_dir"]
#         target_name = output_directory_mixed_results["target_name"]
#         expected_uploaded = output_directory_mixed_results["expected_uploaded"]
#         expected_failed = output_directory_mixed_results["expected_failed"]
#         expected_retried = output_directory_mixed_results["expected_retried"]

#         expected_result = {"uploaded": expected_uploaded, "failed": expected_failed, "retried": expected_retried}
        
#         result = await uploader.upload_to_hugging_face_in_parallel(
#             output_dir=output_dir,
#             target_dir_name=target_name
#         )
        
#         assert result == expected_result, f"expected {expected_result}, got {result}"

"""Test upload files to HuggingFace in parallel."""
import pytest


class TestFilesUploadSuccessfullyWhenAPIIsAvailable:
    """Files upload successfully when API is available"""

    @pytest.mark.asyncio
    async def test_when_uploading_files_then_returns_correct_upload_count(self, output_directory_10_parquet_files):
        """
        GIVEN an output directory with 2 folders containing 10 parquet files total
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect return value to contain uploaded count of 2
        """
        # Arrange
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        expected_uploaded = 2

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected uploaded={expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_uploading_files_then_returns_zero_failed_count(self, output_directory_10_parquet_files):
        """
        GIVEN an output directory with 2 folders and API succeeds for all uploads
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect return value to contain failed count of 0
        """
        # Arrange
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        expected_failed = 0

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["failed"] == expected_failed, f"expected failed={expected_failed}, got {result['failed']}"

    @pytest.mark.asyncio
    async def test_when_uploading_files_then_returns_zero_retry_count(self, output_directory_10_parquet_files):
        """
        GIVEN an output directory with 2 folders and API succeeds on first attempt
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect return value to contain retried count of 0
        """
        # Arrange
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        expected_retried = 0

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["retried"] == expected_retried, f"expected retried={expected_retried}, got {result['retried']}"

    @pytest.mark.asyncio
    async def test_when_uploading_files_then_calls_upload_folder_correct_number_of_times(self, output_directory_10_parquet_files):
        """
        GIVEN an output directory with 2 folders containing parquet files
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder to be called exactly 2 times
        """
        # Arrange
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        expected_call_count = 2

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        actual_call_count = uploader.api.upload_folder.call_count
        assert actual_call_count == expected_call_count, f"expected {expected_call_count} calls, got {actual_call_count}"

    @pytest.mark.asyncio
    async def test_when_uploading_files_then_calls_upload_folder_with_correct_repo_id(self, output_directory_10_parquet_files):
        """
        GIVEN an output directory with 2 folders and repo_id "test-repo"
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect all upload_folder calls to use repo_id "test-repo"
        """
        # Arrange
        uploader = output_directory_10_parquet_files["uploader"]
        output_dir = output_directory_10_parquet_files["output_dir"]
        target_name = output_directory_10_parquet_files["target_name"]
        expected_repo_id = "test-repo"

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        for call_args in uploader.api.upload_folder.call_args_list:
            actual_repo_id = call_args.kwargs.get("repo_id")
            assert actual_repo_id == expected_repo_id, f"expected repo_id={expected_repo_id}, got {actual_repo_id}"


class TestFilePatternFiltersDetermineWhichFilesUpload:
    """File pattern filters determine which files upload"""

    @pytest.mark.asyncio
    async def test_when_filtering_by_parquet_then_uploads_only_parquet_folders(self, output_directory_mixed_files):
        """
        GIVEN an output directory with 1 folder containing 5 parquet and 3 json files
        WHEN upload_to_hugging_face_in_parallel is called with file_path_ending ".parquet"
        THEN expect uploaded count to be 1
        """
        # Arrange
        uploader = output_directory_mixed_files["uploader"]
        output_dir = output_directory_mixed_files["output_dir"]
        target_name = output_directory_mixed_files["target_name"]
        file_pattern = output_directory_mixed_files["file_pattern"]
        expected_count = 1

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            file_path_ending=file_pattern
        )

        # Assert
        assert result["uploaded"] == expected_count, f"expected {expected_count}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_filtering_by_parquet_then_calls_upload_folder_with_parquet_pattern(self, output_directory_mixed_files):
        """
        GIVEN an output directory with mixed file types and filter ".parquet"
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder delete_patterns argument to contain "*.parquet"
        """
        # Arrange
        uploader = output_directory_mixed_files["uploader"]
        output_dir = output_directory_mixed_files["output_dir"]
        target_name = output_directory_mixed_files["target_name"]
        file_pattern = output_directory_mixed_files["file_pattern"]

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            file_path_ending=file_pattern
        )

        # Assert
        for call_args in uploader.api.upload_folder.call_args_list:
            delete_patterns = call_args.kwargs.get("delete_patterns", "")
            assert "*.parquet" in delete_patterns, f"expected '*.parquet' in delete_patterns, got {delete_patterns}"


class TestRateLimiterControlsUploadTiming:
    """Rate limiter controls upload timing"""

    @pytest.mark.asyncio
    async def test_when_uploading_folders_then_waits_for_token_before_each_upload(self, output_directory_20_files):
        """
        GIVEN an output directory with 4 folders
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect wait_for_token to be called at least 4 times
        """
        # Arrange
        uploader = output_directory_20_files["uploader"]
        output_dir = output_directory_20_files["output_dir"]
        target_name = output_directory_20_files["target_name"]
        max_concurrency_value = output_directory_20_files["max_concurrency"]
        folder_count = output_directory_20_files["folder_count"]
        expected_min_calls = folder_count

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )

        # Assert
        actual_calls = uploader.rate_limiter.wait_for_token.call_count
        assert actual_calls >= expected_min_calls, f"expected at least {expected_min_calls} wait calls, got {actual_calls}"

    @pytest.mark.asyncio
    async def test_when_uploading_folders_then_completes_all_uploads(self, output_directory_20_files):
        """
        GIVEN an output directory with 4 folders and rate limiting enabled
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 4
        """
        # Arrange
        uploader = output_directory_20_files["uploader"]
        output_dir = output_directory_20_files["output_dir"]
        target_name = output_directory_20_files["target_name"]
        max_concurrency_value = output_directory_20_files["max_concurrency"]
        folder_count = output_directory_20_files["folder_count"]
        expected_uploaded = folder_count

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"


class TestFailedUploadsRetryUntilSuccessOrMaxRetries:
    """Failed uploads retry until success or max retries"""

    @pytest.mark.asyncio
    async def test_when_api_fails_once_then_returns_uploaded_count_of_one(self, api_fails_then_succeeds):
        """
        GIVEN API that fails on first attempt then succeeds
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 1
        """
        # Arrange
        uploader = api_fails_then_succeeds["uploader"]
        output_dir = api_fails_then_succeeds["output_dir"]
        target_name = api_fails_then_succeeds["target_name"]
        expected_uploaded = 1

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_api_fails_once_then_returns_failed_count_of_zero(self, api_fails_then_succeeds):
        """
        GIVEN API that fails on first attempt then succeeds
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect failed count to be 0
        """
        # Arrange
        uploader = api_fails_then_succeeds["uploader"]
        output_dir = api_fails_then_succeeds["output_dir"]
        target_name = api_fails_then_succeeds["target_name"]
        expected_failed = 0

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["failed"] == expected_failed, f"expected {expected_failed}, got {result['failed']}"

    @pytest.mark.asyncio
    async def test_when_api_fails_once_then_returns_retry_count_of_one(self, api_fails_then_succeeds):
        """
        GIVEN API that fails on first attempt then succeeds
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect retried count to be 1
        """
        # Arrange
        uploader = api_fails_then_succeeds["uploader"]
        output_dir = api_fails_then_succeeds["output_dir"]
        target_name = api_fails_then_succeeds["target_name"]
        expected_retried = 1

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["retried"] == expected_retried, f"expected {expected_retried}, got {result['retried']}"

    @pytest.mark.asyncio
    async def test_when_api_fails_once_then_calls_upload_folder_twice(self, api_fails_then_succeeds):
        """
        GIVEN API that fails on first attempt then succeeds
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder to be called exactly 2 times
        """
        # Arrange
        uploader = api_fails_then_succeeds["uploader"]
        output_dir = api_fails_then_succeeds["output_dir"]
        target_name = api_fails_then_succeeds["target_name"]
        expected_call_count = 2

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        actual_call_count = uploader.api.upload_folder.call_count
        assert actual_call_count == expected_call_count, f"expected {expected_call_count} calls, got {actual_call_count}"

    @pytest.mark.asyncio
    async def test_when_api_always_fails_then_returns_uploaded_count_of_zero(self, api_always_fails):
        """
        GIVEN API that always fails and max_retries is 3
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 0
        """
        # Arrange
        uploader = api_always_fails["uploader"]
        output_dir = api_always_fails["output_dir"]
        target_name = api_always_fails["target_name"]
        expected_uploaded = 0

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_api_always_fails_then_returns_failed_count_of_one(self, api_always_fails):
        """
        GIVEN API that always fails and max_retries is 3
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect failed count to be 1
        """
        # Arrange
        uploader = api_always_fails["uploader"]
        output_dir = api_always_fails["output_dir"]
        target_name = api_always_fails["target_name"]
        expected_failed = 1

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["failed"] == expected_failed, f"expected {expected_failed}, got {result['failed']}"

    @pytest.mark.asyncio
    async def test_when_api_always_fails_then_returns_retry_count_of_three(self, api_always_fails):
        """
        GIVEN API that always fails and max_retries is 3
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect retried count to be 3
        """
        # Arrange
        uploader = api_always_fails["uploader"]
        output_dir = api_always_fails["output_dir"]
        target_name = api_always_fails["target_name"]
        max_retries = api_always_fails["max_retries"]
        expected_retried = max_retries

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["retried"] == expected_retried, f"expected {expected_retried}, got {result['retried']}"

    @pytest.mark.asyncio
    async def test_when_api_always_fails_then_calls_upload_folder_three_times(self, api_always_fails):
        """
        GIVEN API that always fails and max_retries is 3
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder to be called exactly 3 times
        """
        # Arrange
        uploader = api_always_fails["uploader"]
        output_dir = api_always_fails["output_dir"]
        target_name = api_always_fails["target_name"]
        max_retries = api_always_fails["max_retries"]
        expected_call_count = max_retries

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        actual_call_count = uploader.api.upload_folder.call_count
        assert actual_call_count == expected_call_count, f"expected {expected_call_count} calls, got {actual_call_count}"


class TestMaxConcurrencyLimitsParallelUploads:
    """Max concurrency limits parallel uploads"""

    @pytest.mark.asyncio
    async def test_when_max_concurrency_set_then_completes_all_uploads(self, output_directory_100_files):
        """
        GIVEN an output directory with 20 folders and max_concurrency of 5
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 20
        """
        # Arrange
        uploader = output_directory_100_files["uploader"]
        output_dir = output_directory_100_files["output_dir"]
        target_name = output_directory_100_files["target_name"]
        max_concurrency_value = output_directory_100_files["max_concurrency"]
        folder_count = output_directory_100_files["folder_count"]
        expected_uploaded = folder_count

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_max_concurrency_set_then_calls_upload_folder_correct_times(self, output_directory_100_files):
        """
        GIVEN an output directory with 20 folders and max_concurrency of 5
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder to be called exactly 20 times
        """
        # Arrange
        uploader = output_directory_100_files["uploader"]
        output_dir = output_directory_100_files["output_dir"]
        target_name = output_directory_100_files["target_name"]
        max_concurrency_value = output_directory_100_files["max_concurrency"]
        folder_count = output_directory_100_files["folder_count"]
        expected_call_count = folder_count

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            max_concurrency=max_concurrency_value
        )

        # Assert
        actual_call_count = uploader.api.upload_folder.call_count
        assert actual_call_count == expected_call_count, f"expected {expected_call_count} calls, got {actual_call_count}"


class TestUploadModeDeterminesGranularity:
    """Upload mode determines granularity"""

    @pytest.mark.asyncio
    async def test_when_upload_piecemeal_true_then_returns_file_count(self, output_directory_with_folders):
        """
        GIVEN upload_piecemeal is True and directory has 8 files
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 8
        """
        # Arrange
        uploader = output_directory_with_folders["uploader"]
        output_dir = output_directory_with_folders["output_dir"]
        target_name = output_directory_with_folders["target_name"]
        upload_piecemeal_value = True
        expected_uploaded = output_directory_with_folders["total_files"]

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            upload_piecemeal=upload_piecemeal_value
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_upload_piecemeal_false_then_returns_folder_count(self, output_directory_with_folders):
        """
        GIVEN upload_piecemeal is False and directory has 2 folders
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 2
        """
        # Arrange
        uploader = output_directory_with_folders["uploader"]
        output_dir = output_directory_with_folders["output_dir"]
        target_name = output_directory_with_folders["target_name"]
        upload_piecemeal_value = False
        expected_uploaded = output_directory_with_folders["folder_count"]

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            upload_piecemeal=upload_piecemeal_value
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_upload_piecemeal_false_then_calls_upload_folder(self, output_directory_with_folders):
        """
        GIVEN upload_piecemeal is False and directory has 2 folders
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect upload_folder to be called exactly 2 times
        """
        # Arrange
        uploader = output_directory_with_folders["uploader"]
        output_dir = output_directory_with_folders["output_dir"]
        target_name = output_directory_with_folders["target_name"]
        upload_piecemeal_value = False
        folder_count = output_directory_with_folders["folder_count"]
        expected_call_count = folder_count

        # Act
        await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name,
            upload_piecemeal=upload_piecemeal_value
        )

        # Assert
        actual_call_count = uploader.api.upload_folder.call_count
        assert actual_call_count == expected_call_count, f"expected {expected_call_count} calls, got {actual_call_count}"


class TestReturnValueProvidesUploadStatistics:
    """Return value provides upload statistics"""

    @pytest.mark.asyncio
    async def test_when_mixed_results_then_returns_correct_uploaded_count(self, output_directory_mixed_results):
        """
        GIVEN 4 folders where 3 succeed and 1 fails
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect uploaded count to be 3
        """
        # Arrange
        uploader = output_directory_mixed_results["uploader"]
        output_dir = output_directory_mixed_results["output_dir"]
        target_name = output_directory_mixed_results["target_name"]
        expected_uploaded = output_directory_mixed_results["expected_uploaded"]

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["uploaded"] == expected_uploaded, f"expected {expected_uploaded}, got {result['uploaded']}"

    @pytest.mark.asyncio
    async def test_when_mixed_results_then_returns_correct_failed_count(self, output_directory_mixed_results):
        """
        GIVEN 4 folders where 3 succeed and 1 fails
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect failed count to be 1
        """
        # Arrange
        uploader = output_directory_mixed_results["uploader"]
        output_dir = output_directory_mixed_results["output_dir"]
        target_name = output_directory_mixed_results["target_name"]
        expected_failed = output_directory_mixed_results["expected_failed"]

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["failed"] == expected_failed, f"expected {expected_failed}, got {result['failed']}"

    @pytest.mark.asyncio
    async def test_when_mixed_results_then_returns_correct_retry_count(self, output_directory_mixed_results):
        """
        GIVEN 4 folders where 1 retries once and 1 retries twice before failing
        WHEN upload_to_hugging_face_in_parallel is called
        THEN expect retried count to be 2
        """
        # Arrange
        uploader = output_directory_mixed_results["uploader"]
        output_dir = output_directory_mixed_results["output_dir"]
        target_name = output_directory_mixed_results["target_name"]
        expected_retried = output_directory_mixed_results["expected_retried"]

        # Act
        result = await uploader.upload_to_hugging_face_in_parallel(
            output_dir=output_dir,
            target_dir_name=target_name
        )

        # Assert
        assert result["retried"] == expected_retried, f"expected {expected_retried}, got {result['retried']}"