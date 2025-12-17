import concurrent.futures as cf
import logging
from pathlib import Path
import re
import time
import threading
from typing import Any, Optional


from huggingface_hub import login, HfApi, CommitInfo
from huggingface_hub.errors import HfHubHTTPError
import tqdm


logger = logging.getLogger(__name__)
from ._utils.configs import Configs


class RateLimiter:
    """
    Token bucket rate limiter for API requests.
    
    This class implements a token bucket algorithm to limit the rate of API requests.
    It ensures that requests are made at a rate that doesn't exceed the specified limit.
    
    Attributes:
        request_limit_per_hour (int): Maximum number of requests allowed per hour
        tokens (float): Current number of tokens in the bucket
        token_rate (float): Rate at which tokens are added to the bucket (tokens per second)
        last_update_time (float): Timestamp of the last token update
        mutex (threading.Lock): Lock for thread-safe operations
    """
    
    def __init__(self, request_limit_per_hour: int = 300):
        """
        Initialize the rate limiter.
        
        Args:
            request_limit_per_hour (int): Maximum number of requests allowed per hour
        """
        self.request_limit_per_hour = request_limit_per_hour
        self.tokens = request_limit_per_hour  # Start with a full bucket
        self.token_rate = request_limit_per_hour / 3600.0  # Tokens per second
        self.last_update_time = time.time()
        self.mutex = threading.Lock()
    
    def _update_tokens(self):
        """Update the token count based on elapsed time."""
        current_time = time.time()
        time_diff = current_time - self.last_update_time
        new_tokens = time_diff * self.token_rate
        
        # Update token count but don't exceed the maximum
        with self.mutex:
            self.tokens = min(self.request_limit_per_hour, self.tokens + new_tokens)
            self.last_update_time = current_time
    
    def wait_for_token(self, tokens: int = 1) -> float:
        """
        Wait until the specified number of tokens are available and then consume them.
        
        Args:
            tokens (int): Number of tokens to consume
            
        Returns:
            float: Time waited in seconds
        """
        start_wait = time.time()
        
        while True:
            self._update_tokens()
            
            with self.mutex:
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return time.time() - start_wait
            
            # If not enough tokens, sleep for a short time before checking again
            # Calculate sleep time based on how many tokens we need and the token rate
            needed_tokens = tokens - self.tokens
            if needed_tokens > 0:
                sleep_time = needed_tokens / self.token_rate
                # Sleep for a smaller interval to be more responsive
                time.sleep(min(sleep_time, 1.0))
            else:
                time.sleep(0.1)  # Minimal sleep to prevent CPU spinning
    
    def get_current_rate(self) -> float:
        """
        Get the current rate of tokens per hour.
        
        Returns:
            float: Current rate of tokens in tokens per hour
        """
        with self.mutex:
            return self.tokens * (3600.0 / self.token_rate)
    
    def reset(self):
        """Reset the rate limiter to its initial state."""
        with self.mutex:
            self.tokens = self.request_limit_per_hour
            self.last_update_time = time.time()


