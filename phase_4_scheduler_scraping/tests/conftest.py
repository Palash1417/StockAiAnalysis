import sys
from pathlib import Path

# Make the phase root importable for tests (scraping_service.* and scheduler.*).
PHASE_ROOT = Path(__file__).resolve().parent.parent
if str(PHASE_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE_ROOT))
