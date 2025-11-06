import functools
import itertools
from pathlib import Path
from queue import Queue
import time
from threading import RLock
from typing import Any, Callable, Generator, Optional


from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import Configs, DatabaseConnection, Logger

import duckdb
error_db: duckdb.DuckDBPyConnection

class _CitationValidatorError(Exception):
    """Base class for all citation validation errors."""
    pass

from dataclasses import dataclass, InitVar
@dataclass
class CheckResult:
    """
    The result of a citation validation check.

    Attributes:
        valid (bool): Whether the citation passed validation. Defaults to True.
        error_type (Optional[str]): The type of validation error encountered, if any.
            None when the citation is valid.
        message (Optional[str]): A descriptive message about the validation result.
            None when the citation is valid.
    """
    valid: bool = True
    error_type: Optional[str] = None # Optional for cases where no error type is needed, e.g., valid checks
    message: Optional[str] = None # Optional for cases where no message is needed, e.g., valid checks

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the CheckResult to a dictionary.

        Returns:
            A dictionary representation of the CheckResult.
        """
        return {
            "valid": self.valid,
            "error_type": self.error_type,
            "message": self.message
        }

@dataclass
class ErrorDbInsert:
    """
    Represents an error record to be inserted into the errors database table.

    Attributes:
        cid (str): Primary CID identifier for the error record. 
            Created by hashing all other fields together once they are assigned.
        citation_cid (str): CID Identifier for the related citation
        gnis (int): Geographic Names Information System identifier
        geography_error (str): Geography validation error message (empty string if none)
        type_error (str): Type validation error message (empty string if none)
        section_error (str): Section validation error message (empty string if none)
        date_error (str): Date validation error message (empty string if none)
        format_error (str): Format validation error message (empty string if none)
        error_message (str): Combined error message for all validation errors
        severity (int): Error severity level (1-5, where 1 is low and 5 is critical)
        created_at (Optional[str]): Timestamp when the error was created (auto-generated in DB)
    """
    citation_cid: str
    gnis: int
    geography_error: str = None 
    type_error: str = None
    section_error: str = None
    date_error: str = None
    format_error: str  = None
    severity: int = None
    error_message: str = None
    created_at: str = None
    cid: str = None # Created afterwards by hashing all the other fields together

    def __post_init__(self):
        """Validate severity is within acceptable range."""
        if not 1 <= self.severity <= 5:
            raise ValueError("Severity must be between 1 and 5")
        self.created_at = time.strftime('%Y-%m-%d %H:%M:%S')


class CitationValidator:

    def __init__(self, resources=None, configs: Configs = None):
        self.resources = resources
        self.configs = configs

        self._max_concurrency = configs['max_concurrency']
        self._random_seed = configs['random_seed']
        self._insert_batch_size = configs['insert_batch_size']
        self._citation_dir = configs['citation_dir']
        self._citation_dir = configs['html_dir']
        self._save_validation_errors_sql_path: str = (self.configs.ROOT_DIR / "citation_validator" / "_save_validation_errors.sql").resolve()


        self._load_citations_for_place: Callable = resources['load_citations_for_place']
        self._load_documents_for_place: Callable = resources['load_documents_for_place']
        self.__check_geography: Callable = resources['check_geography']
        self.__check_code: Callable = resources['check_code']
        self.__check_section: Callable = resources['run_section_checker']
        self.__check_dates: Callable = resources['run_date_checker']
        self.__check_formats: Callable = resources['run_format_checker']
        self.__validate_citation_consistency: Callable = resources['validate_citation_consistency'] # TODO Might just remove this.
        self.__run_in_thread_pool: Callable = resources['run_in_thread_pool']

        self._logger: Logger = resources['logger']

        self._duckdb = resources['duckdb']
        self._tqdm = resources['tqdm']
        self._reference_db: DatabaseConnection = None # Reference database for validation checks. Set in public method.

        self._gnis_queue = Queue() # Queue for paths to be processed
        self._validation_queue = Queue() # Queue for validation results
        self._lock = RLock()

        self._save_validation_errors_string: str = self._load_save_validation_errors_string()


    def _load_save_validation_errors_string(self) -> None:
        try:
            with open(self._save_validation_errors_sql_path, "r") as f:
                return f.read()
        except FileNotFoundError as e:
            raise FileNotFoundError(f"SQL file for saving validation errors not found: {e}")
        except Exception as e:
            raise Exception(f"Failed to read SQL file for saving validation errors: {e}")

    def _validate_citations(self, gnis: int) -> list[dict[str, CheckResult]]:
        """
        Returns:
            A list of dictionaries containing validation results for each citation in the parquet file.
        """
        try:
            place_citations: list[dict] = self._load_citations_for_place(gnis, self._citation_dir)
            place_documents: list[dict] = self._load_documents_for_place(gnis, self._citation_dir)
        except FileNotFoundError as e:
            self._logger.error(f"File not found for place {gnis}: {e}")
            return []
        except Exception as e:
            self._logger.exception(f"Failed to load citations or documents for place {gnis}: {e}")
            return []

        print(f"Validating {len(place_citations)} citations for place {gnis}...")
        # Bluebook citation example: ("1234567890", "City of Example", "Mass.", "Municipal Code", "§ 123-456", "2023",)
        return [
            ErrorDbInsert(
                citation_cid=citation['cid'],
                gnis=gnis,
                geography_error=self._check_geography(citation, self._reference_db), #  -> dict
                type_error=self._check_code(citation, self._reference_db), #  -> dict
                section_error=self._check_section(citation, self._reference_db, place_documents), #  -> dict
                date_error=self._check_dates(citation, self._reference_db, place_documents), #  -> dict
                format_error=self._check_formats(citation, self._reference_db), #  -> dict
            ) for citation in place_citations 
        ]

    @staticmethod
    def error_message(name: str, e: Exception) -> str:
        name = name.split('.')[0].capitalize()
        f'{name} check failed with {type(e).__name__}: {e}'

    @property
    def iterable_validation_queue(self) -> Generator[Any, None, None]:
        """Convert the queue to an iterable for batch processing"""
        if self._validation_queue is not None:
            yield from self._queue_to_iterable(self._validation_queue)

    @property
    def iterable_gnis_queue(self) -> Generator[Any, None, None]:
        """Convert the queue to an iterable for batch processing"""
        if self._gnis_queue is not None:
            yield from self._queue_to_iterable(self._gnis_queue)

    @staticmethod
    def _queue_to_iterable(queue: Queue) -> Generator[Any, None, None]:
        """Convert a Queue to an iterable generator.
        
        Args:
            queue (Queue): The queue to convert.
        
        Yields:
            Any: Items from the queue.
        """
        while not queue.empty():
            yield queue.get()

    def _run_check(self, 
                   func: Callable = None, 
                   citation: dict = None, 
                   error_type: str = None, 
                   place_documents: Optional[list[dict]] = None
                   ) -> Optional[dict]:
        """
        Run a validation check on a citation.
        Args:
            func (Callable): The validation function to run.
            citation (dict): The citation to validate.
            error_type (str): The type of error to report if validation fails.
        """
        if not func or not citation or not error_type:
            raise ValueError("Function, citation, and error_type must be provided")

        result = CheckResult(valid=True) # Prevent UnboundLocalError if exception occurs before assignment
        try:
            error_message = func(citation, place_documents)
            if error_message is not None:
                result = CheckResult(
                    valid=False,
                    error_type=error_type,
                    message=error_message
                )
        except Exception as e:
            self._logger.exception(self.error_message(error_type, e))
            result = CheckResult(
                valid=False,
                error_type=error_type,
                message=self.error_message(error_type, e)
            )
        return result.to_dict() if not result.valid else None # Should automatically filter out valid results

    def _check_geography(self, citation: dict=None, place_documents=None) -> dict:
        return self._run_check(
            func=self.__check_geography,
            citation=citation,
            error_type='geography_error',
            reference_db=self._reference_db
        )

    def _check_code(self, citation: dict=None, place_documents=None) -> dict:
        return self._run_check(
            func=self.__check_code,
            citation=citation,
            error_type='code_error',
            reference_db=self._reference_db
        )

    def _check_section(self, citation: dict=None, place_documents=None) -> dict:
        if not place_documents:
            raise ValueError("place_documents must be provided for date checks")

        return self._run_check(
            func=self.__check_section,
            citation=citation,
            error_type='section_error',
            place_documents=place_documents
        )

    def _check_dates(self, citation: dict=None,  place_documents=None) -> dict:
        if not place_documents:
            raise ValueError("place_documents must be provided for date checks")

        return self._run_check(
            func=self.__check_dates,
            citation=citation,
            error_type='date_error',
            place_documents=place_documents
        )

    def _check_formats(self, citation: dict=None, place_documents=None) -> dict:
        return self._run_check(
            func=self.__check_formats,
            citation=citation,
            error_type='format_error'
        )

    def save_validation_errors(self, result_batch: list[dict[str, Any]], error_db: duckdb.DuckDBPyConnection) -> int:
        """
        Save validation errors for a citation to the error database.

        Args:
            results: The validation results containing error information
            error_db: The database connection for storing validation errors
        """
        insert_batch = []
        ErrorDbInsert
        for result in result_batch:
            try:
                gnis = result['gnis']
                citation_cid = result['cid']

                # Check each validation type for errors
                geography_check = result.get('geography', {})
                type_check = result.get('type', {})
                section_check = result.get('section', {})
                date_check = result.get('date', {})
                format_check = result.get('format', {})

                # Determine if there are any errors
                geography_error = not geography_check.get('valid', True)
                type_error = not type_check.get('valid', True)
                section_error = not section_check.get('valid', True)
                date_error = not date_check.get('valid', True)
                format_error = not format_check.get('valid', True)

                # Only save if there are errors
                if any([geography_error, type_error, section_error, date_error, format_error]):
                    # Collect error messages
                    error_messages = []
                    if geography_error:
                        error_messages.append(f"Geography: {geography_check.get('message', 'Unknown error')}")
                    if type_error:
                        error_messages.append(f"Type: {type_check.get('message', 'Unknown error')}")
                    if section_error:
                        error_messages.append(f"Section: {section_check.get('message', 'Unknown error')}")
                    if date_error:
                        error_messages.append(f"Date: {date_check.get('message', 'Unknown error')}")
                    if format_error:
                        error_messages.append(f"Format: {format_check.get('message', 'Unknown error')}")

                    error_message = "; ".join(error_messages) # This or error_messages list should be exported to the error report generator.

                    # Determine severity based on number and type of errors.
                    num_errors = sum([geography_error, type_error, section_error, date_error, format_error])
                    critical_errors = geography_error or type_error
                    severity = 5 if critical_errors else num_errors

                    # Prepare the SQL insert statement
                    sql_insert = [
                        citation_cid, gnis, geography_error, type_error, section_error,
                        date_error, format_error, severity, time.strftime('%Y-%m-%d %H:%M:%S')
                    ]
                    cid = self._make_cid(sql_insert)
                    sql_insert.insert(0, cid)
                    insert_batch.append(tuple(sql_insert))
            except Exception as e:
                self._logger.exception(f"Error processing result for gnis {gnis}: {e}")
                continue

        try:
            with self._lock.acquire(timeout=10): # Since duckdb does not support concurrent writes, we need to lock it first.
                with error_db.cursor() as cursor:
                    cursor.begin()
                    # Insert error record into database
                    cursor.sql("""
                        INSERT INTO error_reports (
                            cid, 
                            citation_cid, 
                            gnis, 
                            geography_error, 
                            type_error, 
                            section_error, 
                            date_error, 
                            format_error, 
                            severity,
                            error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, )
                    error_count += num_errors


        except TimeoutError as e:
            self._logger.error(f"Failed to acquire lock for saving validation errors: {e}")
            return 0

        finally:
            self._lock.release()


    def validate_citations_against_html_and_references(self, 
                                            # citation_paths: list[Path], 
                                            # html_paths: list[Path], 
                                            sampled_gnis, 
                                            reference_db, 
                                            error_db
                                            ) -> tuple[list]:
        # Set here so that we don't need to create it in the factory function
        self._reference_db = reference_db

        print("Running validation on sampled places...")
        total_citations: int = 0
        total_errors: int = 0
        result_list: list[dict] = []
 
        pbar = None # Avoid UnboundLocalError.
        try:
            pbar = self._tqdm(total=len(sampled_gnis), desc="Validating citations", unit="place")

            # Initialize the GNIS queue with sampled places
            for gnis in gnis_batch:
                self._gnis_queue.put(gnis)
                self._gnis_queue

            # Validate GNIS identifiers in batches.
            # This should stop the program from loading everything into memory at once.
            while not self._gnis_queue.empty():
                for gnis_batch in itertools.batched(self.iterable_gnis_queue, self._max_concurrency):
                    for results, gnis in self.__run_in_thread_pool(self._validate_citations, gnis_batch, max_concurrency=self._max_concurrency, use_tqdm=False):
                        total_citations += len(results)
                        self._validation_queue.put(results)

            while not self._validation_queue.empty(): # Save any errors found
                for result_batch in itertools.batched(self.iterable_validation_queue, self._insert_batch_size): 
                    error_count: int = self.save_validation_errors(result_batch, error_db)
                result_list.extend(results)

                total_errors += error_count
                if pbar is not None:
                    pbar.update(1)
        finally:
            if pbar is not None:
                pbar.close()

        print(f"Validated {total_citations} citations, found {total_errors} errors")
        return result_list

