"""Windowless launcher for the local web panel at Windows user sign-in."""

import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

log_path = PROJECT_ROOT / "runtime" / "logs" / "panel.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8", buffering=1) as output:
    sys.stdout = output
    sys.stderr = output
    try:
        from zapret2_webcontrol.server import run

        run()
    except Exception:
        traceback.print_exc(file=output)
