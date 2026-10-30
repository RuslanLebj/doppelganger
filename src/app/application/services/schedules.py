from datetime import UTC, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.models import BackupPlan, BackupRun


def next_fire(cron: str, timezone: str, after: datetime) -> datetime:
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    trigger = CronTrigger.from_crontab(cron, timezone=timezone)
    result = trigger.get_next_fire_time(None, after + timedelta(microseconds=1))
    if result is None:
        raise ValueError("Schedule has no next run")
    return result.astimezone(UTC).replace(tzinfo=None)


def enqueue_due(session_factory, now: datetime) -> int:
    """Persist the next due time, coalescing missed nights into a single run."""
    count = 0
    with session_factory.begin() as session:
        plans = session.scalars(
            select(BackupPlan).where(
                BackupPlan.enabled.is_(True),
                BackupPlan.next_run_at <= now,
            )
        ).all()
        for plan in plans:
            try:
                with session.begin_nested():
                    session.add(BackupRun(plan_id=plan.id, trigger="schedule"))
                    session.flush()
                count += 1
            except IntegrityError:
                # An earlier run of this plan is still queued or running.
                pass
            plan.next_run_at = next_fire(plan.cron, plan.timezone, now)
    return count
