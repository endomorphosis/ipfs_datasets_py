# !/usr/bin/env python3
from __future__ import annotations
import anyio
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated, AsyncGenerator, Optional, TextIO


from bs4 import BeautifulSoup
import openai
from openai.types import Batch, FileObject
import pandas as pd
from pydantic import AfterValidator as AV, BaseModel, computed_field, PrivateAttr, ValidationError, SecretStr
import tiktoken


from ipfs_datasets_py.ipfs_multiformats import get_cid
from .configs import configs


logger = logging.getLogger(__name__)

# setup a file and console handler for the logger
file_handler = logging.FileHandler('openai_embedding.log')
console_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
# Set logger level to DEBUG for more detailed output
logger.setLevel(logging.DEBUG)


def get_gnis_from_file_name(filename: str, ending: Optional[str] = None) -> str:
    """
    Extract the GNIS identifier from a filename.
    
    Args:
        filename (str): The filename to extract GNIS from
        
    Returns:
        str: The extracted GNIS identifier, or empty string if not found
    """
    if not filename:
        return ""

    if ending:
        if not filename.endswith(ending):
            logger.warning(f"Filename does not end with {ending}: {filename}")
            return ""

    try:
        # Extract GNIS from patterns like "123456.jsonl" or "123456_something.jsonl"
        return filename.split("_")[0]
    except (IndexError, AttributeError):
        logger.warning(f"Could not extract GNIS from filename: {filename}")
        return ""


class EmbeddingBody(BaseModel):
    model: str
    input: str


class JsonlLine(BaseModel):
    custom_id: str | None
    method: str = "POST"
    url: str = "/v1/embeddings"
    body: EmbeddingBody


def validate_description(description: str) -> str:
    msg = None
    if "embeddings for " not in description:
        msg = f"Description does not contain 'embeddings for ': '{description}'"

    if not re.search(r'\d', description):
        msg = "Description does not contain any numeric values."

    if msg is None:
        logger.error(msg)
        raise ValueError(msg)
    return description


def _validate_openai_embedding_data_dict(data: dict) -> dict:
    try:
        _ = data['custom_id']
        _ = data['response']['body']['data'][0]['embedding']
    except KeyError as e:
        logger.error(f"Invalid data format received from OpenAI embedding API: {e}")
        raise ValidationError("Invalid data format received from OpenAI embedding API.")

    if "_" not in data['custom_id']:
        logger.error("Custom ID does not contain an underscore.")
        raise ValidationError("Custom ID does not contain an underscore.")
    return data

def _validate_row(row: tuple) -> None:
    msg = None
    if len(row) != 3 or len(row) != 2:
        msg = f"Row does not have the expected number of elements: '{len(row)}' instead of 3 or 2"

    for item in row:
        # Check if the item is None
        if item is None:
            msg = "Row contains None values."
        # Check if the item is a string. If it is, check if there are numbers in it. Else raise a ValidationError
        if isinstance(item, str) and not re.search(r'\d', item):
            msg = "String item does not contain any numeric values."

    if msg:
        logger.error(msg)
        raise ValidationError(msg)


class ParquetRow(BaseModel):

    data: Annotated[dict, AV(_validate_openai_embedding_data_dict)]
    gnis: Optional[str] = None
    cid: Optional[str] = None
    embedding: Optional[list[float]] = None
    _row: Annotated[tuple, AV(_validate_row)] | None = PrivateAttr(default=None)

    def __init__(self, **data):
        super().__init__(**data)
        self._row = data['custom_id'].split('_') # -> {gnis}_{row.cid}_chunk-{i} or {gnis}_{row.cid}
        if self._row is None:
            raise ValueError(f"Row data could not be parsed from custom_id: {data['custom_id']} .")

        self.gnis = str(self._row[0])
        self.cid = str(self._row[1]) # Foreign key
        self.embedding = self.data['response']['body']['data'][0]['embedding']
        # Revalidate the model to ensure all fields are set correctly
        self.model_validate(self)

    @computed_field # type: ignore[misc]
    @property
    def embedding_cid(self) -> str:
        return get_cid(f"{json.dumps(self.embedding)}{self.cid}")  # Ensure the embedding is part of the CID to avoid collisions

    @computed_field # type: ignore[misc]
    @property
    def text_chunk_order(self) -> int:
        if self._row is None:
            raise ValueError("Row data has not been set.")
        return int(self._row[2].split('-')[1]) if len(self._row) == 3 else 1


