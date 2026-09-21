"""Telethon client that watches your job channels and runs each new post
through the pipeline. Uses your own Telegram account (not a bot) so it can
read channels/groups you're a member of, admin or not.

On first run this will prompt for your phone number + login code in the
terminal, then save a .session file so you won't be asked again.
"""
import asyncio
import datetime as dt
import logging
from typing import Awaitable, Callable

from telethon import TelegramClient, events

from app import pipeline
from app.config import settings

logger = logging.getLogger(__name__)

SESSION_PATH = "data/job_watcher"

OnPending = Callable[[int], Awaitable[None]]


def build_client() -> TelegramClient:
    return TelegramClient(SESSION_PATH, settings.telegram_api_id, settings.telegram_api_hash)


async def _process_and_notify(channel_label: str, message_id: int, text: str, on_pending: OnPending):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, pipeline.process_post, channel_label, message_id, text)
    logger.info("Processed post from %s -> %s (%s)", channel_label, result.status, result.detail)
    if result.status == "pending" and result.job_id is not None:
        await on_pending(result.job_id)
    return result


async def run_backfill(client: TelegramClient, days: int, on_pending: OnPending, delay_seconds: float = 1.5):
    """Fetches and screens messages from the last `days` days in each
    watched channel. Safe to re-run or overlap with live watching: the
    pipeline's content-hash dedup means a message already seen (whether
    live or from a previous backfill) is skipped automatically, so this
    never double-processes or double-sends anything.

    `delay_seconds` paces requests between messages to stay well under
    Telegram's and Groq's rate limits during a large catch-up run.
    """
    if days <= 0:
        return
    if not settings.job_channels:
        logger.warning("No TELEGRAM_JOB_CHANNELS configured; nothing to backfill.")
        return

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    for channel in settings.job_channels:
        try:
            entity = await client.get_entity(channel)
        except Exception:
            logger.exception("Could not resolve channel %s for backfill", channel)
            continue

        channel_label = getattr(entity, "username", None) or getattr(entity, "title", None) or channel
        messages = []
        async for message in client.iter_messages(entity):
            if not message.date or message.date < cutoff:
                break
            if message.raw_text and message.raw_text.strip():
                messages.append(message)

        logger.info("Backfilling %d message(s) from %s (last %d day(s))", len(messages), channel_label, days)
        for message in reversed(messages):  # oldest first, matches how they'd have arrived live
            await _process_and_notify(channel_label, message.id, message.raw_text, on_pending)
            await asyncio.sleep(delay_seconds)


async def run_listener(client: TelegramClient, on_pending: OnPending):
    if not settings.job_channels:
        logger.warning("No TELEGRAM_JOB_CHANNELS configured; listener has nothing to watch.")

    @client.on(events.NewMessage(chats=settings.job_channels or None))
    async def handler(event):
        text = event.raw_text or ""
        if not text.strip():
            return
        chat = await event.get_chat()
        channel_label = getattr(chat, "username", None) or getattr(chat, "title", None) or str(event.chat_id)
        await _process_and_notify(channel_label, event.id, text, on_pending)

    logger.info("Telethon listener started, watching: %s", settings.job_channels)
    await client.run_until_disconnected()
