from pathlib import Path

def load_sql_file(path: str | Path, encoding="utf-8") -> str:
    """
    Load and return the contents of a SQL file as a string.

    Args:
        path (str or Path): Path to the SQL file.
        encoding (str): Encoding to use when reading the file. Defaults to "utf-8".

    Returns:
        str: Contents of the SQL file.

    Raises:
        TypeError: If the provided path is not a string or Path object.
        ValueError: If the path does not point to a SQL file.
        FileNotFoundError: If the SQL file does not exist or cannot be found.
        IOError: If there is an error reading the file.
        Exception: For any other unexpected errors.
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(f"Expected path to be str or Path, got {type(path).__name__}")

    sql_path = Path(path)
    if not sql_path.name.endswith(".sql"):
        raise ValueError(f"Provided path does not point to a SQL file: {sql_path}")

    try:
        sql_path = sql_path.resolve(strict=True)
        with sql_path.open("r", encoding=encoding) as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"SQL file not found: {sql_path}")
    except IOError as e:
        raise IOError(f"Error reading SQL file {sql_path}: {e}") from e
    except Exception as e:
        raise Exception(f"Unexpected {type(e).__name__} loading SQL file {sql_path}: {e}") from e
