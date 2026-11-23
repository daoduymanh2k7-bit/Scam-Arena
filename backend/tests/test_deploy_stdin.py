"""Docker must not consume the rest of a deploy script piped through SSH."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


def test_docker_exec_cannot_drain_remote_shell_script():
    if os.name == "nt":
        import pytest
        pytest.skip("POSIX shell regression; also verified in Linux Docker")
    source = (Path(__file__).resolve().parents[2] / "deployment/deploy-vps.sh").read_text()
    commands = [line.strip() for line in source.splitlines() if line.strip().startswith("docker compose -p scam-arena exec -T")]
    assert len(commands) >= 2
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fake = root / "docker"
        fake.write_text("#!/bin/sh\ncat >/dev/null\nprintf 'mock-command-finished\\n'\n")
        fake.chmod(0o755)
        script = "set -eu\nbackup=" + shlex.quote(str(root / "backup")) + "\n"
        script += "\n".join(commands) + "\nprintf 'DEPLOY_REACHED_END\\n'\n"
        result = subprocess.run(["bash", "-s"], input=script, text=True, capture_output=True,
                                env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}, timeout=5)
        assert result.returncode == 0, result.stderr
        assert "DEPLOY_REACHED_END" in result.stdout
