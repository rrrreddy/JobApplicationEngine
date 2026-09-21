"""The Telegram control room: approval cards, profile setup, channel management,
manual-forward (e.g. for LinkedIn posts you paste in by hand), and on-demand reports.

Only ever talks to TELEGRAM_OWNER_CHAT_ID -- every handler checks the sender.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters as tg_filters,
)

from app import db, listener, mailer, pipeline
from app import profile as profile_mod
from app.config import settings
from app.report import build_report_text

logger = logging.getLogger(__name__)

(
    ASK_FULL_NAME,
    ASK_EMAIL,
    ASK_PHONE,
    ASK_TITLE,
    ASK_YEARS,
    ASK_STACK,
    ASK_ROLES,
    ASK_RELOCATION,
    ASK_ACHIEVEMENTS,
) = range(9)


def _is_owner(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == settings.telegram_owner_chat_id


async def _guard(update: Update) -> bool:
    if not _is_owner(update):
        # Silently ignore anyone who isn't you -- this bot is private.
        return False
    return True


# ---------- basic commands ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    profile = profile_mod.get_profile()
    if profile_mod.is_complete(profile):
        await update.message.reply_text(
            "You're all set. I'll post a card here whenever a matching job comes in.\n\n"
            "Commands:\n"
            "/setprofile - edit your profile\n"
            "/channels - manage watched channels\n"
            "/backfill [days] - screen recent history from watched channels (default 10 days)\n"
            "/report - today's summary\n\n"
            "You can also paste any job post text directly into this chat "
            "(e.g. a LinkedIn post you're forwarding manually) and I'll screen it the same way."
        )
    else:
        missing = ", ".join(profile_mod.missing_fields(profile))
        await update.message.reply_text(
            f"Welcome. Your profile is incomplete (missing: {missing}).\n"
            f"Run /setprofile to fill it in -- I need it to judge which jobs actually fit you."
        )


async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    args = context.args
    if not args:
        rows = db.list_channels()
        if not rows:
            await update.message.reply_text(
                "No channels configured yet. Use /channels add <username> or edit "
                "TELEGRAM_JOB_CHANNELS in .env and restart."
            )
            return
        listing = "\n".join(f"- {r['identifier']} ({r['label'] or 'no label'})" for r in rows)
        await update.message.reply_text(f"Watching:\n{listing}")
        return

    sub, *rest = args
    if sub == "add" and rest:
        db.add_channel(rest[0], " ".join(rest[1:]))
        await update.message.reply_text(
            f"Added {rest[0]}. Restart the service for the listener to pick it up."
        )
    elif sub == "remove" and rest:
        db.remove_channel(rest[0])
        await update.message.reply_text(f"Removed {rest[0]}.")
    else:
        await update.message.reply_text("Usage: /channels [add <id> [label] | remove <id>]")


_backfill_running = False


async def cmd_backfill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return

    global _backfill_running
    if _backfill_running:
        await update.message.reply_text("A backfill is already running, hang tight.")
        return

    days = 10
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /backfill [days] (default 10)")
            return

    client = context.application.bot_data.get("telethon_client")
    if client is None:
        await update.message.reply_text("Telethon client isn't ready yet, try again in a moment.")
        return

    await update.message.reply_text(
        f"Backfilling the last {days} day(s) across watched channels. "
        f"Already-seen posts are skipped automatically -- this won't double-apply to anything. "
        f"This can take a while on busy channels."
    )

    async def on_pending(job_id: int):
        await send_approval_card(context.application, job_id)

    _backfill_running = True
    try:
        await listener.run_backfill(client, days, on_pending)
    finally:
        _backfill_running = False

    await update.message.reply_text("Backfill complete. Run /report for a summary.")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await update.message.reply_text(build_report_text())


# ---------- /setprofile conversation ----------

async def setprofile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return ConversationHandler.END
    context.user_data["profile"] = dict(profile_mod.get_profile())
    await update.message.reply_text("What's your full name?")
    return ASK_FULL_NAME


def _step(field_name, next_prompt, next_state):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["profile"][field_name] = update.message.text.strip()
        await update.message.reply_text(next_prompt)
        return next_state
    return handler


ask_full_name = _step("full_name", "What's your email address?", ASK_EMAIL)
ask_email = _step("email", "What's your phone number?", ASK_PHONE)
ask_phone = _step("phone", "What's your current job title?", ASK_TITLE)
ask_title = _step("current_title", "How many years of experience do you have?", ASK_YEARS)
ask_years = _step("years_experience", "List your stack/skills, comma-separated.", ASK_STACK)
ask_stack = _step("stack", "What roles are you targeting? Comma-separated.", ASK_ROLES)
ask_roles = _step("target_roles", "What's your relocation/remote preference?", ASK_RELOCATION)
ask_relocation = _step(
    "relocation",
    "List 2-4 standout achievements, one per line.",
    ASK_ACHIEVEMENTS,
)


async def ask_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [l.strip() for l in update.message.text.splitlines() if l.strip()]
    context.user_data["profile"]["achievements"] = lines
    profile_mod.set_profile(context.user_data["profile"])
    await update.message.reply_text("Profile saved. Run /report anytime for a summary.")
    return ConversationHandler.END


async def setprofile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled, no changes saved.")
    return ConversationHandler.END


def build_setprofile_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setprofile", setprofile_start)],
        states={
            ASK_FULL_NAME: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_full_name)],
            ASK_EMAIL: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_email)],
            ASK_PHONE: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_phone)],
            ASK_TITLE: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_title)],
            ASK_YEARS: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_years)],
            ASK_STACK: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_stack)],
            ASK_ROLES: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_roles)],
            ASK_RELOCATION: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_relocation)],
            ASK_ACHIEVEMENTS: [MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, ask_achievements)],
        },
        fallbacks=[CommandHandler("cancel", setprofile_cancel)],
    )


# ---------- approval cards ----------

def _card_text(job) -> str:
    return (
        f"<b>New match</b> ({job['channel']})\n"
        f"<b>To:</b> {job['recruiter_email']}\n"
        f"<b>Subject:</b> {job['draft_subject']}\n\n"
        f"{job['draft_body']}\n\n"
        f"<b>Original post:</b>\n{job['raw_text'][:500]}"
    )


def _card_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Send", callback_data=f"send:{job_id}"),
                InlineKeyboardButton("Don't Send", callback_data=f"skip:{job_id}"),
            ]
        ]
    )


async def send_approval_card(app: Application, job_id: int):
    job = db.get_job(job_id)
    if job is None:
        return
    msg = await app.bot.send_message(
        chat_id=settings.telegram_owner_chat_id,
        text=_card_text(job),
        parse_mode=ParseMode.HTML,
        reply_markup=_card_keyboard(job_id),
    )
    db.update_job(job_id, approval_chat_message_id=msg.message_id)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or query.from_user.id != settings.telegram_owner_chat_id:
        await query.answer()
        return
    await query.answer()

    action, job_id_str = query.data.split(":", 1)
    job_id = int(job_id_str)
    job = db.get_job(job_id)
    if job is None or job["status"] not in ("pending",):
        await query.edit_message_text(query.message.text_html + "\n\n<i>(already handled)</i>", parse_mode=ParseMode.HTML)
        return

    if action == "skip":
        db.update_job(job_id, status="rejected")
        await query.edit_message_text(
            query.message.text_html + "\n\n<b>Skipped.</b>", parse_mode=ParseMode.HTML
        )
        return

    if action == "send":
        db.update_job(job_id, status="approved")
        try:
            mailer.send_application(job["recruiter_email"], job["draft_subject"], job["draft_body"])
        except Exception:
            logger.exception("send failed for job %s", job_id)
            db.update_job(job_id, status="failed")
            await query.edit_message_text(
                query.message.text_html + "\n\n<b>Send FAILED -- check logs, retry manually.</b>",
                parse_mode=ParseMode.HTML,
            )
            return
        db.update_job(job_id, status="sent")
        db.mark_recruiter_contacted(job["recruiter_email"], job_id)
        await query.edit_message_text(
            query.message.text_html + "\n\n<b>Sent.</b>", parse_mode=ParseMode.HTML
        )


# ---------- manual forward (e.g. LinkedIn posts pasted by hand) ----------

async def on_forwarded_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    text = update.message.text or ""
    if len(text.strip()) < 30:
        return  # too short to be a job post, ignore quietly

    await update.message.reply_text("Screening that post...")
    result = pipeline.process_post("manual-forward", None, text)

    if result.status == "pending":
        await send_approval_card(context.application, result.job_id)
    elif result.status == "dropped_noise":
        await update.message.reply_text(f"Dropped: {result.detail}")
    elif result.status == "duplicate_content":
        await update.message.reply_text("Already saw this exact post before.")
    elif result.status == "not_a_fit":
        await update.message.reply_text(f"Not a fit: {result.detail}")
    elif result.status == "no_contact":
        await update.message.reply_text("Looks like a fit, but I couldn't find a contact email in the text.")
    elif result.status == "duplicate_recruiter":
        await update.message.reply_text(f"Skipped: {result.detail}")
    else:
        await update.message.reply_text(f"Couldn't process that post ({result.status}).")


def build_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CommandHandler("backfill", cmd_backfill))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(build_setprofile_conversation())
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, on_forwarded_text))
    return app
