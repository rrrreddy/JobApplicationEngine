"""A single-worker in-process queue that all post-processing funnels
through: the poll loop and backfill both enqueue raw posts here instead
of calling the pipeline directly. One worker processes them strictly one
at a time, which removes the concurrent-writer contention that came from
multiple sources hitting the database and Groq/SMTP at once, and makes
rate-limit pacing trivial (the worker just paces itself between items).
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app import pipeline

logger = logging.getLogger(__name__)

OnPending = Callable[[int], Awaitable[None]]


@dataclass
class RawPost:
    channel_label: str
    message_id: int
    text: str


class JobQueue:
    def __init__(self, on_pending: OnPending, pace_seconds: float = 1.0):
        self._queue: "asyncio.Queue[RawPost]" = asyncio.Queue()
        self._on_pending = on_pending
        self._pace_seconds = pace_seconds

    async def put(self, channel_label: str, message_id: int, text: str):
        await self._queue.put(RawPost(channel_label, message_id, text))

    def qsize(self) -> int:
        return self._queue.qsize()

    async def run_worker(self):
        """Runs forever, processing one post at a time."""
        loop = asyncio.get_running_loop()
        while True:
            post = await self._queue.get()
            try:
                result = await loop.run_in_executor(
                    None, pipeline.process_post, post.channel_label, post.message_id, post.text
                )
                logger.info(
                    "Processed post from %s -> %s (%s)", post.channel_label, result.status, result.detail
                )
                if result.status == "pending" and result.job_id is not None:
                    await self._on_pending(result.job_id)
            except Exception:
                logger.exception("Unexpected error processing post from %s", post.channel_label)
            finally:
                self._queue.task_done()
            if self._pace_seconds > 0:
                await asyncio.sleep(self._pace_seconds)
