"""
Domain-specific processors for specialized data processing tasks.

This package contains domain-specific processors organized by field:
- patent: Patent data processing and scraping
- geospatial: Geographic and spatial data analysis
- ml: Machine learning and classification tools
"""

# Try to import domain modules, but make them optional
try:
    from . import patent
except ImportError:
    patent = None

try:
    from . import geospatial
except ImportError:
    geospatial = None

try:
    from . import ml
except ImportError:
    ml = None

__all__ = ['patent', 'geospatial', 'ml']
