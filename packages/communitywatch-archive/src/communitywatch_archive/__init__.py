"""Offline sealed-history archive tool for the detect-only observer.

The package is import-safe without DuckDB/PyArrow installed: this module
re-exports only the stdlib-only layout primitives.  The heavy backends are
imported explicitly via ``communitywatch_archive.export`` (PyArrow),
``communitywatch_archive.cold`` (DuckDB), ``communitywatch_archive.gates``,
``communitywatch_archive.lifecycle``, and ``communitywatch_archive.cli``.
"""

from .layout import ArtifactRoot, read_pointer, validate_generation_id

__all__ = [
    "ArtifactRoot",
    "read_pointer",
    "validate_generation_id",
]
__version__ = "0.1.0"
