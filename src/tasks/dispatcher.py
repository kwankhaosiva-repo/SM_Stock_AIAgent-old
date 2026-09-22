from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
import store
from tasks.queue import enqueue_report


def process_schedule(schedule: dict):
    """Claim a due schedule, then enqueue its work to the background queue."""
    user_key = schedule.get('user_key')
    if not user_key:
        return

    user = store.get_user(user_key)
    if not user:
        return
    items = store.list_watchlist(user_key)
    if not items:
        return

    store.upsert_schedule(user_key, last_run=_now_utc())

    payload_items = [
        {
            'symbol': item['symbol'],
            'strategy': item.get('strategy'),
            'goal': item.get('goal'),
            'risk': item.get('risk'),
            'report_format': item.get('report_format'),
        }
        for item in {item['symbol']: item for item in items}.values()
    ]
    settings = {
        'core_strategy': user.get('core_strategy'),
        'investment_goal': user.get('investment_goal'),
        'risk_appetite': user.get('risk_appetite'),
        'report_format': user.get('report_format'),
    }
    enqueue_report(user_key, user.get('line_user_id') or user_key, payload_items, settings)


def _now_utc():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc)


def check_jobs():
    """Scan store for active schedules due at the current hour."""
    import pytz

    tz = pytz.timezone(getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    now = datetime.datetime.now(tz)
    current_time = now.strftime('%H:00')

    try:
        schedules = store.list_active_schedules(current_time)
    except Exception as exc:
        print(f"[Dispatcher] Error querying schedules: {exc}")
        return

    for schedule in schedules:
        last_run = schedule.get('last_run')
        # Skip if already ran within this hour (Firestore stores tz-aware datetimes)
        if last_run is not None:
            last_naive = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
            if last_naive.date() == now.date() and last_naive.hour == now.hour:
                continue
        try:
            process_schedule(schedule)
        except Exception as exc:
            print(f"[Dispatcher] Error processing schedule: {exc}")


def start_scheduler():
    """Start blocking scheduler process."""
    scheduler = BlockingScheduler(timezone=getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    scheduler.add_job(check_jobs, 'cron', minute=0)
    scheduler.add_job(store.prune_global_stock_info, 'cron', hour=3, minute=0, kwargs={'max_age_hours': 24})
    print("[Dispatcher] Scheduler started.")
    scheduler.start()


if __name__ == '__main__':
    start_scheduler()
