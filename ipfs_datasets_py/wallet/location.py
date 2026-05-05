"""Location privacy helpers for the data wallet."""

from __future__ import annotations

import hashlib
import json
import math
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


def haversine_distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Return great-circle distance in kilometers between two coordinates."""

    radius_km = 6371.0088
    lat_a_rad = math.radians(float(lat_a))
    lat_b_rad = math.radians(float(lat_b))
    delta_lat = math.radians(float(lat_b) - float(lat_a))
    delta_lon = math.radians(float(lon_b) - float(lon_a))
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def distance_membership_statement(
    lat: float,
    lon: float,
    *,
    target_id: str,
    target_lat: float,
    target_lon: float,
    max_distance_km: float,
) -> Dict[str, Any]:
    """Create a public statement for proving location is near a target.

    The precise wallet point and target coordinates are committed privately.
    Public inputs expose the target policy hash and threshold, not the user's
    exact coordinates.
    """

    target_policy_hash = hashlib.sha256(
        f"{target_id}:{float(target_lat):.8f}:{float(target_lon):.8f}:{float(max_distance_km):.6f}".encode()
    ).hexdigest()
    witness_commitment = hashlib.sha256(
        (
            f"{float(lat):.8f}:{float(lon):.8f}:"
            f"{target_id}:{float(target_lat):.8f}:{float(target_lon):.8f}:"
            f"{float(max_distance_km):.6f}"
        ).encode()
    ).hexdigest()
    return {
        "target_id": target_id,
        "claim": "location_within_distance",
        "max_distance_km": float(max_distance_km),
        "target_policy_hash": target_policy_hash,
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
