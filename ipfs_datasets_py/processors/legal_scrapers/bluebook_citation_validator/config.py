"""Configuration dataclass for the Bluebook citation validator."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ValidatorConfig:
    """Configuration for the Bluebook citation validator.

    Attributes:
        citation_dir: Path to directory containing citation parquet files.
        document_dir: Path to directory containing HTML document parquet files.
        error_db_path: Path for the DuckDB error database.
        error_report_db_path: Path for the DuckDB error-report database.
        output_dir: Path for generated report output.
        random_seed: RNG seed for reproducible stratified sampling.
        insert_batch_size: Number of error rows to insert per DB transaction.
        sample_size: Target size of the stratified sample (default 385 ≈ 95 % CI ±5 %).
        max_concurrency: Thread-pool size for parallel place validation.
        mysql_host: MySQL server hostname (reference DB).
        mysql_port: MySQL server port.
        mysql_user: MySQL username.
        mysql_password: MySQL password.
        mysql_database: MySQL database / schema name.
    """

    citation_dir: Path = field(default_factory=lambda: Path("./citations"))
    document_dir: Path = field(default_factory=lambda: Path("./documents"))
    error_db_path: Path = field(default_factory=lambda: Path("bluebook_errors.duckdb"))
    error_report_db_path: Path = field(default_factory=lambda: Path("bluebook_error_reports.duckdb"))
    output_dir: Path = field(default_factory=lambda: Path("./reports"))
    random_seed: int = 420
    insert_batch_size: int = 5000
    sample_size: int = 385
    max_concurrency: int = 8
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""

    def __post_init__(self) -> None:
        # Coerce strings → Path objects to be forgiving of CLI usage.
        for attr in ("citation_dir", "document_dir", "error_db_path",
                     "error_report_db_path", "output_dir"):
            value = getattr(self, attr)
            if not isinstance(value, Path):
                object.__setattr__(self, attr, Path(value))

    # Allow dict-style read access so legacy code using configs['key'] still works.
    def __getitem__(self, key: str):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"ValidatorConfig has no field '{key}'")

    @property
    def mysql_configs(self) -> dict:
        """Return MySQL connection parameters as a plain dict."""
        return {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "database": self.mysql_database,
        }