class BatchMetadata(BaseModel):
    description: Annotated[str, AV(validate_description)]
    model: str


class OpenAIEmbedding:
    """
    Implementation of EmbeddingGenerator using OpenAI's embedding API.
    """
    def __init__(self, 
                 model: str = "text-embedding-3-small", 
                 api_key: Optional[str] = None
                ):
        """
        Initialize the OpenAI embedding generator.
        
        Args:
            model (str): The OpenAI embedding model to use.
            api_key (Optional[str]): OpenAI API key. If None, will use OPENAI_API_KEY environment variable.
        """
        self.model = model
        self.max_embedding_input_size = 8192
        self.max_embedding_array_dimension = 2048
        self.batch_jobs = []
        self.total_token_count = 0

        # Store the API key
        self._api_key = None
        
        # Set API key first, before initializing clients
        if api_key:
            self._api_key = api_key
            # Set for compatibility with older code that might use global api_key
            openai.api_key = api_key
        elif "OPENAI_API_KEY" in os.environ and os.environ["OPENAI_API_KEY"]:
            self._api_key = os.environ["OPENAI_API_KEY"]
            # Set for compatibility with older code that might use global api_key
            openai.api_key = self._api_key
        else:
            raise ValueError("OpenAI API key must be provided either as an argument or via OPENAI_API_KEY environment variable")
        
        # Log that we have an API key (without revealing it)
        logger.debug(f"API key set: {bool(self._api_key)}")    
        
        # Initialize the clients with the API key explicitly
        try:
            self.async_client = openai.AsyncOpenAI(api_key=self._api_key)
            logger.debug("OpenAI clients initialized successfully")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI clients: {e}") from e

        # Initialize tokenizer
        try:
            self.embedding_encoding = tiktoken.encoding_for_model('text-embedding-3-small')
            logger.debug("Tokenizer initialized successfully")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize tokenizer: {e}") from e

    @staticmethod
    def get_cid(file_data: str | Path | bytes, for_string: bool = False) -> str:
        return get_cid(file_data, for_string=for_string)

    @staticmethod
    def parquet_to_jsonl(html_parquet_path: Path, output_file: str) -> pd.DataFrame:
        """
        Convert a parquet file to a JSONL file.
        
        Args:
            html_parquet_path (Path): Path to the input parquet file.
            output_file (str): Path to the output JSONL file.
        """
        df = pd.read_parquet(html_parquet_path)
        df.to_json(output_file, orient="records", lines=True)
        return df

    def get_token_list(self, text: str) -> list[int]:
        """Convert text to a list of token IDs using the encoding model."""
        return self.embedding_encoding.encode(text, allowed_special="all")

    def get_token_count(self, text: str) -> int:
        """Calculate the number of tokens in the input text."""
        return len(self.get_token_list(text))
    
    def chunk_text_by_tokens(self, text: str) -> list[str]:
        """
        Chunk a piece of text into smaller pieces based on a maximum token count.
        
        Args:
            text: The text to chunk
            max_tokens: Maximum number of tokens per chunk
            
        Returns:
            List of text chunks, each containing at most max_tokens tokens
        """
        token_id_list = self.get_token_list(text)
        current_token_count = 0
        chunks = []
        current_chunk_ids = []

        for token_id in token_id_list:
            # If adding this token would exceed the limit
            if current_token_count + 1 > self.max_embedding_input_size:
                # Convert current chunk IDs back to text
                if current_chunk_ids:
                    chunk_text = self.embedding_encoding.decode(current_chunk_ids)
                    chunks.append(chunk_text)
                    current_chunk_ids = [token_id]  # Start new chunk with current token
                    current_token_count = 1
            else:
                current_chunk_ids.append(token_id)
                current_token_count += 1

        # Don't forget to add the last chunk
        if current_chunk_ids:
            chunk_text = self.embedding_encoding.decode(current_chunk_ids)
            chunks.append(chunk_text)

        logger.debug(f"Chunked text into {len(chunks)} chunks")
        logger.debug(f"chunks: {chunks}")
        return chunks

    @staticmethod
    def _prepare_html_for_embedding(html_title: str, html: str) -> str:
        """
        Prepare HTML content for embedding by extracting text and removing tags.
        
        Args:
            html_title (str): The title of the HTML content.
            html (str): The HTML content to process.
            
        Returns:
            str: The text content extracted from the HTML.
        """
        raw_text_list = []
        for _html in [html_title, html]:
            soup = BeautifulSoup(_html, "html.parser")
            # Find elements with either chunk-content or chunk-title class
            element = soup.find(class_="chunk-content")
            if not element:
                element = soup.find(class_="chunk-title")

            # If no specific elements found, use the whole soup
            if element:
                text = element.get_text(separator=" ")
            else:
                text = soup.get_text(separator=" ")

            raw_text_list.append(text)

        # Make sure the raw text in the raw_text_list is not empty
        if not raw_text_list:
            raw_text = ""
        else:
            raw_text = " ".join(raw_text_list)

        # Clean the text by removing extra spaces and newlines

        # Remove newlines
        text = raw_text.replace('\n', ' ')
        # Remove extra spaces
        text = re.sub(r'\s+', ' ', text)
        # Strip leading and trailing spaces
        text = text.strip()

        return text


    def _write_to_jsonl_line(self, file: TextIO, chunk: Optional[str] = None, custom_id: Optional[str] = None) -> None:
        """
        Writes a single JSON line to a file for OpenAI embedding request.

        This method formats a chunk of text as a JSON object compatible with OpenAI's
        embeddings API and writes it as a single line to the provided file.

        Args:
            file (TextIO): An open file object in text mode to write to.
            chunk (str, optional): The text content to be embedded. Defaults to None.
            custom_id (str, optional): A custom identifier for the embedding. Defaults to None.

        Returns:
            None: This method doesn't return anything, it writes directly to the file.

        Note:
            The format follows OpenAI's batch processing format for embeddings,
            with each line containing a complete request object.
        """
        embedding_body = EmbeddingBody(model=self.model, input=str(chunk))
        jsonl_line = JsonlLine(custom_id=custom_id, body=embedding_body)
        file.write(json.dumps(jsonl_line.model_dump_json) + "\n")


    async def upload_parquet_for_embedding(self, html_parquet_path: Path) -> None:
        """
        Upload a parquet file to OpenAI for embedding processing.

        This method reads a parquet file containing HTML content, processes each row,
        prepares the text for embedding, and creates a JSONL file that is then
        uploaded to OpenAI for batch embedding generation.
        The method handles large texts by chunking them into smaller pieces when 
        they exceed the maximum token limit. It also ensures the JSONL file stays 
        within OpenAI's batch processing limits (under 50,000 lines and 200 MB).

        Args:
            html_parquet_path (Path): Path to the input parquet file containing
                HTML content to be embedded.
        Raises:
            Exception: Any errors during the processing or uploading are logged
                but not re-raised.
        Note:
            - The parquet file should have columns 'html_title', 'html', and 'cid'
            - GNIS (Geographic Names Information System) identifier is extracted from the filename
            - Token count is tracked for each text and accumulated in self.total_token_count
        """
        try:
            gnis = str(html_parquet_path.stem.split("_")[0])
            # Make sure gnis ONLY contains numeric values
            if not gnis.isdigit():
                logger.warning(f"GNIS '{gnis}' does not contain only numeric values.")
                return

            df = pd.read_parquet(html_parquet_path)

            with tempfile.TemporaryDirectory() as temp_dir:

                temp_path = os.path.join(temp_dir, f'{gnis}.jsonl')
                with open(temp_path, 'w', newline='\n') as jsonl_file:

                    line_count = 0
                    for row in df.itertuples():
                        text = self._prepare_html_for_embedding(row.html_title, row.html) # type: ignore
                        if text == "":
                            logger.debug(f"Skipping empty text for '{gnis}'\nCID: {row.cid}")
                            continue
                        logger.debug(f"text: {text}")
                        token_count: int = self.get_token_count(text)
                        self.total_token_count += token_count

                        # If the text is too long, split it into chunks and tokenize each chunk.
                        if token_count > self.max_embedding_input_size:
                            logger.debug(f"Splitting request for {gnis}_{row.cid} due to token count '{token_count}' being over '{self.max_embedding_input_size}'.")
                            text_chunks = self.chunk_text_by_tokens(text)
                            for i, chunk in enumerate(text_chunks, start=1):
                                self._write_to_jsonl_line(jsonl_file, chunk, f"{gnis}_{row.cid}_chunk_{i}")
                                line_count += 1
                            continue
                        else:
                            self._write_to_jsonl_line(jsonl_file, text, f"{gnis}_{row.cid}")
                            line_count += 1

                        # Make sure the jsonl_file is under 50,000 lines and 200 MB
                        # Leave 1000 lines of space.
                        if line_count > 49000:
                            logger.warning(f"Reached 49000 lines limit for {gnis}, stopping further processing")
                            break
                        # Leave 5 MB of space.
                        if os.path.getsize(jsonl_file.name) > 195000000:
                            logger.warning(f"Reached file size limit (195MB) for {gnis}, stopping further processing")
                            break

                # Upload the JSONL file to OpenAI
                purpose = "batch"
                assert purpose == "batch" # I'd rather raise an error than let this shit fuck up again!
                with open(temp_path, "rb") as jsonl_file:
                    await self.async_client.files.create(
                        file=jsonl_file,
                        purpose=purpose
                    )

                logger.info(f"Uploaded gnis '{gnis}' to OpenAI for embedding.")
            logger.info(f"Finished processing {html_parquet_path}")

        except Exception as e:
            logger.exception(f"Error processing {html_parquet_path}: {e}")

    async def create_batch_from_files(self) -> None:
        """
        Creates batch embedding jobs from uploaded files.

        This asynchronous method retrieves all files from the OpenAI API and creates a batch 
        embedding job for each file. Each batch job is configured with a 24-hour completion window
        and includes metadata about the source file and the embedding model being used.

        Returns:
            None: Batch jobs are stored in the instance's batch_jobs list.

        Raises:
            Potential OpenAI API exceptions are not explicitly handled by this method.
        """
        try:
            # Get files list from OpenAI
            files_response = await self.async_client.files.list()
            try:
                logger.info(f"Found {len(files_response)} files to process") # type: ignore
            except Exception as e:
                logger.info(f"Found files to process but could not determine count: {e}")
            count = 0

            for file in files_response.data:
                file: FileObject
                try:
                    # Check if file is a tuple or has expected attributes
                    input_file_id = file.id
                    if not input_file_id:
                        logger.error(f"Could not extract file ID from: {file}")
                        continue

                    file_name = file.filename
                    if not file_name:
                        logger.warning(f"Skipping file with filename: {file}")
                        continue

                    gnis = get_gnis_from_file_name(file_name, ending=".jsonl")

                    logger.info(f"Creating batch for file ID: {input_file_id}, name: {file_name}")
                    try:
                        metadata = BatchMetadata(description=f"embeddings for {gnis}", model=self.model)
                    except ValidationError as e:
                        logger.error(f"Error creating metadata for file '{file_name}': {e}")
                        continue

                    batch = await self.async_client.batches.create(
                        input_file_id=input_file_id,
                        endpoint="/v1/embeddings",
                        completion_window="24h",
                        metadata=metadata.model_dump() # Convert to dict for OpenAI API
                    )
                    self.batch_jobs.append(batch)
                    count += 1
                    logger.info(f"Batch created for {file_name} with ID {batch.id}")
                except Exception as e:
                    logger.error(f"Error creating batch for file: {e}")

            logger.info(f"Created {count} batches")
        except Exception as e:
            logger.error(f"Error in create_batch_from_files: {e}")

    async def monitor_batch_jobs(self) -> AsyncGenerator[str, None]:
        """
        Monitor the status of batch jobs and yield completed job IDs.

        This asynchronous method tracks the progress of all batch jobs stored in self.batch_jobs.
        It continuously checks each job's status until all jobs are completed or at least one job fails.
        Job statuses are logged appropriately based on their state (completed, failed, in_progress, etc.).

        Yields:
            str: The job ID of each completed batch job.
        Returns:
            AsyncGenerator[str, None]: An async generator that yields completed job IDs.
        Note:
            - The method includes a 10-minute (600 second) sleep between status checks.
            - After all jobs are processed, it logs statistics about any failed requests.
        """

        job_ids = [job.id for job in self.batch_jobs]
        fail_flag = False
        finished = set()

        while True:
            for job_id in job_ids:
                job: Batch = await self.async_client.batches.retrieve(job_id)
                match job.status:
                    case "completed":
                        logger.info(f"Batch {job_id} completed")
                        logger.info(f"Output file ID: {job.output_file_id}")
                        finished.add(job_id)
                        yield job_id
                    case "failed":
                        #If any of the jobs failed we will stop and check it up.  
                        logger.error(f"Job {job_id} has failed with error {job.errors}")
                        fail_flag = True
                        break
                    case "expired":
                        logger.error(f"Job {job_id} expired")
                    case "cancelled":
                        logger.error(f"Job {job_id} cancelled")
                    case "in_progress":
                        logger.info(
                            f'Job {job_id} is in progress, {job.request_counts.completed}/{job.request_counts.total} requests completed' # type: ignore
                        )
                    case "finalizing":
                        logger.info(f'Job {job_id} is finalizing, waiting for the output file id')
                    case _:
                        logger.info(f"Batch {job.id} is {job.status}")

            if fail_flag == True or len(finished) == len(job_ids):
                break
            time.sleep(600)

        # Check for failed embeddings
        for job_id in job_ids:
            job  = await self.async_client.batches.retrieve(job_id)
            logger.error(f'{job.request_counts.failed}/{job.request_counts.total} requests failed in job {job_id}') # type: ignore
        
        logger.info("All jobs have been processed")


    async def download_output_file(self, job_id: str) -> pd.DataFrame:
        """
        Downloads and processes the output file from an OpenAI batch embedding job.

        This method retrieves the output file from a completed batch job, parses the embeddings
        and metadata, and converts them into a structured DataFrame.

        Args:
            job_id (str): The ID of the batch job to retrieve the output for.

        Returns:
            pd.DataFrame: A DataFrame containing the processed embeddings with columns:
                - embedding_cid: Content identifier hash of the embedding
                - gnis: Geographic Names Information System identifier
                - cid: Content identifier of the original text
                - text_chunk_order: The order of the chunk if text was split (defaults to 1)
                - embedding: The vector embedding from OpenAI

        Raises:
            Exception: Catches and logs any errors that occur during processing of individual lines.

        Note:
            The method deletes the output file from OpenAI's servers after processing.
        """

        output = await self.async_client.batches.retrieve(job_id)
        output_file_id = output.output_file_id

        if output_file_id:
            content = await self.async_client.files.content(output_file_id)
            file = content.text
        else:
            return pd.DataFrame() # Return empty DataFrame if no output file

        # Extract the custom id and embedding
        parquet_rows = []
        for line in file.split('\n')[:-1]:
            try:
                data = json.loads(line)
                parquet_row = ParquetRow(**data)
                # Make sure the computed fields compute
                _ = parquet_row.embedding_cid
                _ = parquet_row.text_chunk_order
                parquet_rows.append(parquet_row)
            except Exception as e:
                logging.error(f"Error processing line: {e}")
                continue

        # Append the row to the DataFrame
        embedding_results = pd.DataFrame(
            parquet_rows,
            columns=['embedding_cid', 'gnis', 'cid', 'text_chunk_order', 'embedding']
        )
        await self.async_client.files.delete(output_file_id)
        return embedding_results


    def save_data_to_parquet(self, df: pd.DataFrame, parquet_path: Path, partition_column: str = "gnis") -> None:
        """
        Save DataFrame to parquet files, partitioned by the specified column.
        
        This method groups the data by the partition column and saves each group
        to a parquet file with gzip compression.
        
        Args:
            df (pd.DataFrame): The DataFrame to save
            parquet_path (Path): Path where the parquet file will be saved
            partition_column (str, optional): Column name to use for partitioning. Defaults to "gnis"

        Raises:
            ValueError: If the partition_column does not exist in the DataFrame
        """
        # Check if partition column exists
        if partition_column not in df.columns:
            raise ValueError(f"Partition column '{partition_column}' not found in DataFrame columns: {df.columns.tolist()}")

        # Group by partition column
        for partition_value, group_df in df.groupby(partition_column):

            # Save the group as a parquet file
            group_df.to_parquet(parquet_path, compression="gzip")
            logger.debug(f"Saved partition {str(partition_value)} with {len(group_df)} rows to {parquet_path}")




