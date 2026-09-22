# Deploying to Azure

Since you're reusing Docker (not Container Instances or App Service),
this is the same pattern as the Oracle/GCP guides: a plain Ubuntu VM
running `docker compose`. The one shortcut available here that Railway
didn't allow: your Mac already has a fully authenticated Telegram
session and your resume sitting in `data/`, so instead of any
env-var-encoding workaround, you just copy that folder straight to the
VM.

## 1. Create the VM

In the Azure Portal:

1. **Create a resource → Virtual Machine**.
2. **Image**: Ubuntu Server 22.04 LTS.
3. **Size**: `Standard_B1s` (1 vCPU, 1GB RAM) is enough for this app and
   cheap on pay-as-you-go/student credit; go up to `Standard_B2s` (2
   vCPU, 4GB) if you want more headroom or plan to add more later.
4. **Authentication**: SSH public key (Azure will offer to generate a
   new key pair for you, or use one you already have) -- download/save
   the private key, you'll need it to connect.
5. **Inbound ports**: only allow SSH (22). This app makes outbound-only
   connections (Telegram/Groq/SMTP), nothing needs to be exposed inbound.
6. Create it. Note the VM's public IP address once it's running.

Equivalent via the `az` CLI, if you have it installed locally:
```bash
az vm create \
  --resource-group <your-resource-group> \
  --name job-engine \
  --image Ubuntu2204 \
  --size Standard_B1s \
  --admin-username azureuser \
  --generate-ssh-keys
```

## 2. SSH in and prepare the VM

```bash
ssh -i <path-to-private-key> azureuser@<vm-public-ip>
git clone <your repo url>
cd JobApplicationEngine
chmod +x deploy/azure_vm_setup.sh
./deploy/azure_vm_setup.sh
```

Installs Docker + the compose plugin, adds a swapfile if the VM has
under 2GB RAM. If you were just added to the `docker` group, run
`newgrp docker` (or reconnect via SSH) before continuing.

## 3. Configure

```bash
cp .env.example .env
nano .env   # fill in Telegram/Groq/SMTP credentials
```

## 4. Copy your existing session + resume up (no re-login needed)

From your **Mac** (not the VM), in your local `JobApplicationEngine`
folder:

```bash
scp -i <path-to-private-key> data/job_watcher.session azureuser@<vm-public-ip>:~/JobApplicationEngine/data/
scp -i <path-to-private-key> data/resume.pdf azureuser@<vm-public-ip>:~/JobApplicationEngine/data/
```

This reuses the Telegram login you already completed locally -- no
interactive phone-code step needed on the VM.

## 5. Run it

Back on the **VM**:

```bash
docker compose up -d
docker compose logs -f
```

Should come straight up already logged in and watching your channels,
since the session file is already there.

## Keeping costs predictable

- `Standard_B1s`/`B2s` are burstable/cheap, but they're not free unless
  your subscription has free-tier credit or student credits covering
  them -- check Azure's cost estimator for your specific subscription
  type before creating the VM.
- Stop (deallocate) the VM from the Portal if you ever want to pause
  billing without deleting it -- `az vm deallocate` or the Portal's
  Stop button, not just shutting down the OS from inside (that still
  bills for the reserved VM).
