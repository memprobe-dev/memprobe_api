"""memprobe: a thin, local-first CLI for firmware memory budgets and size checks.

The binary is read on your machine; only commodity metadata (sections, symbols,
segments) is sent to the memprobe API for analysis. No analysis logic lives in
this package.
"""

__version__ = "0.1.0"
