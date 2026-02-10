from enum import Enum
import os
from pathlib import Path


class DefaultPaths(Path, Enum):
    PROJECT_ROOT: Path = Path(os.getcwd())
    INPUT_DIR: Path = PROJECT_ROOT / "input"
    OUTPUT_DIR: Path = PROJECT_ROOT / "output"
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    DATABASE_DIR: Path = PROJECT_ROOT / "database"
    FILE_PATH_MANAGER_DUCK_DB_PATH: Path = DATABASE_DIR / "file_path_manager.db"