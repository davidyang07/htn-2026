"""These tests cover the half of the bridge that does not need the WorkSwarm
engine: the fail-closed HTTP client, the sandbox write guard, the pytest
runner's output parsing, and the instruction-follower.

That split is deliberate. It means the demo's security-relevant bridge
behaviour is verifiable with the backend's own venv (`httpx` + `pytest`), in
CI, without installing WorkSwarm -- while `workswarm/workers.py` and
`workswarm/flows/` are exercised by actually running the demo.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
