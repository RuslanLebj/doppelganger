import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from threading import Event


class CommandError(RuntimeError):
    """Only sanitized messages may be persisted or exposed over the API."""


class WorkerShutdown(Exception):
    pass


def stop_process(process: subprocess.Popen):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_command(
    args: list[str],
    *,
    env: dict[str, str],
    timeout: int,
    stop: Event,
    work_dir: Path,
    min_free_bytes: int = 0,
) -> None:
    """Run a cancellable command without exposing credentials in process output."""
    if stop.is_set():
        raise WorkerShutdown()
    work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        process = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        raise CommandError(
            "Executable could not be started; check installation and permissions"
        ) from None
    try:
        deadline = time.monotonic() + timeout
        while True:
            if stop.is_set():
                raise WorkerShutdown()
            if min_free_bytes and shutil.disk_usage(work_dir).free < min_free_bytes:
                raise CommandError("Stopped: local disk free-space reserve reached")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandError("Command exceeded its time limit")
            try:
                code = process.wait(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if code != 0:
            raise CommandError(
                f"Command failed with exit code {code}; raw stderr is not retained"
            )
    finally:
        stop_process(process)


def base_environment() -> dict[str, str]:
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
    return {key: os.environ[key] for key in allowed if key in os.environ}
