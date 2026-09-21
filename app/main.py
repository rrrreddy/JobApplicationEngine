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
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    scheduler = AsyncIOScheduler()
    _schedule_daily_report(scheduler, app)
    scheduler.start()

    async def on_pending(job_id: int):
        await bot_mod.send_approval_card(app, job_id)

    if settings.backfill_days > 0:
        logger.info("Running startup backfill for the last %d day(s)", settings.backfill_days)
        await listener.run_backfill(client, settings.backfill_days, on_pending)
        logger.info("Startup backfill complete")

    try:
        await listener.run_listener(client, on_pending)
    finally:
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
