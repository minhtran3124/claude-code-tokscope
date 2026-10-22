"""Static HTML report: the important numbers up front, everything else in expandable sections. Tokens first, USD second.

Layout: common (TOKENS), styles (CSS), scripts (page JS), widgets (HTML building blocks), sections/ (one module
per section) and writer (write_report)."""

from .writer import write_report

__all__ = ["write_report"]
