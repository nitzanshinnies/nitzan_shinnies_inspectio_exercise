"""Dedicated S3 persistence service boundary (HTTP surface skeleton)."""

from .local_s3 import LocalS3Provider
from .memory_s3 import MemoryLocalS3Provider

__all__ = ["LocalS3Provider", "MemoryLocalS3Provider"]