class UploadToHuggingFaceInParallel:
    """
    Upload files to HuggingFace in parallel with rate limiting.
    
    This class handles uploading files to HuggingFace repositories while respecting
    the API rate limits. It uses a token bucket rate limiter to ensure that the
    number of requests doesn't exceed the specified limit.
    
    Attributes:
        configs (Configs): Configuration object
        resources (Optional[dict]): Additional resources if needed
        repo_id (str): HuggingFace repository ID
        sql_input (Path): Input path for SQL data
        rate_limiter (RateLimiter): Rate limiter for API requests
        upload_count (int): Count of successful uploads
        failed_count (int): Count of failed uploads
        retry_count (int): Count of retried uploads
        repo_type (str): Repository type (dataset, model, space)
        api (HfApi): HuggingFace API client

    Example:
        # Example usage
        if __name__ == "__main__":
            # This is just an example of how to use the class
            class ExampleConfig:
                def __init__(self):
                    self.REPO_ID = "your-repo-id"
                    self.HUGGING_FACE_USER_ACCESS_TOKEN = "your-token"
                    self.paths = type('Paths', (), {'INPUT_FROM_SQL': Path('./data')})()
            
            # Initialize uploader
            uploader = UploadToHuggingFaceInParallel(configs=ExampleConfig())
            
            # Use the uploader
            import asyncio
            
            async def main():
                result = await uploader.upload_to_hugging_face_in_parallel(
                    output_dir=Path("./output"),
                    target_dir_name="target_dir",
                    max_concurrency=3  # Customize based on your needs
                )
                print(f"Upload results: {result}")
            
            # Run the async function
            asyncio.run(main())
    """

    _HUGGING_FACE_API_LIMIT_PER_HOUR = 300
    _REPO_TYPE = "dataset"
    
    def __init__(self, *, resources: dict[str, Any], configs: Configs) -> None:
        """
        Initialize the uploader.
        
        Args:
            resources (Optional[dict]): Additional resources if needed
            configs (Configs): Configuration object
        """
        self.configs = configs
        self.resources = resources

        self.logger = resources["logger"]
        
        self.repo_id: str = configs.REPO_ID
        self.sql_input: Path = configs.paths.INPUT_FROM_SQL
        self.target_dir_name: str = configs.TARGET_DIR_NAME

        # Create rate limiter with HuggingFace API limits
        self.requests_per_hour: int = self._HUGGING_FACE_API_LIMIT_PER_HOUR
        self.rate_limiter = RateLimiter(request_limit_per_hour=self.requests_per_hour)
        
        # Initialize counters
        self.upload_count: int = 0
        self.failed_count: int = 0
        self.retry_count: int = 0
        
        # Set repository type and initialize API
        self.repo_type: str = self._REPO_TYPE
        
        # Initialize API
        self._setup_hugging_face_api()
        self.api = HfApi()


    def _setup_hugging_face_api(self) -> None:
        """Set up the HuggingFace API by logging in with the access token."""
        login(self.configs.HUGGING_FACE_USER_ACCESS_TOKEN)


    def _get_target_dir_name_with_backslash(self, at_the_end: Optional[bool] = None, at_the_beginning: Optional[bool] = None) -> str:
        """
        Get target directory name with optional backslashes at beginning or end.
        
        Args:
            at_the_end (bool, optional): Add backslash at the end if True
            at_the_beginning (bool, optional): Add backslash at the beginning if True
            
        Returns:
            str: Formatted target directory name
        """
        if at_the_end is None and at_the_beginning is None:
            return self.target_dir_name
        else:
            target_dir_name_copy = self.target_dir_name
            if at_the_end:
                # Add a backslash at the end of the target directory name
                target_dir_name_copy = target_dir_name_copy if target_dir_name_copy.endswith("/") else f"{target_dir_name_copy}/"
            if at_the_beginning:
                # Add a backslash at the beginning of the target directory name
                target_dir_name_copy = target_dir_name_copy if target_dir_name_copy.startswith("/") else f"/{target_dir_name_copy}"
        return target_dir_name_copy

    def _get_already_processed_files(self) -> set[str]:
        """
        Get the set of files that have already been uploaded to the repository.
        
        Returns:
            set[str]: Set of file names already in the repository
        """
        if not self.api:
            logger.error("API not initialized, can't get processed files")
            return set()
            
        # Wait for a token before making an API request
        self.rate_limiter.wait_for_token()
        
        try:
            # list all files in the repository
            file_info = self.api.list_repo_files(
                repo_id=self.repo_id,
                repo_type=self.repo_type,
                revision="main"  # You can change this to another branch if needed
            )

            # Map the file_info to just the file names, excluding .json files
            parquet_files = [f for f in file_info if '.json' not in f]
            target_dir_name_with_backslash = self._get_target_dir_name_with_backslash(at_the_end=True)
            file_info_set = set(
                map(lambda x: re.sub(f"{target_dir_name_with_backslash}", "", x), parquet_files)
            )
            
            logger.info(f"Found {len(file_info_set)} files in the repository {self.repo_id}.")

            return file_info_set
        except Exception as e:
            logger.error(f"Error getting processed files: {e}")
            raise e

    def _get_folders_to_upload(self, data_dir: Path, file_info_set: set[str]) -> list[Path]:
        """
        Get the list of folders that need to be uploaded.
        
        Args:
            data_dir (Path): Directory containing the data
            file_info_set (set[str]): Set of file names already in the repository
            
        Returns:
            list[Path]: list of folders to upload
        """
        folders_to_upload: list[Path] = []
        
        for dir in data_dir.iterdir():
            if dir.is_dir():
                #logger.debug(f"Checking directory: {dir.stem}")
                
                # Check if all the files in this directory already exist in the repository
                all_files_exist = True
                for file in dir.glob("**/*.parquet"):
                    #logger.debug(f"Checking if file {file.stem} exists in repository.")
                    if file.name not in file_info_set:
                        #logger.debug(f"File {file.stem} not found in repository. Will upload this directory.")
                        all_files_exist = False
                        break
                
                # Skip uploading this directory if all files already exist
                if all_files_exist:
                    #logger.debug(f"Directory {dir.stem} already uploaded to repository.")
                    continue
                else:
                    # Otherwise, add the files for upload
                    folders_to_upload.append(dir)
                    
        return folders_to_upload


    def _upload_file(self, *,file_path: Path, path_in_repo: str) -> cf.Future:
        """Upload a single file to HuggingFace."""
        _path_in_repo = Path(path_in_repo) / file_path.name
        return self.api.upload_file( # type: ignore[call-arg]
            path_or_fileobj=file_path,
            path_in_repo=str(_path_in_repo.resolve()),
            repo_id=self.repo_id,
            repo_type=self.repo_type,
            run_as_future=True
        )


    def _upload_folder(self, *,
                        folder_path: Path, 
                        path_in_repo: str, 
                        delete_patterns: str,
                        ) -> cf.Future:
        """Upload a single folder to HuggingFace."""
        return self.api.upload_folder(
            folder_path=folder_path,
            path_in_repo=path_in_repo,
            repo_id=self.repo_id,
            repo_type=self.repo_type,
            delete_patterns=delete_patterns,
            run_as_future=True  # Use async upload if available
        )


    def upload_with_retry(self, 
                        dir: Path, 
                        path_in_repo: str, 
                        delete_patterns: str,
                        max_retries: int = 3,
                        retry_delay: float = 5.0,
                        ) -> cf.Future | None:
        """
        Upload a folder with retry logic and rate limiting.
        
        Args:
            dir (Path): Directory to upload
            path_in_repo (str): Path in the repository
            delete_patterns (str): Patterns for files to delete
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries in seconds
            
        Returns:
            Future: A future containing information about the commit if successful, None otherwise
            
        Example:
            >>> uploader = UploadToHuggingFaceInParallel(resources={...}, configs=config)
            >>> folder = Path("./data/municipal_laws/city_ordinances")
            >>> future = uploader.upload_with_retry(
            ...     dir=folder,
            ...     path_in_repo="/datasets/municipal_laws",
            ...     delete_patterns="**/city_ordinances/*.parquet",
            ...     max_retries=5,
            ...     retry_delay=10.0
            ... )
            >>> if future:
            ...     commit_info = future.result()
            ...     print(f"Upload successful: {commit_info.commit_url}")
        """
        for attempt in range(max_retries):
            try:
                # Wait for a token before making an API request
                wait_time = self.rate_limiter.wait_for_token()
                if wait_time > 0.1:
                    logger.info(f"Rate limited: waited {wait_time:.2f}s for token")

                # Call the upload function
                if dir.is_file():
                    future = self._upload_file(
                        file_path=dir,
                        path_in_repo=path_in_repo
                    )
                else:
                    future = self._upload_folder(
                        folder_path=dir,
                        path_in_repo=path_in_repo,
                        delete_patterns=delete_patterns
                    )

                self.upload_count += 1
                logger.info(f"Successfully uploaded folder {dir.stem} on attempt {attempt + 1}")
                return future
                
            except cf.CancelledError as e:
                logger.error(f"Future was cancelled: {e}")
                
            except cf.TimeoutError as e:
                logger.error(f"Future timed out: {e}")
                
            except HfHubHTTPError as e:
                # Handle rate limiting errors specially
                if e.response is not None and e.response.status_code == 429:
                    logger.warning(f"Rate limit exceeded, waiting longer before retry: {e}")
                    time.sleep(retry_delay * 2)  # Wait longer for rate limit errors
                else:
                    logger.error(f"HTTP error while uploading {dir.stem}: {e}")
                    time.sleep(retry_delay)
                    
            except Exception as e:
                logger.exception(f"Exception while uploading {dir.stem}: {e}")
                time.sleep(retry_delay)
            
            # If we got here, the upload failed but we'll retry
            self.retry_count += 1
            logger.info(f"Retrying upload for {dir.stem} (attempt {attempt + 2}/{max_retries}) after {retry_delay} seconds")

        # If we've exhausted all retries
        self.failed_count += 1
        logger.error(f"Failed to upload {dir.stem} after {max_retries} attempts")
        return None

    async def upload_to_hugging_face_in_parallel(
            self,
            output_dir: Path,
            target_dir_name: str,
            file_path_ending: str = ".*",
            max_concurrency: Optional[int] = None,
            upload_piecemeal: bool = False
            ) -> dict[str, int]:
        """
        Upload files to HuggingFace in parallel with rate limiting.
        
        Args:
            output_dir (Path): Directory containing the output files
            target_dir_name (str): Name of the target directory in the repository
            file_path_ending (str): File path ending pattern (default: ".*" for all files)
            max_concurrency (Optional[int]): Maximum number of concurrent uploads. If None, defaults to 
                (requests_per_hour / 60) - 1 for safe rate limiting
            upload_piecemeal (bool): If True, upload individual files instead of folders
            
        Returns:
            dict[str, int]: Dictionary with upload statistics containing the following keys:
                - "uploaded" (int): Number of successfully uploaded folders/files
                - "failed" (int): Number of folders/files that failed to upload after all retries
                - "retried" (int): Total number of retry attempts made during the upload process
                
        Example:
            >>> uploader = UploadToHuggingFaceInParallel(resources={...}, configs=config)
            >>> result = await uploader.upload_to_hugging_face_in_parallel(
            ...     output_dir=Path("./output"),
            ...     target_dir_name="municipal_laws",
            ...     file_path_ending=".parquet",
            ...     max_concurrency=5
            ... )
            >>> print(result)
            {'uploaded': 150, 'failed': 2, 'retried': 8}
        """
        if not self.api:
            logger.error("API not initialized, can't upload files")
            return {"uploaded": 0, "failed": 0, "retried": 0}
            
        # Initialize counters
        self.upload_count = 0
        self.failed_count = 0
        self.retry_count = 0
        
        # Set default max concurrency based on rate limits
        if max_concurrency is None:
            # Default to slightly less than the per-minute limit to be safe
            max_concurrency = max(1, int(self.requests_per_hour / 60) - 1)
            
        # Format file path ending
        if file_path_ending != ".*" and file_path_ending != "":
            file_path_ending = f"*{file_path_ending}"

        # Count files to upload
        num_files = len([file for file in output_dir.glob("**/*.parquet") if file.is_file()])
        data_dir = self.sql_input / target_dir_name 

        logger.info(f"Detected {num_files} files in {output_dir}.")

        # Get already processed files
        file_info_set = self._get_already_processed_files()
        
        # Get folders that need to be uploaded
        folders_to_upload = self._get_folders_to_upload(data_dir, file_info_set)
        logger.info(f"Got {len(folders_to_upload)} folders with un-uploaded files.")
        time.sleep(10)

        if upload_piecemeal:
            logger.info(folders_to_upload)
            _folders_to_upload = [
                file for file in folders_to_upload if file.is_file()
            ]
            folders_to_upload = _folders_to_upload
            desc = "Uploading files"
        else:
            desc = "Uploading folders"

        # Create progress bar
        with tqdm.tqdm(total=len(folders_to_upload), desc=desc) as pbar:
            # Use ThreadPoolExecutor for parallel uploads
            with cf.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
                # Submit all upload tasks
                futures = {
                    executor.submit(
                        self.upload_with_retry,
                        dir=dir,
                        path_in_repo=self._get_target_dir_name_with_backslash(at_the_beginning=True),
                        delete_patterns=f"**/{dir}/{file_path_ending}"
                    ): dir for dir in folders_to_upload
                }

                # Process completed futures
                for future in cf.as_completed(futures):
                    dir = futures[future]
                    try:
                        # Get the result (which may raise an exception)
                        result = future.result()
                        if result:
                            logger.debug(f"Successfully uploaded {dir.stem}")
                        else:
                            logger.warning(f"Failed to upload {dir.stem}")
                    except Exception as e:
                        logger.exception(f"Unhandled exception for {dir.stem}: {e}")
                        self.failed_count += 1
                    finally:
                        # Update progress bar
                        pbar.update(1)
        
        # Log final statistics
        logger.info(f"Uploaded {self.upload_count} folders to {self.repo_id}. w00t!")
        
        if self.retry_count > 0:
            logger.info(f"Required {self.retry_count} retries during the upload process.")
            
        if self.failed_count > 0:
            logger.error(f"Failed to upload {self.failed_count} folders to {self.repo_id}. Please check the logs for more details.")

        return {"uploaded": self.upload_count, "failed": self.failed_count, "retried": self.retry_count}
