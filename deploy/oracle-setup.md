# Deploying to Oracle Cloud's Always Free tier

Oracle's free tier is permanent (not a trial) and more generous than
GCP's: you get a pool of up to **4 Ampere A1 (ARM) OCPUs and 24GB RAM**,
usable as one instance or split across several, plus 2 AMD
`VM.Standard.E2.1.Micro` instances (1GB RAM each) as a separate
allowance. 200GB total block storage is included. A credit card is
required at signup for identity verification only -- you're not charged
unless you explicitly upgrade to Pay As You Go.

The one real friction point: Ampere A1 capacity is popular and Oracle
sometimes returns **"Out of host capacity"** when you try to create one,
especially in busy regions. If that happens: try a different
Availability Domain in the same region (the create form lets you pick),
try again in a few minutes/hours, or fall back to the smaller AMD Micro
shape (guaranteed available, just 1GB RAM -- still fine for this app).

## 1. Sign up

Go to https://www.oracle.com/cloud/free/ and create an account. Pick your
home region carefully during signup -- this becomes fixed for your
tenancy and determines where your Always Free resources live.

## 2. Create the instance

1. In the Oracle Cloud console, go to **Compute → Instances → Create Instance**.
2. Name it (e.g. `job-engine`).
3. **Image and shape** → Edit:
   - **Image**: Canonical Ubuntu (22.04 or later).
   - **Shape**: click Change Shape → **Ampere** series → `VM.Standard.A1.Flex`.
     Set **2 OCPUs / 12GB memory** (leaves the other half of the free
     Ampere pool available for something else later; bump it to 4/24 if
     you'd rather have it all on one box). If you hit "out of host
     capacity" here, that's the friction point mentioned above -- try
     another Availability Domain or the `VM.Standard.E2.1.Micro` (AMD,
     always available, 1GB RAM) as a fallback.
4. **Networking**: leave the default "Create new virtual cloud network"
   option selected -- it sets up internet connectivity and a security
   list that allows inbound SSH automatically. No changes needed.
5. **Add SSH keys**: select **Generate a key pair for me**, then click
   **Save private key** and **Save public key**. Unlike GCP's
   browser-based SSH, Oracle needs you to manage your own key pair --
   keep the private key file safe, you'll use it to connect.
6. **Boot volume**: default (50GB) is fine, well within the 200GB free
   block storage allowance.
7. Click **Create**.

## 3. SSH in

From your local machine, using the private key you downloaded:

```bash
chmod 400 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<the instance's public IP>
```

The public IP is shown on the instance's detail page in the console once
it's running (takes a minute or two after creation).

## 4. Prepare the machine

```bash
git clone <your repo url>
cd JobApplicationEngine
chmod +x deploy/oracle_vm_setup.sh
./deploy/oracle_vm_setup.sh
```

Installs Docker + the compose plugin, and adds a swapfile automatically
if it detects a low-RAM shape (the AMD Micro). Ampere shapes with plenty
of RAM skip that step.

If you were just added to the `docker` group, run `newgrp docker` (or
close and reopen the SSH session) before the next step.

## 5. Configure and run

```bash
cp .env.example .env
nano .env              # fill in Telegram/Groq/SMTP credentials
mkdir -p data
# upload your resume from your local machine, e.g.:
#   scp -i ~/Downloads/ssh-key-*.key ./resume.pdf ubuntu@<public-ip>:~/JobApplicationEngine/data/resume.pdf

docker compose run --rm job-engine   # first run only: interactive Telethon phone-code login
docker compose up -d                 # then runs continuously in the background
```

Check it's alive: `docker compose logs -f`.

## 6. Staying free

- Keep the Ampere allocation at or under 4 OCPU / 24GB total across all
  your A1 instances, and don't exceed 2 AMD Micro instances.
- Don't reserve a static public IP beyond the one ephemeral IP attached
  to the instance (reserved IPs you're not using can incur cost).
- Stay on the Always Free tier in the console's billing settings --
  don't click "Upgrade Account" unless you intend to.
