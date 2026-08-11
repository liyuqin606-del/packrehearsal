"""Zero-execution package ecosystem adapters."""

from .common import ManifestParseError
from .npm import NpmDiscovery, discover_npm_packages, parse_npm_manifest
from .python import (
    PythonDiscovery,
    canonical_python_name,
    discover_python_packages,
    parse_python_manifest,
)
from .rust import RustDiscovery, discover_rust_packages, parse_rust_manifest

__all__ = [
    "ManifestParseError",
    "NpmDiscovery",
    "PythonDiscovery",
    "RustDiscovery",
    "canonical_python_name",
    "discover_npm_packages",
    "discover_python_packages",
    "discover_rust_packages",
    "parse_npm_manifest",
    "parse_python_manifest",
    "parse_rust_manifest",
]
