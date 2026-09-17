"""Schedule dispatcher. Report execution lives in tasks.worker."""

import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
from database import Schedule, SessionLocal, User, Watchlist
from init_cache_db import GlobalStockInfo
from tasks import enqueue_report


def prune_cache():
    db = SessionLocal()
    try:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        db.query(GlobalStockInfo).filter(GlobalStockInfo.updated_at < cutoff).delete()
        db.commit()
    finally:
        db.close()


def process_schedule(schedule_id):
    """Claim a due schedule, then enqueue its work outside this dispatcher."""
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
            {'symbol': item.symbol, 'strategy': item.strategy, 'goal': item.goal, 'risk': item.risk, 'report_format': item.report_format}
            for item in {item.symbol: item for item in items}.values()
        ]
        settings = {
            'core_strategy': user.core_strategy,
            'investment_goal': user.investment_goal,
            'risk_appetite': user.risk_appetite,
            'report_format': user.report_format,
        }
        enqueue_report(user.id, user.line_user_id, payload_items, settings)
    finally:
        db.close()


def check_jobs():
    import pytz

    now = datetime.datetime.now(pytz.timezone(Config.SCHEDULER_TIMEZONE))
    current_time = now.strftime('%H:00')
    db = SessionLocal()
    try:
        schedules = db.query(Schedule).filter(Schedule.is_active == True, Schedule.alert_time == current_time).all()
        due_ids = [
            schedule.id for schedule in schedules
            if not schedule.last_run or schedule.last_run.date() != now.date() or schedule.last_run.hour != now.hour
        ]
    finally:
        db.close()
    for schedule_id in due_ids:
        process_schedule(schedule_id)


if __name__ == '__main__':
    scheduler = BlockingScheduler(timezone=Config.SCHEDULER_TIMEZONE)
    scheduler.add_job(check_jobs, 'cron', minute=0)
    scheduler.add_job(prune_cache, 'cron', hour=3, minute=0)
    scheduler.start()
