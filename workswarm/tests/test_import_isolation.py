"""The demo test process must import its app, never AgentShield's app package."""

import subprocess
import sys
from pathlib import Path

from workswarm.config import DEMO_TARGET, REPO_ROOT


def test_demo_target_app_package_wins_in_the_demo_working_directory() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import app; print(Path(app.__file__).resolve())",
        ],
        cwd=DEMO_TARGET,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
    imported = Path(probe.stdout.strip()).resolve()
    assert imported == (DEMO_TARGET / "app" / "__init__.py").resolve()
    assert imported != (REPO_ROOT / "backend" / "app" / "__init__.py").resolve()
