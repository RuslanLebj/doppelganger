import json
import os
import stat
import sys
from pathlib import Path
from threading import Event

import pytest
from conftest import TEST_PASSWORD

from app.application.services.backups import BackupExecutor
from app.infrastructure.backup.process import CommandError, base_environment, run_command
from app.infrastructure.db.models import BackupRun


def executable(path: Path, body: str):
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return str(path)


@pytest.fixture
def fake_dump(settings, tmp_path):
    record = tmp_path / "calls.jsonl"
    settings.PG_DUMP_COMMAND = executable(
        tmp_path / "pg_dump",
        f"""
import json, os, pathlib, stat, sys
password_path = pathlib.Path(os.environ["PGPASSFILE"])
assert stat.S_IMODE(password_path.stat().st_mode) == 0o600
assert "PGPASSWORD" not in os.environ
assert all("--jobs" not in arg for arg in sys.argv)
with open({str(record)!r}, "a") as log:
    log.write(json.dumps({{"argv": sys.argv, "pgpass": str(password_path)}}) + "\\n")
output = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--file="))
pathlib.Path(output).write_bytes(b"fake database dump")
""",
    )
    return record


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.fail_upload = False
        self.fail_promote = False
        self.promotions = []

    def upload(self, path, key):
        if self.fail_upload:
            self.fail_upload = False
            raise CommandError("Upload failed")
        self.objects[key] = path.read_bytes()

    def promote(self, source_key, latest_key):
        if self.fail_promote:
            self.fail_promote = False
            raise CommandError("Copy failed")
        self.objects[latest_key] = self.objects[source_key]
        self.promotions.append(source_key)


@pytest.fixture
def executor(settings, sessions):
    executor = BackupExecutor(settings, sessions, Event())
    executor.storage = FakeStorage()
    return executor


def queued_run(sessions, plan):
    with sessions.begin() as session:
        run = BackupRun(plan_id=plan.id)
        session.add(run)
    return run.id


def test_upload_failure_keeps_private_staging_for_retry(
    settings,
    sessions,
    source,
    fake_dump,
    client,
    executor,
    caplog,
):
    executor.storage.fail_upload = True
    run_id = queued_run(sessions, source[1])
    executor.execute_next()
    with sessions() as session:
        run = session.get(BackupRun, run_id)
        assert run.s3_status == "failed"
        path = settings.DATA_DIR / run.dump_path
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert client.post(f"/api/v1/runs/{run_id}/retry-s3").status_code == 202
    executor.execute_next()
    assert len(fake_dump.read_text().splitlines()) == 1
    calls = [json.loads(line) for line in fake_dump.read_text().splitlines()]
    assert not Path(calls[0]["pgpass"]).exists()
    assert TEST_PASSWORD not in fake_dump.read_text() + caplog.text
    assert not path.exists()
    with sessions() as session:
        assert session.get(BackupRun, run_id).status == "success"


def test_retry_of_old_run_cannot_replace_newer_latest(
    settings,
    sessions,
    source,
    fake_dump,
    client,
    executor,
):
    executor.storage.fail_promote = True
    old_id = queued_run(sessions, source[1])
    executor.execute_next()
    new_id = queued_run(sessions, source[1])
    executor.execute_next()
    assert client.post(f"/api/v1/runs/{old_id}/retry-s3").status_code == 202
    executor.execute_next()
    assert executor.storage.promotions == [executor._key(source[0].id, new_id)]
    assert len(fake_dump.read_text().splitlines()) == 2


def test_failed_dump_is_not_published(settings, sessions, source, tmp_path, executor):
    settings.PG_DUMP_COMMAND = executable(
        tmp_path / "bad-dump",
        f"""
import pathlib, sys
output = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--file="))
pathlib.Path(output).write_bytes(b"incomplete")
print({TEST_PASSWORD!r}, file=sys.stderr)
sys.exit(2)
""",
    )
    run_id = queued_run(sessions, source[1])
    executor.execute_next()
    with sessions() as session:
        run = session.get(BackupRun, run_id)
        assert (run.status, run.dump_path, run.s3_status) == (
            "failed",
            None,
            "not_started",
        )
        assert TEST_PASSWORD not in run.error
    assert executor.storage.objects == {}
    assert not list(settings.DATA_DIR.rglob("*.partial"))
    assert not list(settings.DATA_DIR.rglob("*.dump"))


def test_backup_preserves_history_and_latest(
    settings, sessions, source, fake_dump, executor
):
    ids = []
    for _ in range(2):
        ids.append(queued_run(sessions, source[1]))
        executor.execute_next()
    for run_id in ids:
        with sessions() as session:
            run = session.get(BackupRun, run_id)
            assert (run.status, run.s3_status) == (
                "success",
                "success",
            )
            assert run.dump_path is None
            assert executor.storage.objects[run.s3_key] == b"fake database dump"
    assert executor._latest_key(source[0].id) in executor.storage.objects
    assert not list(settings.BACKUPS_DIR.rglob("*.dump"))


def test_failure_of_new_backup_keeps_previous_latest(
    settings, sessions, source, fake_dump, executor
):
    first_id = queued_run(sessions, source[1])
    executor.execute_next()
    latest = executor._latest_key(source[0].id)
    previous = executor.storage.objects[latest]
    executor.storage.fail_upload = True
    queued_run(sessions, source[1])
    executor.execute_next()
    assert executor.storage.objects[latest] == previous
    assert executor.storage.promotions == [executor._key(source[0].id, first_id)]


def test_restart_marks_running_job_interrupted(settings, sessions, source, executor):
    run_id = queued_run(sessions, source[1])
    with sessions.begin() as session:
        run = session.get(BackupRun, run_id)
        run.status = "running"
        run.s3_status = "running"
    executor.recover_interrupted()
    with sessions() as session:
        run = session.get(BackupRun, run_id)
        assert (run.status, run.s3_status) == ("interrupted", "interrupted")


def test_timeout_stops_the_process(tmp_path):
    pid_file = tmp_path / "pid"
    program = executable(
        tmp_path / "slow",
        f"""
import os, pathlib, time
pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
time.sleep(30)
""",
    )
    with pytest.raises(CommandError, match="time limit"):
        run_command(
            [program], env=base_environment(), timeout=1, stop=Event(), work_dir=tmp_path
        )
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_missing_staged_dump_rejects_retry_without_redump(
    settings, sessions, source, fake_dump, client, executor
):
    executor.storage.fail_upload = True
    run_id = queued_run(sessions, source[1])
    executor.execute_next()
    with sessions() as session:
        path = settings.DATA_DIR / session.get(BackupRun, run_id).dump_path
    path.unlink()
    assert client.post(f"/api/v1/runs/{run_id}/retry-s3").status_code == 409
    assert len(fake_dump.read_text().splitlines()) == 1
