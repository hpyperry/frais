"""Applications scanner plugin."""
from .discovery import read_application, scan_applications
from .plugin import ApplicationsPlugin
from .source_classifier import classify_source

__all__ = ["ApplicationsPlugin", "scan_applications", "read_application", "classify_source"]
