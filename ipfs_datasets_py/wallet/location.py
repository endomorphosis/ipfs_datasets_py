"""Location privacy helpers for the data wallet."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from .models import LocationClaim


def coarse_location(lat: float, lon: float, precision: int = 2) -> Dict[str, float]:
    """Return rounded coordinates for coarse service matching.

    Precision 2 is roughly neighborhood/city-scale and should be adjusted by
    policy for production use.
    """

    return {"lat": round(float(lat), precision), "lon": round(float(lon), precision)}


def region_membership_statement(lat: float, lon: float, region_id: str) -> Dict[str, Any]:
    """Create a deterministic public statement for a simulated region proof.

    This MVP does not include polygon circuits. It commits to the precise point
    privately and exposes only the requested region identifier.
    """

    witness_commitment = hashlib.sha256(f"{float(lat):.8f}:{float(lon):.8f}:{region_id}".encode()).hexdigest()
    return {
        "region_id": region_id,
        "claim": "location_in_region",
        "witness_commitment": witness_commitment,
    }


def make_coarse_location_claim(record_id: str, lat: float, lon: float, precision: int = 2) -> LocationClaim:
    return LocationClaim(
        claim_type="coarse_location",
        public_value=coarse_location(lat, lon, precision),
        source_record_id=record_id,
        precision=f"rounded:{precision}",
    )


def serialize_location(lat: float, lon: float, source: str = "user", accuracy_m: float | None = None) -> bytes:
    payload = {
        "lat": float(lat),
        "lon": float(lon),
        "source": source,
        "accuracy_m": accuracy_m,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
