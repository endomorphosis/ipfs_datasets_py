"""Jordan Official Gazette collector. Importing this module does not run it."""
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "hub_integrated" / Path("legal_scrapers/municipal/collect_jo_gazette.py")

def vendored_path() -> Path:
    return VENDORED
