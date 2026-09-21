"""Telethon client that watches your job channels and runs each new post
through the pipeline. Uses your own Telegram account (not a bot) so it can
read channels/groups you're a member of, admin or not.

On first run this will prompt for your phone number + login code in the
terminal, then save a .session file so you won't be asked again.
"""
import asyncio
import logging
from typing import Awaitable, Callable

from telethon import TelegramClient, events

from app.config import settings
from app import pipeline

logger = logging.getLogger(__name__)

SESSION_PATH = "data/job_watcher"

OnPending = Callable[[int], Awaitable[None]]


async def run_listener(on_pending: OnPending):
    client = TelegramClient(SESSION_PATH, settings.telegram_api_id, settings.telegram_api_hash)

    if not settings.job_channels:
        logger.warning("No TELEGRAM_JOB_CHANNELS configured; listener has nothing to watch.")

    @client.on(events.NewMessage(chats=settings.job_channels or None))
    async def handler(event):
        text = event.raw_text or ""
        if not text.strip():
            return
        chat = await event.get_chat()
        channel_label = getattr(chat, "username", None) or getattr(chat, "title", None) or str(event.chat_id)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, pipeline.process_post, channel_label, event.id, text
        )
        logger.info("Processed post from %s -> %s (%s)", channel_label, result.status, result.detail)

        if result.status == "pending" and result.job_id is not None:
            await on_pending(result.job_id)

    await client.start()
    logger.info("Telethon listener started, watching: %s", settings.job_channels)
    await client.run_until_disconnected()
