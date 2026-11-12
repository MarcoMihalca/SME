"""
Pachetul principal pentru monitorizarea disjunctorului Eaton NZMH4-PX1600-TAZ (PXR25)
și a modulului NZM4-XBSM-TAZ-N prin conexiune USB (Modbus RTU).
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

__version__ = "2.0.0"
