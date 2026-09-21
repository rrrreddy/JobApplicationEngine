"""A single-worker in-process queue that all post-processing funnels
through: the poll loop and backfill enqueue job ids (already persisted to
the database via pipeline.enqueue_discovery, status='queued') instead of
processing them directly. One worker processes them strictly one at a
time, which removes the concurrent-writer contention that came from
multiple sources hitting the database and Groq/SMTP at once, and makes
rate-limit pacing trivial (the worker just paces itself between items).

Items are stored as job ids, not raw post content -- the post is already
durably in the database by the time it's queued, so a restart while
items are still waiting in this in-memory queue can't lose them; main.py
recovers anything still at status='queued' on startup and re-enqueues it.
"""
import asyncio
import logging
from typing import Awaitable, Callable

from app import pipeline

logger = logging.getLogger(__name__)

OnPending = Callable[[int], Awaitable[None]]

MAX_RATE_LIMIT_BACKOFF_SECONDS = 900  # cap a single backoff at 15 min


class JobQueue:
    def __init__(self, on_pending: OnPending, pace_seconds: float = 1.0):
        self._queue: "asyncio.Queue[int]" = asyncio.Queue()
        self._on_pending = on_pending
        self._pace_seconds = pace_seconds

    async def put(self, job_id: int):
        await self._queue.put(job_id)

    def qsize(self) -> int:
        return self._queue.qsize()

    async def run_worker(self):
        """Runs forever, processing one job at a time."""
        loop = asyncio.get_running_loop()
        while True:
            job_id = await self._queue.get()
            try:
                result = await loop.run_in_executor(None, pipeline.process_job, job_id)
                logger.info("Processed job %s -> %s (%s)", job_id, result.status, result.detail)

                if result.status == "pending" and result.job_id is not None:
                    await self._on_pending(result.job_id)

                if result.status == "rate_limited":
                    backoff = min(result.retry_after or MAX_RATE_LIMIT_BACKOFF_SECONDS, MAX_RATE_LIMIT_BACKOFF_SECONDS)
                    logger.warning(
                        "All Groq models rate-limited -- pausing the queue for %.0fs before continuing "
                        "(this job was marked failed and needs a future /backfill to retry)",
                        backoff,
                    )
                    self._queue.task_done()
                    await asyncio.sleep(backoff)
                    continue
            except Exception:
                logger.exception("Unexpected error processing job %s", job_id)

            self._queue.task_done()
            if self._pace_seconds > 0:
                await asyncio.sleep(self._pace_seconds)
