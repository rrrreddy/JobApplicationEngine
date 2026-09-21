# Deploying to Google Cloud's Always Free e2-micro

Google Cloud's free tier includes one `e2-micro` Compute Engine instance
per month, permanently free (not a trial), with these constraints:

- Only in **`us-west1`, `us-central1`, or `us-east1`** -- pick one of these
  regions or you'll be billed.
- Up to 30GB standard persistent disk, free.
- 1GB/month network egress to most destinations, free (this app's traffic
  -- Telegram/Groq/SMTP API calls -- is tiny, won't come close).
- Requires a Google Cloud account with billing enabled (for identity
  verification) -- you will not be charged as long as you stay within the
  Always Free limits (1 e2-micro, in an eligible region, not upgraded to
  a bigger machine type).

## 1. Create the project + VM (Console)

1. Go to https://console.cloud.google.com, create a new project (or use
   an existing one).
2. Enable the **Compute Engine API** if prompted.
3. Go to **Compute Engine → VM instances → Create Instance**.
4. Name it (e.g. `job-engine`).
5. **Region**: pick `us-west1`, `us-central1`, or `us-east1` (any zone
   within it). This is the part that must match to stay free.
6. **Machine type**: `e2-micro` (under the "E2" series).
7. **Boot disk**: click Change → OS: Ubuntu, version: Ubuntu 22.04 LTS,
   size: 30GB (the free-tier max), type: Standard persistent disk.
8. Leave firewall checkboxes unticked -- this app makes only outbound
   connections (to Telegram, Groq, SMTP), it doesn't need to accept
   inbound traffic, so no firewall rule is needed.
9. Click **Create**.

Equivalent as a single `gcloud` CLI command, if you have the SDK installed
locally:

```bash
gcloud compute instances create job-engine \
  --project=YOUR_PROJECT_ID \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard
```

## 2. SSH in

Easiest: in the Console, on the VM instances list, click the **SSH**
button next to your instance -- opens a browser-based terminal, no local
setup needed.

(Or, with the CLI: `gcloud compute ssh job-engine --zone=us-central1-a`.)

## 3. Prepare the machine

```bash
git clone <your repo url>
cd JobApplicationEngine
chmod +x deploy/gcp_vm_setup.sh
./deploy/gcp_vm_setup.sh
```

This installs Docker + the compose plugin and adds a 2GB swapfile (the
e2-micro's 1GB RAM is tight for Docker + Python + a few concurrent
network clients without it).

If you were just added to the `docker` group, run `newgrp docker` (or log
out/back in via SSH) before the next step.

## 4. Configure and run

```bash
cp .env.example .env
nano .env              # fill in Telegram/Groq/SMTP credentials
mkdir -p data
# upload your resume to data/resume.pdf, e.g. from your local machine:
#   gcloud compute scp ./resume.pdf job-engine:~/JobApplicationEngine/data/resume.pdf --zone=us-central1-a

docker compose run --rm job-engine   # first run only: interactive Telethon phone-code login
docker compose up -d                 # then runs continuously in the background
```

Check it's alive: `docker compose logs -f`.

## 5. Keep it free

- Don't change the machine type away from `e2-micro`.
- Don't add a static external IP reservation you leave unused (idle
  reserved IPs are billed; an ephemeral IP, the default, is fine and is
  all this app needs since nothing connects inbound).
- Keep the boot disk at or under 30GB.
- Stay in one of the three eligible regions.
