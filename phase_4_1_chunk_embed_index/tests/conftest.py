import sys
from pathlib import Path

PHASE_ROOT = Path(__file__).resolve().parent.parent
if str(PHASE_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE_ROOT))
