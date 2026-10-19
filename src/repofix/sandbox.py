import os
import subprocess
import uuid
from pathlib import Path
from .process import execute


class DockerRunner:
    def __init__(self, workspace, image="python:3.11-slim", verification=None):
        self.workspace = Path(workspace).resolve()
        self.image = image
        self.verification = Path(verification).resolve() if verification else None

    @staticmethod
    def check(image=None):
        result = execute(["docker", "info"], timeout=10)
        if result["exit_code"]:
            raise RuntimeError("Docker daemon unavailable. Start Docker Desktop first.")
        if image:
            result = execute(["docker", "image", "inspect", image], timeout=10)
            if result["exit_code"]:
                raise RuntimeError(
                    f"Docker image unavailable locally: {image}. Pull or build it before running tasks."
                )

    def run(self, command, timeout=30):
        name = "repofix-" + uuid.uuid4().hex
        argv = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=512m",
            "--cpus=1",
            "--ulimit",
            "fsize=32768:32768",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "--workdir",
            "/workspace",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace",
        ]
        gitdir = self.workspace / ".git"
        if gitdir.exists():
            argv += ["--mount", f"type=bind,src={gitdir},dst=/workspace/.git,readonly"]
        if self.verification:
            argv += [
                "--mount",
                f"type=bind,src={self.verification},dst=/verification,readonly",
            ]
        argv += [self.image, "sh", "-lc", command]
        try:
            return execute(argv, timeout=timeout)
        finally:
            # A timed-out Docker CLI does not necessarily stop its container.
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
