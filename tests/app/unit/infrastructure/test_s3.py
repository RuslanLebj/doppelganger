from copy import deepcopy
from threading import Event

import pytest

from app.infrastructure.backup.process import CommandError, WorkerShutdown
from app.infrastructure.s3.minio import adapter as s3


def test_upload_and_large_copy_use_bounded_managed_transfer(
    settings, tmp_path, monkeypatch
):
    dump = tmp_path / "run.dump"
    dump.write_bytes(b"test dump")
    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def upload_file(self, *args, **kwargs):
            calls.append(("upload", args, kwargs))

        def copy(self, *args, **kwargs):
            calls.append(("copy", args, kwargs))

    monkeypatch.setattr(s3, "open_client", lambda _: Client())
    storage = s3.S3Storage(settings, Event())
    storage.upload(dump, "history/run.dump")
    storage.promote("history/run.dump", "latest/database.dump")
    assert calls[0][1] == (str(dump), settings.S3_BUCKET, "history/run.dump")
    assert calls[1][1][0] == {"Bucket": settings.S3_BUCKET, "Key": "history/run.dump"}
    assert all(call[2]["Config"].max_concurrency == 1 for call in calls)
    assert all(call[2]["Config"].use_threads is False for call in calls)


def test_missing_credentials_never_use_ambient_aws(settings, monkeypatch):
    settings.S3_SECRET_KEY = None

    def forbidden(*args, **kwargs):
        pytest.fail("No ambient credential lookup is allowed")

    monkeypatch.setattr(s3.boto3, "client", forbidden)
    with pytest.raises(ValueError, match="S3_SECRET_KEY is required"):
        s3.open_client(settings)


class LifecycleClient:
    def __init__(self, rules):
        self.rules = rules
        self.applied = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def head_bucket(self, **kwargs):
        pass

    def get_bucket_versioning(self, **kwargs):
        return {}

    def get_bucket_lifecycle_configuration(self, **kwargs):
        return {"Rules": deepcopy(self.rules)}

    def put_bucket_lifecycle_configuration(self, **kwargs):
        self.applied = kwargs["LifecycleConfiguration"]["Rules"]


def test_lifecycle_only_expires_history_and_preserves_other_rules(settings, monkeypatch):
    settings.RETENTION_DAYS = 14
    other = {
        "ID": "logs",
        "Status": "Enabled",
        "Filter": {"Prefix": "logs/"},
        "Expiration": {"Days": 2},
    }
    client = LifecycleClient([other])
    monkeypatch.setattr(s3, "open_client", lambda _: client)
    s3.initialize(settings)
    assert other in client.applied
    rule = next(rule for rule in client.applied if rule["ID"] == s3.RULE_ID)
    assert rule["Filter"] == {"Prefix": "postgres-backups/history/"}
    assert rule["Expiration"] == {"Days": 14}


def test_conflicting_expiration_of_latest_is_rejected(settings, monkeypatch):
    client = LifecycleClient(
        [
            {
                "ID": "everything",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": 1},
            }
        ]
    )
    monkeypatch.setattr(s3, "open_client", lambda _: client)
    with pytest.raises(ValueError, match="latest"):
        s3.initialize(settings)
    assert client.applied is None


def test_disabled_expiration_preserves_other_rules(settings, monkeypatch):
    settings.RETENTION_DAYS = None
    client = LifecycleClient(
        [
            {
                "ID": s3.RULE_ID,
                "Status": "Enabled",
                "Filter": {"Prefix": "postgres-backups/history/"},
                "Expiration": {"Days": 7},
            },
            {
                "ID": "other",
                "Status": "Enabled",
                "Filter": {"Prefix": "logs/"},
                "Expiration": {"Days": 2},
            },
        ]
    )
    monkeypatch.setattr(s3, "open_client", lambda _: client)
    s3.initialize(settings)
    assert not any(rule["ID"] == s3.RULE_ID for rule in client.applied)
    assert any(rule["ID"] == "other" for rule in client.applied)
    assert len(client.applied) == 1


@pytest.mark.parametrize("versioning", ["Enabled", "Suspended"])
def test_versioned_bucket_is_rejected(settings, monkeypatch, versioning):
    client = LifecycleClient([])
    client.get_bucket_versioning = lambda **kwargs: {"Status": versioning}
    monkeypatch.setattr(s3, "open_client", lambda _: client)
    with pytest.raises(ValueError, match="unversioned"):
        s3.initialize(settings)
    assert client.applied is None


def test_transfer_respects_cancellation_and_timeout(settings, tmp_path, monkeypatch):
    stop = Event()

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def upload_file(self, *args, Callback, **kwargs):
            stop.set()
            Callback(1)

    monkeypatch.setattr(s3, "open_client", lambda _: Client())
    storage = s3.S3Storage(settings, stop)
    with pytest.raises(WorkerShutdown):
        storage.upload(tmp_path / "dump", "history/run.dump")
    stop.clear()
    clock = iter([0, 0, 2])
    settings.STORAGE_TIMEOUT_SECONDS = 1
    from types import SimpleNamespace

    monkeypatch.setattr(s3, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    class SlowClient(Client):
        def upload_file(self, *args, Callback, **kwargs):
            Callback(1)

    monkeypatch.setattr(s3, "open_client", lambda _: SlowClient())
    with pytest.raises(CommandError, match="time limit"):
        storage.upload(tmp_path / "dump", "history/run.dump")


def test_sdk_client_is_closed_without_requiring_context_manager(settings, monkeypatch):
    class Client:
        closed = False

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(s3.boto3, "client", lambda *args, **kwargs: client)
    with s3.open_client(settings) as opened:
        assert opened is client
    assert client.closed
