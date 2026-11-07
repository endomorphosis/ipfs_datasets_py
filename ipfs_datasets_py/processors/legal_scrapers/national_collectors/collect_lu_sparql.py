"""Luxembourg legilux SPARQL collector. Importing this module does not run it."""
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "hub_integrated" / Path("justicedao_world_law_scrapers/collectors/lu_sparql_collect.py")

def vendored_path() -> Path:
    return VENDORED
