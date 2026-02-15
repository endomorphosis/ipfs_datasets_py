"""
Geospatial domain processors for geographic and spatial data analysis.
"""

# Try to import geospatial modules, make them optional for missing dependencies
try:
    from .geospatial_analysis import *
except ImportError as e:
    import warnings
    warnings.warn(f"GeospatialAnalysis unavailable due to missing dependencies: {e}")

__all__ = ['GeospatialAnalysis', 'GeospatialProcessor']
