"""Denmark NSTAR municipal collector. Importing this module does not run it."""
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "hub_integrated" / Path("legal_scrapers/municipal/collect_dk_nstar.py")

def vendored_path() -> Path:
    return VENDORED
