"""Entrypoint: runs the Telethon channel listener, the Telegram approval bot,
and the daily report scheduler concurrently in one asyncio event loop.
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode

from app import bot as bot_mod
from app import db, listener
from app.config import settings
from app.report import build_report_text
from app.workqueue import JobQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _schedule_daily_report(scheduler: AsyncIOScheduler, app):
    hour, minute = (int(x) for x in settings.daily_report_time.split(":"))

    async def job():
        text = build_report_text()
        await app.bot.send_message(
            chat_id=settings.telegram_owner_chat_id, text=text, parse_mode=ParseMode.HTML
        )

    scheduler.add_job(job, "cron", hour=hour, minute=minute)


async def main():
    db.init_db()

    problems = settings.validate()
    if problems:
        logger.warning("Config incomplete, some features may not work:")
        for p in problems:
            logger.warning(" - %s", p)

    client = listener.build_client()
    await client.start()

    app = bot_mod.build_application()
    app.bot_data["telethon_client"] = client
    refresh_event = asyncio.Event()
    app.bot_data["refresh_event"] = refresh_event
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    scheduler = AsyncIOScheduler()
    _schedule_daily_report(scheduler, app)
    scheduler.start()

    async def on_pending(job_id: int):
        await bot_mod.send_approval_card(app, job_id)

    # Everything discovered (poll loop, backfill) funnels through this one
    # queue/worker so there's only ever one thing processing at a time --
    # no more concurrent writers hammering the database or Groq/SMTP.
    queue = JobQueue(on_pending)
    app.bot_data["job_queue"] = queue
    worker_task = asyncio.create_task(queue.run_worker())

    # Recover anything discovered-but-not-processed from a previous run
    # (e.g. the app restarted while these were still sitting in the
    # in-memory queue, or mid rate-limit backoff) -- they're already
    # durably in the database at status='queued', just re-enqueue them.
    stuck_job_ids = db.get_job_ids_by_status("queued")
    if stuck_job_ids:
        logger.info("Recovering %d job(s) left over from a previous run", len(stuck_job_ids))
        for job_id in stuck_job_ids:
            await queue.put(job_id)

    try:
        await listener.run_poll_loop(
            client, queue, settings.poll_interval_seconds, refresh_event, settings.backfill_days
        )
    finally:
        worker_task.cancel()
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