def validate_openai_api_key(api_key: str) -> None:
    try:
        # Validate API key by trying to create a client and listing models
        try:
            client = openai.OpenAI(api_key=api_key)
            # Try listing models to validate the key
            models = client.models.list()
            logger.info(f"API key is valid. Available models: {len(models.data)}")
            # Check if the embedding model is available
            embedding_model_available = any(model.id == "text-embedding-3-small" for model in models.data)
            if not embedding_model_available:
                raise ValueError("The specified embedding model 'text-embedding-3-small' is not available with the provided API key.")
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            raise ValidationError from e

    except ValueError as e:
        logger.error(f"Error initializing OpenAIEmbedding: {e}")
        raise ValidationError from e
    except Exception as e:
        logger.error(f"Unexpected error initializing OpenAIEmbedding: {e}")
        raise ValidationError from e


class OpenAiApiKey(BaseModel):
    """
    Model to handle OpenAI API key securely.
    
    This model uses Pydantic's SecretStr to ensure the API key is treated as a secret.
    """
    _api_key: Annotated[SecretStr, AV(validate_openai_api_key)] | None = None

    def __init__(self):
        # Get API key first from environment variable, then from configs if not in env
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            # Get API key from configs (handling SecretStr properly)
            api_key = configs.OPENAI_API_KEY.get_secret_value() if configs.OPENAI_API_KEY else None
        
        logger.info(f"API key found: {'Yes' if api_key else 'No'}")
        
        if not api_key:
            logger.error("No OpenAI API key found in environment or config. Cannot proceed.")
            raise ValidationError("No OpenAI API key found. Please set the OPENAI_API_KEY environment variable or provide it in the configs.")
        self._api_key = api_key # type: ignore[arg-type]
        self.model_validate(self)
    
    @property
    def api_key(self) -> str:
        if self._api_key is None:
            raise ValueError("API key has not been set.")
        return self._api_key.get_secret_value()


