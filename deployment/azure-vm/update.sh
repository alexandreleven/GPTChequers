#!/bin/bash

# Update the running stack with the latest images from Azure Container Registry (ACR).
# Authenticates to ACR, pulls registry images only (no local builds), and recreates containers while preserving volumes.
# Run from the directory that contains docker-compose.prod.yml (e.g. /opt/onyx after copying deployment/azure-vm).
# Requires: ACR_REGISTRY set in .env (e.g. myregistry.azurecr.io). Azure CLI and login to Azure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "docker-compose.prod.yml" ]; then
  echo "Error: docker-compose.prod.yml not found in $SCRIPT_DIR" >&2
  exit 1
fi

# Load ACR_REGISTRY from .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

if [ -z "${ACR_REGISTRY:-}" ]; then
  echo "Error: ACR_REGISTRY not set. Set it in .env or environment (e.g. myregistry.azurecr.io)." >&2
  exit 1
fi

# Registry name is the first component (without .azurecr.io)
ACR_NAME="${ACR_REGISTRY%%.*}"

echo "=== Updating Eleven stack ==="
echo "Registry: $ACR_REGISTRY"
echo "Compose file: docker-compose.prod.yml"

echo "Logging into ACR..."
az login --identity
az acr login --name "$ACR_NAME"

echo "Pulling images..."
# --ignore-buildable: will only pull services that have an image in the registry
docker compose -f docker-compose.prod.yml pull --ignore-buildable


echo "Restarting services..."
# -d               : run containers in the background
# --remove-orphans : remove containers not defined in the current compose file
# --no-build       : never build images locally (pull / use registry images only)
# --force-recreate : always recreate containers, even if configuration did not change
docker compose -f docker-compose.prod.yml up -d --remove-orphans --no-build --force-recreate

echo "Cleaning up old images..."
docker image prune -f

echo "=== Running containers ==="
docker compose -f docker-compose.prod.yml ps

echo "=== Update complete ==="
