from __future__ import annotations

import subprocess
from pathlib import Path


def file_last_commit(project_root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(rel)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()[:12]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return ""
