from __future__ import annotations

import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
import store
from tasks.queue import enqueue_report


def process_schedule(schedule: dict, sync: bool = False):
    """Claim a due schedule, then enqueue its work to the background queue or process synchronously."""
    user_key = schedule.get('user_key')
    if not user_key:
        return

    user = store.get_user(user_key) or {'user_key': user_key, 'line_user_id': user_key}
    items = store.list_watchlist(user_key)
    if not items:
        print(f"[Dispatcher] User {user_key} has empty watchlist. Skipping.")
        return

    store.upsert_schedule(user_key, last_run=_now_utc())

    payload_items = [
        {
            'symbol': item.get('symbol') or item.get('id'),
            'strategy': item.get('strategy'),
            'goal': item.get('goal'),
            'risk': item.get('risk'),
            'report_format': item.get('report_format'),
        }
        for item in {item.get('symbol') or item.get('id'): item for item in items if (item.get('symbol') or item.get('id'))}.values()
    ]
    settings = {
        'core_strategy': user.get('core_strategy'),
        'investment_goal': user.get('investment_goal'),
        'risk_appetite': user.get('risk_appetite'),
        'report_format': user.get('report_format'),
    }
    enqueue_report(user_key, user.get('line_user_id') or user_key, payload_items, settings, sync=sync)


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def check_jobs(target_time: str | None = None, force: bool = False, sync: bool = True) -> int:
    """Scan store for active schedules due at the current hour.
    When sync=True, jobs are executed in-line to guarantee completion in serverless environments."""
    import pytz

    tz = pytz.timezone(getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    now = datetime.datetime.now(tz)
    current_time = target_time or now.strftime('%H:00')
    print(f"[Dispatcher] Checking scheduled jobs for target time {current_time} (now: {now.strftime('%Y-%m-%d %H:%M:%S %Z')})")

    try:
        schedules = store.list_active_schedules(current_time)
    except Exception as exc:
        print(f"[Dispatcher] Error querying schedules: {exc}")
        return 0

    processed_count = 0
    for schedule in schedules:
        user_key = schedule.get('user_key')
        last_run = schedule.get('last_run')
        # Skip if already ran within this hour (converting to local timezone for accurate hour match)
        if not force and last_run is not None:
            try:
                if getattr(last_run, 'tzinfo', None) is not None:
                    last_local = last_run.astimezone(tz)
                else:
                    last_local = pytz.utc.localize(last_run).astimezone(tz)
                if last_local.date() == now.date() and last_local.hour == now.hour:
                    print(f"[Dispatcher] User {user_key} already ran at {last_local.strftime('%Y-%m-%d %H:%M')}. Skipping.")
                    continue
            except Exception as e:
                print(f"[Dispatcher] Warning: unable to parse last_run {last_run}: {e}")

        try:
            print(f"[Dispatcher] Processing schedule for user {user_key} (sync={sync})")
            process_schedule(schedule, sync=sync)
            processed_count += 1
        except Exception as exc:
            print(f"[Dispatcher] Error processing schedule for user {user_key}: {exc}")

    return processed_count


def start_scheduler():
    """Start blocking scheduler process."""
    scheduler = BlockingScheduler(timezone=getattr(Config, 'SCHEDULER_TIMEZONE', 'Asia/Bangkok'))
    scheduler.add_job(check_jobs, 'cron', minute=0)
    scheduler.add_job(store.prune_global_stock_info, 'cron', hour=3, minute=0, kwargs={'max_age_hours': 24})
    print("[Dispatcher] Scheduler started.")
    scheduler.start()


if __name__ == '__main__':
    start_scheduler()
