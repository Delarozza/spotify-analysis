"""Optional APScheduler job: daily listening snapshot into PostgreSQL."""

from __future__ import annotations

import atexit
import logging
import os
from typing import TYPE_CHECKING

from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)

_scheduler = None


def _parse_hh_mm(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {value!r}")
    return int(parts[0]), int(parts[1])


def init_listening_snapshot_scheduler(app: Flask) -> None:
    """Start background cron if DATABASE_URL and LISTENING_SNAPSHOT_TZ are set."""
    global _scheduler
    if _scheduler is not None:
        return
    if not os.environ.get("DATABASE_URL"):
        logger.info("Listening snapshot scheduler: DATABASE_URL not set, skipped")
        return
    tz_name = (os.environ.get("LISTENING_SNAPSHOT_TZ") or "").strip()
    if not tz_name:
        logger.info("Listening snapshot scheduler: LISTENING_SNAPSHOT_TZ not set, skipped")
        return
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        logger.warning("Listening snapshot scheduler: invalid LISTENING_SNAPSHOT_TZ=%r (%s)", tz_name, e)
        return
    try:
        hour, minute = _parse_hh_mm(os.environ.get("LISTENING_SNAPSHOT_AT", "00:05"))
    except Exception as e:
        logger.warning("Listening snapshot scheduler: bad LISTENING_SNAPSHOT_AT (%s)", e)
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "Listening snapshot scheduler: apscheduler not installed "
            "(pip install apscheduler) — use CLI or cron instead."
        )
        return

    def job() -> None:
        with app.app_context():
            try:
                from db_storage import get_connection
                from listening_snapshots import run_scheduled_listening_snapshot
                from recent_history import get_spotify

                sp = get_spotify()
                with get_connection() as conn:
                    run_scheduled_listening_snapshot(sp, conn, tz)
            except Exception:
                logger.exception("Listening snapshot job failed")

    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(
        job,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="listening_daily_snapshot",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "Listening snapshot scheduler on (zone=%s, daily at %02d:%02d)",
        tz_name,
        hour,
        minute,
    )

    def _shutdown() -> None:
        global _scheduler
        if _scheduler:
            _scheduler.shutdown(wait=False)

    atexit.register(_shutdown)
