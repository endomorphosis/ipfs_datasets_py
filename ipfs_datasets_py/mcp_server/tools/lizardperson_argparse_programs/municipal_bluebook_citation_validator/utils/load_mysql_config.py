from pathlib import Path


from dependencies import dependencies


def load_mysql_config(config_path: Path) -> dict[str, str]:
    """Load MySQL connection settings from a YAML config file."""
    try:
        with open(config_path, 'r') as file:
            config: dict[str, str] = dependencies.yaml.safe_load(file)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    except dependencies.yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML config file: {e}")
    else:
        return dict(config)

