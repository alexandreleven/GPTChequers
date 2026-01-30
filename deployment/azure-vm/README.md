# Azure VM deployment for Eleven

Self-contained Azure VM deployment for Eleven (no Vespa), using Azure Container Registry (ACR) and optional Azure Key Vault for certificates.

## Purpose

This folder contains everything needed to run Eleven on an Azure VM. Copy the entire folder to the VM (e.g. `/opt/onyx`) and run with Docker Compose. No build step on the VM; images are pulled from ACR.

## Prerequisites

- **Azure VM** with Docker and Docker Compose installed
- **Azure Container Registry (ACR)** with images pushed (e.g. by GitHub Actions `deployment.yml`)
- **Optional:** Azure Key Vault for storing Let's Encrypt certs or app secrets
- **Optional:** Domain and HTTPS via Let's Encrypt (see below)

## Quick start

1. Copy this entire folder to the VM (e.g. `/opt/onyx`).

2. Create `.env` from `env.eleven` and set at least:
   - `ACR_REGISTRY` (e.g. `myregistry.azurecr.io`)
   - `IMAGE_TAG` (e.g. `latest`)
   - `POSTGRES_PASSWORD` (and other required app/auth vars)

3. **HTTPS (optional):** Create `.env.nginx` from `env.nginx.eleven` (set `DOMAIN` and optionally `EMAIL`), then run:
   ```bash
   chmod +x init-letsencrypt.eleven.sh
   ./init-letsencrypt.eleven.sh
   ```

4. Start the stack:
   ```bash
   docker compose -f docker-compose.prod.eleven.yml up -d
   ```

5. To update images later (e.g. after a new build):
   ```bash
   ./update.sh
   ```
   Ensure `.env` has `ACR_REGISTRY` set and Azure CLI is logged in (or use a managed identity that can pull from ACR).

## Main files

| File / folder | Purpose |
|---------------|--------|
| `docker-compose.prod.eleven.yml` | Compose file: ACR images only, no Vespa, nginx/certbot under `./nginx` and `./certbot`. |
| `nginx/` | Nginx config: `run-nginx.sh`, `app.conf.eleven.prod`, MCP configs (`.eleven`). Mounted into the nginx container. |
| `init-letsencrypt.eleven.sh` | One-time Let's Encrypt setup; uses `docker-compose.prod.eleven.yml` and local `./certbot`. |
| `update.sh` | Pull images from ACR and restart services; run from this directory. |
| `env.eleven` | Example env for `.env` (ACR, DB, auth, MinIO, etc.). Copy to `.env` and fill in. |
| `env.nginx.eleven` | Example env for `.env.nginx` (DOMAIN, EMAIL for HTTPS). Copy to `.env.nginx` for nginx and init-letsencrypt. |

You need `.env.nginx` for HTTPS (create from `env.nginx.eleven`); it is used by the nginx container and by `init-letsencrypt.eleven.sh`.

## GitHub Actions

If you use the repo’s deploy workflows (`deploy.yml`, `setup-vm.yml`), configure them to copy from `deployment/azure-vm/` to the VM and to use `docker-compose.prod.eleven.yml` so that the VM runs this self-contained setup.

## Notes

- **No Vespa:** This setup does not include the Vespa index service; it is the “Eleven” variant.
- **Images:** All app images are expected from ACR (`ACR_REGISTRY` + `IMAGE_TAG`). Postgres, Redis, Nginx, Certbot, and MinIO use public images.
- **Paths:** Nginx and certbot use `./nginx` and `./certbot` so that a single copy of this folder on the VM is enough.
