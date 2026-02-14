"""Backward-compatibility shim — use normalizer.py instead."""
from normalizer import DocumentNormalizer as JefferiesNormalizer, detect_section_headers

__all__ = ['JefferiesNormalizer', 'detect_section_headers']
