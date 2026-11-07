"""Hungary NJT local-decree collector. Importing this module does not run it."""
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "hub_integrated" / Path("legal_scrapers/municipal/collect_hu_njt.py")

def vendored_path() -> Path:
    return VENDORED
