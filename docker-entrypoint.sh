#!/usr/bin/env sh
# Seeds data/ from environment variables if it's not already there, then
# starts the app. This lets a fresh headless deploy (no interactive
# terminal for the Telethon phone-code login, no way to drag-and-drop a
# resume file) reuse a session/resume you already set up locally.
#
# Harmless no-op for local docker-compose use: if these env vars aren't
# set, it just skips straight to starting the app as before.
set -e

mkdir -p data

if [ -n "$TELETHON_SESSION_B64" ] && [ ! -f data/job_watcher.session ]; then
    echo "Restoring Telegram session from TELETHON_SESSION_B64..."
    echo "$TELETHON_SESSION_B64" | base64 -d > data/job_watcher.session
fi

if [ -n "$RESUME_URL" ] && [ ! -f data/resume.pdf ]; then
    echo "Downloading resume from RESUME_URL..."
    python -c "import urllib.request, os; urllib.request.urlretrieve(os.environ['RESUME_URL'], 'data/resume.pdf')"
fi

exec python -m app.main
