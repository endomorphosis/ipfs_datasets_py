"""
Serialization module for IPFS Datasets Python.

This module provides utilities for converting between different data formats,
including IPFS CAR files, Parquet, JSONL, and Hugging Face datasets.

Migrated from data_transformation.serialization in v2.0.0 migration.

Main Components:
    - car_conversion: Convert datasets to/from CAR (Content Addressable aRchive) format
    - dataset_serialization: Serialize Hugging Face datasets to IPFS
    - ipfs_parquet_to_car: Convert Parquet files to CAR format  
    - jsonl_to_parquet: Convert JSONL files to Parquet format
"""

from .car_conversion import *
from .jsonl_to_parquet import *
from .dataset_serialization import *
from .ipfs_parquet_to_car import *

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
