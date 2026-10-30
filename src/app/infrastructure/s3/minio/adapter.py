import time
from contextlib import closing
from pathlib import Path
from threading import Event

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from app.infrastructure.backup.process import CommandError, WorkerShutdown
from config import Settings


def open_client(settings: Settings):
    if settings.S3_SECRET_KEY is None or not settings.S3_SECRET_KEY.get_secret_value():
        raise ValueError("S3_SECRET_KEY is required")
    return closing(
        boto3.client(
            "s3",
            endpoint_url=str(settings.S3_ENDPOINT),
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY.get_secret_value(),
            config=Config(
                connect_timeout=min(10, settings.STORAGE_TIMEOUT_SECONDS),
                read_timeout=min(60, settings.STORAGE_TIMEOUT_SECONDS),
                retries={"mode": "standard", "total_max_attempts": 3},
                s3={"addressing_style": "path"},
            ),
        )
    )


class S3Storage:
    def __init__(self, settings: Settings, stop: Event):
        self.settings = settings
        self.stop = stop
        self.transfer_config = TransferConfig(
            multipart_threshold=64 * 1024**2,
            multipart_chunksize=64 * 1024**2,
            max_concurrency=1,
            use_threads=False,
        )

    def _transfer(self, operation: str, source: Path | str, key: str):
        deadline = time.monotonic() + self.settings.STORAGE_TIMEOUT_SECONDS

        def check_transfer(_=0):
            if self.stop.is_set():
                raise WorkerShutdown()
            if time.monotonic() >= deadline:
                raise CommandError("S3 transfer exceeded its time limit")

        check_transfer()
        try:
            with open_client(self.settings) as client:
                options = {"Config": self.transfer_config, "Callback": check_transfer}
                if operation == "upload":
                    client.upload_file(
                        str(source), self.settings.S3_BUCKET, key, **options
                    )
                else:
                    client.copy(
                        {"Bucket": self.settings.S3_BUCKET, "Key": source},
                        self.settings.S3_BUCKET,
                        key,
                        **options,
                    )
            check_transfer()
        except CommandError, WorkerShutdown:
            raise
        except Exception:
            # Preserve cancellation even if the SDK wraps a callback exception.
            check_transfer()
            raise CommandError(
                f"S3 {operation} failed; check storage availability and credentials"
            ) from None

    def upload(self, path: Path, key: str):
        self._transfer("upload", path, key)

    def promote(self, source_key: str, latest_key: str):
        self._transfer("copy", source_key, latest_key)


RULE_ID = "doppelganger-expiration"


def initialize(settings: Settings):
    with open_client(settings) as client:
        try:
            client.head_bucket(Bucket=settings.S3_BUCKET)
        except ClientError as error:
            if str(error.response["Error"]["Code"]) not in {
                "404",
                "NoSuchBucket",
                "NotFound",
            }:
                raise
            options = (
                {}
                if settings.S3_REGION == "us-east-1"
                else {
                    "CreateBucketConfiguration": {
                        "LocationConstraint": settings.S3_REGION
                    },
                }
            )
            client.create_bucket(Bucket=settings.S3_BUCKET, **options)
        try:
            rules = client.get_bucket_lifecycle_configuration(Bucket=settings.S3_BUCKET)[
                "Rules"
            ]
        except ClientError as error:
            if error.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
                raise
            rules = []
        previous = list(rules)
        rules = [rule for rule in rules if rule.get("ID") != RULE_ID]
        latest_prefix = (
            "/".join(part for part in [settings.S3_PREFIX.strip("/"), "latest"] if part)
            + "/"
        )
        for rule in rules:
            if rule.get("Status") != "Enabled" or "Expiration" not in rule:
                continue
            filter_ = rule.get("Filter", {})
            prefix = filter_.get(
                "Prefix", filter_.get("And", {}).get("Prefix", rule.get("Prefix", ""))
            )
            if latest_prefix.startswith(prefix) or prefix.startswith(latest_prefix):
                raise ValueError("An existing expiration rule can delete latest backups")
        if client.get_bucket_versioning(Bucket=settings.S3_BUCKET).get("Status") in {
            "Enabled",
            "Suspended",
        }:
            raise ValueError("Use an unversioned bucket for this expiration policy")
        if settings.RETENTION_DAYS:
            prefix = "/".join(
                part for part in [settings.S3_PREFIX.strip("/"), "history"] if part
            )
            rules.append(
                {
                    "ID": RULE_ID,
                    "Status": "Enabled",
                    "Filter": {"Prefix": prefix + "/"},
                    "Expiration": {"Days": settings.RETENTION_DAYS},
                }
            )
        if rules:
            client.put_bucket_lifecycle_configuration(
                Bucket=settings.S3_BUCKET, LifecycleConfiguration={"Rules": rules}
            )
        elif previous:
            client.delete_bucket_lifecycle(Bucket=settings.S3_BUCKET)
