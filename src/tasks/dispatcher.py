from __future__ import annotations

import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
from database import Schedule, SessionLocal, User, Watchlist
from init_cache_db import GlobalStockInfo
from tasks.queue import enqueue_report


def prune_cache():
    db = SessionLocal()
    try:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        db.query(GlobalStockInfo).filter(GlobalStockInfo.updated_at < cutoff).delete()
        db.commit()
    except Exception as exc:
        print(f"[Dispatcher] Cache pruning error: {exc}")
    finally:
        db.close()


def process_schedule(schedule_id: int):
    """Claim a due schedule, then enqueue its work to the background queue."""
    db = SessionLocal()
    try:
        schedule = db.query(Schedule).filter(Schedule.id == schedule_id, Schedule.is_active == True).first()
        if not schedule:
            return
        user = db.query(User).filter(User.id == schedule.user_id).first()
        if not user:
            return
        items = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()
        if not items:
            return

        schedule.last_run = datetime.datetime.utcnow()
        db.commit()

        payload_items = [
            {
                'symbol': item.symbol,
                'strategy': item.strategy,
                'goal': item.goal,
                'risk': item.risk,
                'report_format': item.report_format,
            }
            for item in {item.symbol: item for item in items}.values()
        ]
        settings = {
            'core_strategy': user.core_strategy,
            'investment_goal': user.investment_goal,
            'risk_appetite': user.risk_appetite,
            'report_format': user.report_format,
        }
        enqueue_report(user.id, user.line_user_id, payload_items, settings)
    except Exception as exc:
        print(f"[Dispatcher] Error processing schedule {schedule_id}: {exc}")
    finally:
        db.close()


def check_jobs():
    """Scan database for active schedules due at the current hour."""
    import pytz

    tz = pytz.timezone(getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    now = datetime.datetime.now(tz)
    current_time = now.strftime('%H:00')

    db = SessionLocal()
    due_ids = []
    try:
        schedules = db.query(Schedule).filter(Schedule.is_active == True, Schedule.alert_time == current_time).all()
        due_ids = [
            schedule.id
            for schedule in schedules
            if not schedule.last_run
            or schedule.last_run.date() != now.date()
            or schedule.last_run.hour != now.hour
        ]
    except Exception as exc:
        print(f"[Dispatcher] Error querying schedules: {exc}")
    finally:
        db.close()

    for schedule_id in due_ids:
        process_schedule(schedule_id)


def start_scheduler():
    """Start blocking scheduler process."""
    scheduler = BlockingScheduler(timezone=getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    scheduler.add_job(check_jobs, 'cron', minute=0)
    scheduler.add_job(prune_cache, 'cron', hour=3, minute=0)
    print("[Dispatcher] Scheduler started.")
    scheduler.start()


if __name__ == '__main__':
    start_scheduler()
