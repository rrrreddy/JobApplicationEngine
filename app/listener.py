"""Telethon client that periodically checks your job channels and enqueues
each new post for processing. Uses your own Telegram account (not a bot)
so it can read channels/groups you're a member of, admin or not.

On first run this will prompt for your phone number + login code in the
terminal, then save a .session file so you won't be asked again.

Watching is poll-based rather than a live event stream: every
POLL_INTERVAL_SECONDS (default 30 min) it checks each channel for
messages newer than the last time that channel was checked, independent
of Telegram's read/unread state. A manual /refresh in the bot wakes the
loop early via `refresh_event` for an on-demand check.

Discovering new messages (this module) is kept separate from processing
them (app.workqueue.JobQueue) -- both the poll loop and backfill just
enqueue what they find, and a single worker processes everything one at
a time, so there's never more than one thing writing to the database or
calling Groq/SMTP at once.
"""
import asyncio
import datetime as dt
import logging

from telethon import TelegramClient

from app import db
from app.config import settings
from app.workqueue import JobQueue

logger = logging.getLogger(__name__)

SESSION_PATH = "data/job_watcher"


def build_client() -> TelegramClient:
    return TelegramClient(SESSION_PATH, settings.telegram_api_id, settings.telegram_api_hash)


async def resolve_channel(client: TelegramClient, identifier: str):
    """Resolves a configured TELEGRAM_JOB_CHANNELS entry to a Telethon
    entity. Accepts a public @username, an invite link, a numeric chat ID,
    or -- for private groups/channels with no username, which can't be
    resolved by Telegram's API directly -- falls back to matching against
    the exact or partial title of a chat in your dialog list.
    """
    identifier = identifier.strip()
    stripped = identifier.lstrip("@")

    if stripped.lstrip("-").isdigit():
        try:
            return await client.get_entity(int(stripped))
        except Exception:
            pass

    try:
        return await client.get_entity(identifier)
    except Exception:
        pass

    lowered = identifier.lower()
    async for dialog in client.iter_dialogs():
        if dialog.name and dialog.name.strip().lower() == lowered:
            return dialog.entity

    async for dialog in client.iter_dialogs():
        if dialog.name and lowered in dialog.name.strip().lower():
            return dialog.entity

    return None


async def resolve_channels(client: TelegramClient, identifiers: list[str]) -> dict[str, object]:
    """Resolves each configured identifier, logging (and skipping) any
    that can't be matched to an actual chat instead of crashing later."""
    resolved = {}
    for identifier in identifiers:
        entity = await resolve_channel(client, identifier)
        if entity is None:
            logger.error(
                "Could not resolve channel %r to a Telegram chat -- it will NOT be watched. "
                "Use the group's @username if it has one, or make sure this matches the chat's "
                "exact title as shown in your Telegram app.",
                identifier,
            )
        else:
            label = getattr(entity, "username", None) or getattr(entity, "title", None) or identifier
            logger.info("Resolved channel %r -> %s", identifier, label)
            resolved[identifier] = entity
    return resolved


async def run_backfill(client: TelegramClient, days: int, queue: JobQueue):
    """Finds messages from the last `days` days in each watched channel
    and enqueues them, regardless of each channel's poll bookkeeping.
    Safe to re-run or overlap with the poll loop: the pipeline's
    content-hash dedup means a message already seen and resolved is
    skipped automatically (a previously *failed* one is retried, which is
    intentional). Enqueueing is fast; the actual pacing happens in the
    queue's single worker.
    """
    if days <= 0:
        return
    if not settings.job_channels:
        logger.warning("No TELEGRAM_JOB_CHANNELS configured; nothing to backfill.")
        return

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    resolved = await resolve_channels(client, settings.job_channels)

    for identifier, entity in resolved.items():
        channel_label = getattr(entity, "username", None) or getattr(entity, "title", None) or identifier
        messages = []
        async for message in client.iter_messages(entity):
            if not message.date or message.date < cutoff:
                break
            if message.raw_text and message.raw_text.strip():
                messages.append(message)

        logger.info("Backfilling %d message(s) from %s (last %d day(s))", len(messages), channel_label, days)
        for message in reversed(messages):  # oldest first, matches how they'd have arrived live
            await queue.put(channel_label, message.id, message.raw_text)


async def _check_channel_once(client: TelegramClient, identifier: str, entity, queue: JobQueue, seed_days: int):
    """Enqueues messages newer than this channel's last recorded check.
    On a channel's very first ever check, seeds the starting point `seed_days`
    back (0 = only messages from this point forward)."""
    last_checked = db.get_channel_last_checked(identifier)
    now = dt.datetime.now(dt.timezone.utc)
    if last_checked is None:
        cutoff = now - dt.timedelta(days=seed_days) if seed_days > 0 else now
    else:
        cutoff = dt.datetime.fromtimestamp(last_checked, tz=dt.timezone.utc)

    channel_label = getattr(entity, "username", None) or getattr(entity, "title", None) or identifier
    messages = []
    async for message in client.iter_messages(entity):
        if not message.date or message.date <= cutoff:
            break
        if message.raw_text and message.raw_text.strip():
            messages.append(message)

    if messages:
        logger.info("Found %d new message(s) in %s since last check", len(messages), channel_label)
    for message in reversed(messages):  # oldest first
        await queue.put(channel_label, message.id, message.raw_text)

    db.set_channel_last_checked(identifier, now.timestamp())


async def run_poll_loop(
    client: TelegramClient,
    queue: JobQueue,
    interval_seconds: int,
    refresh_event: asyncio.Event,
    seed_days: int = 0,
):
    """Runs forever: checks every watched channel for new messages, then
    waits either `interval_seconds` or until `refresh_event` is set
    (e.g. by the bot's /refresh command) for an immediate re-check.
    """
    resolved = await resolve_channels(client, settings.job_channels)
    if not resolved:
        logger.error(
            "None of the configured TELEGRAM_JOB_CHANNELS could be resolved -- "
            "nothing will be watched until this is fixed."
        )

    logger.info(
        "Polling %d channel(s) every %d seconds (manual /refresh also supported)",
        len(resolved), interval_seconds,
    )

    while True:
        for identifier, entity in resolved.items():
            try:
                await _check_channel_once(client, identifier, entity, queue, seed_days)
            except Exception:
                logger.exception("Error checking channel %s", identifier)

        refresh_event.clear()
        try:
            await asyncio.wait_for(refresh_event.wait(), timeout=interval_seconds)
            logger.info("Manual refresh triggered, checking again now")
        except asyncio.TimeoutError:
            pass
