import functools
import itertools
from pathlib import Path
from queue import Queue
from threading import RLock
from typing import Any, Callable, Generator, Optional


from types_ import DatabaseConnection, Logger

import duckdb
error_db: duckdb.DuckDBPyConnection
            

from dataclasses import dataclass
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
        cid (str): Primary key identifier for the error record
        citation_cid (str): Identifier for the related citation
        gnis (int): Geographic Names Information System identifier
        geography_error (bool): Whether there's a geography validation error
        type_error (bool): Whether there's a type validation error
        section_error (bool): Whether there's a section validation error
        date_error (bool): Whether there's a date validation error
        format_error (bool): Whether there's a format validation error
        severity (int): Error severity level (1-5, where 1 is low and 5 is critical)
        created_at (Optional[str]): Timestamp when the error was created (auto-generated in DB)
    """
    cid: str
    citation_cid: str
    gnis: int
    geography_error: bool
    type_error: bool
    section_error: bool
    date_error: bool
    format_error: bool
    severity: int
    created_at: Optional[str] = None

    def __post_init__(self):
        """Validate severity is within acceptable range."""
        if not 1 <= self.severity <= 5:
            raise ValueError("Severity must be between 1 and 5")


class CitationValidator:

    def __init__(self, resources=None, configs=None):
        self.resources = resources
        self.configs = configs

        self._random_seed = configs['random_seed']
        self._insert_batch_size = configs['insert_batch_size']

        self._load_citations_for_place: Callable = resources['load_citations_for_place']
        self._load_documents_for_place: Callable = resources['load_documents_for_place']
        self.__check_geography: Callable = resources['check_geography']
        self.__check_code: Callable = resources['check_code']
        self.__check_section: Callable = resources['run_section_checker']
        self.__check_dates: Callable = resources['run_date_checker']
        self.__check_formats: Callable = resources['run_format_checker']
        self.__validate_citation_consistency: Callable = resources['validate_citation_consistency']
        self.__run_in_thread_pool: Callable = resources['run_in_thread_pool']

        self._logger: Logger = resources['logger']

        self._duckdb = resources['duckdb']

        self._validation_queue = Queue()
        self._lock = RLock()


    def _validate_citations_for_gnis(
        self,
        gnis: int, 
        citations: list[Path] = None, 
        html: list[Path] = None, 
        reference_db: DatabaseConnection = None
        ): #-> list[dict[str, CheckResult]]:
        """
        Yields:
            A dictionary containing validation results for each citation.

        """
        place_citations: list[dict] = self._load_citations_for_place(gnis, citations)
        place_documents: list[dict] = self._load_documents_for_place(gnis, html)

        print(f"Validating {len(place_citations)} citations for place {gnis}...")
        # Bluebook citation example: ("1234567890", "City of Example", "Mass.", "Municipal Code", "§ 123-456", "2023",)
        for citation in place_citations:
            yield {
                "gnis": gnis,
                "citation": citation,
                "geography": self._check_geography(citation, reference_db), # -> bool
                "type": self._check_code(citation, reference_db), # -> bool
                "section": self._check_section(citation, place_documents), # -> bool
                "date": self._check_dates(citation, place_documents), # -> bool
                "format": self._check_formats(citation) # -> bool
            }

    @staticmethod
    def error_message(name: str, e: Exception) -> str:
        name = name.split('.')[0].capitalize()
        f'{name} check failed with {type(e).__name__}: {e}'

    @property
    def iterable_validation_queue(self) -> Generator[Any, None, None]:
        """Convert the queue to an iterable for batch processing"""
        if self._validation_queue is not None:
            while not self._validation_queue.empty():
                yield self._validation_queue.get()

    def _run_check(self, 
                   func: Callable = None, 
                   citation: dict = None, 
                   error_type: str = None, 
                   reference_db: Optional[DatabaseConnection] = None, 
                   place_documents: Optional[list[dict]] = None
                   ) -> dict:

        if not func or not citation or not error_type:
            raise ValueError("Function, citation, and error_type must be provided")

        result = CheckResult(valid=True) # Prevent UnboundLocalError if exception occurs before assignment
        try:
            error_message = func(citation, reference_db, place_documents)
            if error_message is not None:
                result = CheckResult(
                    valid=False,
                    error_type=error_type,
                    message=error_message
                ).to_dict()
        except Exception as e:
            self._logger.exception(self.error_message(error_type, e))
            result = CheckResult(
                valid=False,
                error_type=error_type,
                message=self.error_message(error_type, e)
            )
        return result.to_dict()

    def _check_geography(self, citation: dict=None, reference_db=None, DatabaseConnection=None, place_documents=None) -> CheckResult:
        return self._run_check(
            func=self.__check_geography,
            citation=citation,
            error_type='geography_error',
            reference_db=reference_db
        )

    def _check_code(self, citation: dict=None, reference_db=None, DatabaseConnection=None, place_documents=None) -> CheckResult:
        return self._run_check(
            func=self.__check_code,
            citation=citation,
            error_type='code_error',
            reference_db=reference_db
        )

    def _check_section(self, citation: dict=None, reference_db=None, DatabaseConnection=None, place_documents=None) -> CheckResult:
        return self._run_check(
            func=self.__check_section,
            citation=citation,
            error_type='section_error',
            place_documents=place_documents
        )

    def _check_dates(self, citation: dict=None, reference_db=None, DatabaseConnection=None, place_documents=None) -> CheckResult:
        return self._run_check(
            func=self.__check_dates,
            citation=citation,
            error_type='date_error',
            place_documents=place_documents
        )

    def _check_formats(self, citation: dict=None, reference_db=None, DatabaseConnection=None, place_documents=None) -> CheckResult:
        return self._run_check(
            func=self.__check_formats,
            citation=citation,
            error_type='format_error'
        )

    def save_validation_errors(self, citation: dict, results, error_db: duckdb.DuckDBPyConnection):
        """
        Save validation errors for a citation to the error database.

        Args:
            citation: The citation that was validated
            results: The validation results containing error information
            error_db: The database connection for storing validation errors
        """
        try:
            with self._lock.acquire(timeout=10): # Since duckdb does not support concurrent writes, we need to lock it first.
                with error_db.cursor() as cursor:
                    cursor.begin()
        except TimeoutError as e:
            self._logger.error(f"Failed to acquire lock for saving validation errors: {e}")
            return 0

        finally:
            self._lock.release()



    def validate_citations_against_html_and_references(self, 
                                            citations: list[Path], 
                                            html: list[Path], 
                                            gnis_for_sampled_places, 
                                            reference_db, 
                                            error_db
                                            ) -> tuple[list]:

        print("Running validation on sampled places...")
        total_citations: int = 0
        total_errors: int = 0
        db_inputs: list[dict] = []
        result_list: list[dict] = []

        _validator_func = functools.partial(
            self._validate_citations_for_gnis,
            citations=citations,
            html=html,
            reference_db=reference_db
        )

        for results, gnis in self.__run_in_thread_pool(_validator_func, gnis_for_sampled_places, max_concurrency=5):
            total_citations += len(results)
            self._validation_queue.put(results)

        while not self._validation_queue.empty():
            for citation in itertools.batched(self.iterable_validation_queue, self._insert_batch_size): # Save any errors found
                error_count: int = self.save_validation_errors(citation, results, error_db)
            result_list.extend(results)

            total_errors += error_count

        print(f"Validated {total_citations} citations, found {total_errors} errors")
        return result_list

