#!/usr/bin/env python3
"""
Compat shim for environments/scripts that invoke `OCI-Master-Tool.py`.
Delegates to OCI_Master.py:main(), where the real CLI lives.
"""
from __future__ import annotations

import sys

# Ensure local import works when executed from repo root
try:
    from OCI_Master import main as _main
except Exception as e:  # pragma: no cover
    # Fallback: add current directory to path and retry
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from OCI_Master import main as _main  # type: ignore

if __name__ == "__main__":
    _main()
