"""Runner entrypoint for background worker or scheduler."""

import sys
from tasks.dispatcher import check_jobs, process_schedule, prune_cache, start_scheduler


def run_rq_worker():
    from config import Config
    from redis import Redis
    from rq import Connection, Worker

    if not Config.REDIS_URL:
        print("[Worker] REDIS_URL not configured. Cannot run standalone RQ worker.")
        return

    redis_conn = Redis.from_url(Config.REDIS_URL)
    with Connection(redis_conn):
        worker = Worker([Config.QUEUE_NAME])
        print(f"[Worker] Starting RQ worker on queue '{Config.QUEUE_NAME}'...")
        worker.work()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'rq':
        run_rq_worker()
    else:
        start_scheduler()
