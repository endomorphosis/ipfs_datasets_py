# Geospatial Tools

MCP thin wrapper for geographic data processing and spatial analysis. Business logic lives in
`ipfs_datasets_py.processors.geospatial_analysis`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `geospatial_tools.py` | `geocode_address()`, `reverse_geocode()`, `calculate_distance()`, `spatial_query()`, `get_map_data()` | Geocoding, distance calculation, spatial queries, map data retrieval |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.geospatial_tools import (
    geocode_address, calculate_distance, spatial_query
)

# Geocode an address
location = await geocode_address(
    address="1600 Pennsylvania Ave NW, Washington DC"
)
# Returns: {"lat": 38.8977, "lon": -77.0366, "formatted": "...", "confidence": 0.98}

# Distance between two points
dist = await calculate_distance(
    from_coords={"lat": 40.7128, "lon": -74.0060},  # New York
    to_coords={"lat": 34.0522, "lon": -118.2437},   # Los Angeles
    unit="km"
)
# Returns: {"distance": 3944.8, "unit": "km"}

# Spatial query — find points of interest within radius
pois = await spatial_query(
    center={"lat": 40.7128, "lon": -74.0060},
    radius_km=5,
    category="hospital"
)
```

## Core Module

- `ipfs_datasets_py.processors.geospatial_analysis` — all business logic

## Dependencies

- `geopy` — geocoding (optional; multiple provider backends)
- `shapely` — spatial operations (optional)
- `geopandas` — GeoDataFrame support (optional)

## Status

| Tool | Status |
|------|--------|
| `geospatial_tools` | ✅ Production ready |
