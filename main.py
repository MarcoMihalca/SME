#!/usr/bin/env python3
"""
Entry-point principal pentru monitorizarea prin USB (Modbus RTU) a echipamentelor:
  - Disjunctor Eaton NZMH4-PX1600-TAZ (unitate electronică PXR25)
  - Modul interfață/stare Eaton NZM4-XBSM-TAZ-N
"""

from __future__ import annotations

import os
import sys

# Adăugăm directorul `src` în sys.path pentru importul pachetului `eaton_pxr`
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from eaton_pxr.cli import run_cli


if __name__ == "__main__":
    sys.exit(run_cli())
