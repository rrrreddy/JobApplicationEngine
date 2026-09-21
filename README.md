# Auto-Job-Application Engine

A human-in-the-loop job application assistant. It watches your Telegram job
channels, filters out spam, judges fit against your profile with an LLM,
drafts a personalized application email, and waits for you to tap **Send**
or **Don't Send** on a card in your own private Telegram chat. Nothing goes
out without your approval.

Current scope (MVP): **Telegram channels only**. LinkedIn is intentionally
not scraped automatically -- LinkedIn's ToS prohibits automated scraping and
actively bans accounts for it. Instead, paste/forward any LinkedIn post's
text directly into the bot chat and it runs through the exact same
screening + drafting pipeline (see "Manual forward" below).

## How it works

1. `app/listener.py` uses your own Telegram account (via Telethon) to read
   new messages in the channels you list in `.env`.
2. Each post goes through `app/pipeline.py`:
   - `app/filters.py` -- cheap heuristic filter (drops greetings, fee
     scams, crypto spam, anything without job-like keywords) before any
     LLM call.
   - `app/llm.py` (`judge_fit`) -- an LLM call with your profile loaded
     decides if it's a real vacancy and if it's a fit for you.
   - `app/llm.py` (`draft_application`) -- if it's a fit, extracts the
     recruiter email and drafts a short, human-sounding application email.
   - Dedup: reposts of the same content are skipped (`content_hash`), and
     you'll never be offered to email the same recruiter address twice.
3. A fit gets posted as a card in your Telegram bot chat (`app/bot.py`)
   with **Send** / **Don't Send** buttons.
4. **Send** triggers `app/mailer.py`, which emails the recruiter over SMTP
   with your resume attached, respecting a cooldown between sends.
5. `/report` any time, or an automatic daily summary at `DAILY_REPORT_TIME`,
   shows how many were screened, applied to, skipped, or failed today.

## Setup walkthrough

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Telegram API credentials (for reading channels)

These let the engine log in as *you* to read channels you're a member of.

1. Go to https://my.telegram.org, log in with your phone number.
2. Go to "API development tools", create an app (any name/URL works).
3. Copy the **api_id** and **api_hash** into `.env` as `TELEGRAM_API_ID`
   and `TELEGRAM_API_HASH`.

### 3. Telegram bot (for the approval control room)

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   follow the prompts.
2. Copy the token it gives you into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Message your new bot anything (e.g. `/start`) so it can see your chat.
4. To find your `TELEGRAM_OWNER_CHAT_ID`, message
   [@userinfobot](https://t.me/userinfobot) and copy the `Id` it replies
   with into `.env`. This locks the bot to only ever talk to you.

### 4. Channels to watch

Add the channel usernames (no `@`) or invite links you want watched, comma
separated, to `TELEGRAM_JOB_CHANNELS` in `.env`. You must already be a
member of each one.

### 5. LLM (Groq, open-weight model, free tier available)

1. Go to https://console.groq.com/keys, sign up, create an API key.
2. Copy it into `.env` as `GROQ_API_KEY`. The default model
   (`llama-3.3-70b-versatile`) works well for this; change `GROQ_MODEL` if
   you want a different open-weight model Groq hosts.

### 6. Email sending (Gmail example)

1. Enable 2-Step Verification on your Google account if not already on.
2. Go to https://myaccount.google.com/apppasswords, create an app password
   for "Mail".
3. Put your Gmail address in `SMTP_USER` and the 16-character app password
   (no spaces) in `SMTP_PASSWORD`.
4. Using a different provider (Outlook, custom SMTP)? Just change
   `SMTP_HOST`/`SMTP_PORT` accordingly.

### 7. Resume

Put your resume PDF at `./data/resume.pdf` (or point `RESUME_PATH`
somewhere else). It's attached to every application email automatically.

### 8. Run it

```bash
cp .env.example .env   # then fill in the values above
python -m app.main
```

First run will ask for your phone number + the login code Telegram sends
you (this is Telethon logging in as your account to read channels) --
after that a session file is saved and you won't be asked again.

Then message your bot `/start` and `/setprofile` to fill in your candidate
profile (title, stack, years of experience, target roles, relocation
preference, achievements) -- this is what the LLM uses to judge fit.

## Manual forward (LinkedIn, or anything outside watched channels)

Paste any job post's text directly into the bot chat. It runs through the
identical filter -> fit-judgment -> draft -> approval pipeline as channel
posts. This is the current, ToS-safe way to include LinkedIn posts: no
automated scraping of your account.

## Hosting it continuously

**Using: local Docker, on your own machine.** No cloud account, no card,
no signup friction -- just Docker running on a computer you leave on and
connected to the internet. This is a persistent background process (it
needs to stay running, not spin up per-request), so the machine needs to
actually stay powered on; see the OS-specific notes below for preventing
sleep and auto-starting on boot.

```bash
git clone <your repo url> && cd JobApplicationEngine
cp .env.example .env && nano .env    # or any editor -- fill in credentials
mkdir -p data                        # put your resume at data/resume.pdf
docker compose run --rm job-engine   # first run only: interactive Telethon phone-code login
docker compose up -d                 # then runs continuously in the background
```

Check it's alive any time: `docker compose logs -f`.

### Keeping it running continuously

- **Prevent sleep**: laptops/desktops sleeping kills the container's
  network connections. On macOS: System Settings -> Lock Screen -> set
  "Turn display off" and disable "Put hard disks/Mac to sleep" (or
  `sudo pmset -c sleep 0` while it's plugged in). On Windows: Settings ->
  System -> Power & battery -> set Sleep to Never (while plugged in). On
  Linux: `sudo systemctl mask sleep.target suspend.target hibernate.target`.
- **Auto-start on boot**: Docker Desktop (Mac/Windows) has a "Start Docker
  Desktop when you sign in" option in its settings, and
  `restart: unless-stopped` in `docker-compose.yml` (already set) means
  the container itself relaunches automatically whenever Docker restarts.
  On Linux with plain Docker Engine: `sudo systemctl enable docker`.

### If you ever want it reachable without your machine staying on

The cloud paths are still documented and ready to go if you change your
mind later: [`deploy/oracle-setup.md`](deploy/oracle-setup.md) (Oracle
Always Free, most generous but had signup issues) and
[`deploy/gcp-setup.md`](deploy/gcp-setup.md) (Google Cloud `e2-micro`,
smaller but simpler signup). Same `docker compose` commands apply there
too, via `deploy/oracle_vm_setup.sh` / `deploy/gcp_vm_setup.sh`.

## Commands

- `/start` -- status + help
- `/setprofile` -- fill in / update your candidate profile
- `/channels` -- list, add, or remove watched channels (`/channels add
  <username> [label]`, `/channels remove <username>`)
- `/report` -- on-demand summary of today's activity
- `/cancel` -- abort an in-progress `/setprofile` conversation

## Notes / known limitations of this MVP

- No web dashboard yet -- Telegram is the only interface. The DB layer
  (`app/db.py`) is plain SQLite and reusable if a website dashboard is
  added later for profile editing and richer reporting.
- LinkedIn automation is deliberately out of scope for now given ToS/ban
  risk -- see "Manual forward" above.
- The noise filter and LLM prompts are a reasonable starting point but
  will likely need tuning (`app/filters.py`, prompts in `app/llm.py`) once
  you see real channel traffic.
