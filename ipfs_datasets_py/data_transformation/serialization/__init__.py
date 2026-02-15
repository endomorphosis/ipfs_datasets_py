"""
Data serialization utilities for IPFS Datasets.

This package contains utilities for converting between different data formats
and serialization protocols used in IPFS dataset management.

Components:
    - car_conversion: Convert data to/from CAR (Content Addressable aRchive) format
    - jsonl_to_parquet: Convert JSONL files to Parquet format
    - dataset_serialization: General dataset serialization utilities
    - ipfs_parquet_to_car: Convert Parquet files to CAR format for IPFS storage
"""

from ipfs_datasets_py.data_transformation.serialization.car_conversion import *
from ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet import *
from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import *
from ipfs_datasets_py.data_transformation.serialization.ipfs_parquet_to_car import *

__all__ = [
    # car_conversion exports
    "DataInterchangeUtils",
    # jsonl_to_parquet exports  
    "JSONLToParquetConverter",
    # dataset_serialization exports
    "DatasetSerializer",
    # ipfs_parquet_to_car exports
    "ParquetToCarConverter",
]