async def main(input_files: Optional[list[Path]] = None) -> int:
    logger = logging.getLogger(__name__)

    # Update to include the "american_law" subdirectory
    input_dir = configs.paths.ROOT_DIR / "input_from_sql" / "american_law" / "data"
    logger.info(f"Looking for files in: {input_dir}")
    
    # Check if directory exists
    if not input_dir.exists():
        logger.error(f"Directory does not exist: {input_dir}")
        return 1

    # Make one iteration through the loop to see what files are found
    html_files = list(input_dir.glob("*_html.parquet")) if input_files is None else input_files

    # Exit if no files found
    if not html_files:
        logger.info("No HTML parquet files found. Exiting.")
        return 1
    logger.info(f"Found {len(html_files)} HTML parquet files.")

    try:
        openai_embedding = OpenAIEmbedding(
            model="text-embedding-3-small",
            api_key=OpenAiApiKey().api_key,
        )
    except Exception as e:
        logger.exception(f"Error initializing OpenAIEmbedding: {e}")
        return 1
    logger.info("Starting to upload parquet files for embedding.")
    
    try:
        processed_count = 0
        error_count = 0

        # Process all files
        for html_parquet_path in html_files:
            try:
                gnis_str = html_parquet_path.stem.split("_")[0]
                embedding_path = input_dir / f"{gnis_str}_embeddings.parquet"

                if embedding_path.exists():
                    logger.info(f"Embeddings already exist for {gnis_str}.")
                    continue

                logger.info(f"Uploading {html_parquet_path.name} for embedding")
                await openai_embedding.upload_parquet_for_embedding(html_parquet_path)
                processed_count += 1
            except Exception as e:
                logger.error(f"Error processing {html_parquet_path}: {e}")
                error_count += 1
                continue

        # Create batch jobs from uploaded files
        try:
            logger.info("Creating batch embedding jobs from uploaded files")
            await openai_embedding.create_batch_from_files()
        except Exception as e:
            logger.error(f"Error in batch job processing: {e}")
            error_count += 1

        # Monitor and process batch jobs
        logger.info("Monitoring batch jobs")
        async for job_id in openai_embedding.monitor_batch_jobs():
            try:
                logger.info(f"Processing results for job {job_id}")
                df = await openai_embedding.download_output_file(job_id)
                if len(df) == 0:
                    logger.info(f"No embeddings found for job {job_id}")
                    continue
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}")
                error_count += 1
        logger.info(f"Embedding process completed. Processed: {processed_count}, Errors: {error_count}")

    except Exception as e:
        logger.error(f"Error in main processing loop: {e}")
        return 1

    logger.info("Embedding processing finished")
    return 0

if __name__ == "__main__":
    sys.exit(anyio.run(main()))
