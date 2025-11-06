import argparse
from pathlib import Path
import random

_RANDOM_SEED = 420
# Set random seed for reproducibility
random.seed(_RANDOM_SEED)

try:
    from pydantic import (
        BaseModel, 
        ValidationError, 
        Field, 
        DirectoryPath, 
        FilePath, PositiveInt, SecretStr
    )
except ImportError:
    raise ImportError("pydantic is required for this module. Please install it using 'pip install pydantic'.")


from .utils.parse_arguments import parse_arguments
from .utils.load_mysql_config import load_mysql_config


class _MySqlConfig(BaseModel):
    """
    Configuration model for MySQL database connection parameters.

    Attributes:
        host (str): The hostname or IP address of the MySQL server.
        port (int): The port number on which the MySQL server is listening.
        user (SecretStr): The username for database authentication (stored securely).
        password (SecretStr): The password for database authentication (stored securely).
        database (SecretStr): The name of the database to connect to (stored securely).
    """
    host: str
    port: int
    user: SecretStr
    password: SecretStr
    database: SecretStr

class _Configs(BaseModel):
    error_db_path: FilePath = Field(default_factory=lambda: Path("bluebook_error_database.db"))
    citation_dir: DirectoryPath = Field(default_factory=lambda: Path("./citations"))
    document_dir: DirectoryPath = Field(default_factory=lambda: Path("./documents"))
    output_dir: DirectoryPath = Field(default_factory=lambda: Path("./reports"))
    random_seed: PositiveInt = Field(default=_RANDOM_SEED)
    insert_batch_size: PositiveInt = Field(default=5000)
    sample_size: PositiveInt = Field(default=385)

    mysql_configs_internal: _MySqlConfig = Field(default_factory=None)

    @property
    def mysql_configs(self) -> dict:
        """Return MySQL configurations as a Pydantic model."""
        return {
            "host": self.mysql_configs_internal.host,
            "port": self.mysql_configs_internal.port,
            "user": self.mysql_configs_internal.user.get_secret_value(),
            "password": self.mysql_configs_internal.password.get_secret_value(),
            "database": self.mysql_configs_internal.database.get_secret_value()
        }

    @mysql_configs.setter
    def mysql_configs(self, value: dict):
        """Set MySQL configurations from a dictionary."""
        try:
            self.mysql_configs_internal = _MySqlConfig(**value)
        except ValidationError as e:
            raise ValueError(f"Invalid MySQL configuration: {e}")

    @property
    def ROOT_DIR(self) -> Path:
        """Return the root directory of the project."""
        return Path(__file__).parent
    
    def to_dict(self) -> dict:
        """Convert the configuration to a dictionary."""
        return self.model_dump(mode="python", exclude_none=True)

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"Configuration key '{key}' not found.")

if __name__ == "__main__":
    # Parse command line arguments
    args: argparse.Namespace = parse_arguments()

    # Setup configs.
    configs = _Configs(
        error_db_path=args.error_db_path,
        citation_dir=args.citation_dir,
        document_dir=args.document_dir,
        output_dir=args.output_dir,
        random_seed=_RANDOM_SEED,
        sample_size=args.sample_size,
    )

    mysql_configs=load_mysql_config(args.mysql_config)

