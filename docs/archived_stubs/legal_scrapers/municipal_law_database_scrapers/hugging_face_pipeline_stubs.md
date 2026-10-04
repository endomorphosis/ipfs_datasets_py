# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/hugging_face_pipeline.py'

Files last updated: 1765920158.181445

Stub file last updated: 2025-12-16 13:26:14

## RateLimiter
```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UploadToHuggingFaceInParallel
```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__
```python
def __init__(self, request_limit_per_hour: int = 300):
    """
    Initialize the rate limiter.

Args:
    request_limit_per_hour (int): Maximum number of requests allowed per hour
    """
```
* **Async:** False
* **Method:** True
* **Class:** RateLimiter

## __init__
```python
def __init__(self, *, resources: dict[str, Any], configs: Configs) -> None:
    """
    Initialize the uploader.

Args:
    resources (Optional[dict]): Additional resources if needed
    configs (Configs): Configuration object
    """
```
* **Async:** False
* **Method:** True
* **Class:** UploadToHuggingFaceInParallel

## get_current_rate
```python
def get_current_rate(self) -> float:
    """
    Get the current rate of tokens per hour.

Returns:
    float: Current rate of tokens in tokens per hour
    """
```
* **Async:** False
* **Method:** True
* **Class:** RateLimiter

## reset
```python
def reset(self):
    """
    Reset the rate limiter to its initial state.
    """
```
* **Async:** False
* **Method:** True
* **Class:** RateLimiter

## upload_to_hugging_face_in_parallel
```python
async def upload_to_hugging_face_in_parallel(self, output_dir: Path, target_dir_name: str, file_path_ending: str = ".*", max_concurrency: Optional[int] = None, upload_piecemeal: bool = False) -> dict[str, int]:
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
```
* **Async:** True
* **Method:** True
* **Class:** UploadToHuggingFaceInParallel

## upload_with_retry
```python
def upload_with_retry(self, dir: Path, path_in_repo: str, delete_patterns: str, max_retries: int = 3, retry_delay: float = 5.0) -> cf.Future | None:
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
```
* **Async:** False
* **Method:** True
* **Class:** UploadToHuggingFaceInParallel

## wait_for_token
```python
def wait_for_token(self, tokens: int = 1) -> float:
    """
    Wait until the specified number of tokens are available and then consume them.

Args:
    tokens (int): Number of tokens to consume
    
Returns:
    float: Time waited in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** RateLimiter