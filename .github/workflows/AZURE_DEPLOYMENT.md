# Azure VM Deployment Workflows

This document describes the GitHub Actions workflows for deploying to an Azure VM.

## Overview

| Workflow | Description |
|----------|-------------|
| `deployment.yml` | Build and push Docker images to Azure Container Registry (ACR) |
| `deploy.yml` | Deploy images to an Azure VM via `az vm run-command` |
| `tag-nightly.yml` | Automatically create nightly tags for daily builds |
| `setup-vm.yml` | Initial setup of an Azure VM (Docker, ACR, etc.) |

## Prerequisites

### 1. Azure Configuration

#### Azure Container Registry (ACR)
```bash
# Create an ACR
az acr create --name <registry-name> --resource-group <rg> --sku Basic

# Enable admin (optional, prefer Service Principal)
az acr update --name <registry-name> --admin-enabled true
```

#### Service Principal for CI/CD
```bash
# Create a Service Principal with access to ACR and VMs
az ad sp create-for-rbac --name "github-actions-onyx" \
  --role contributor \
  --scopes /subscriptions/<subscription-id>/resourceGroups/<resource-group>

# Add ACR push/pull rights
az role assignment create \
  --assignee <client-id> \
  --role AcrPush \
  --scope /subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/<acr-name>
```

#### Azure Key Vault (for application secrets)
```bash
# Create a Key Vault
az keyvault create --name <vault-name> --resource-group <rg> --location <location>

# Add secrets
az keyvault secret set --vault-name <vault-name> --name "postgres-password" --value "<password>"
az keyvault secret set --vault-name <vault-name> --name "encryption-key" --value "<key>"

# Grant access to the Service Principal
az keyvault set-policy --name <vault-name> \
  --spn <client-id> \
  --secret-permissions get list

# Or do everything via the UI
```


### 2. GitHub Configuration

#### Secrets (Settings > Secrets and variables > Actions > Secrets)

| Secret | Description | Example |
|--------|-------------|---------|
| `AZURE_CLIENT_ID` | Service Principal client ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_CLIENT_SECRET` | Service Principal client secret | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |

#### Variables (Settings > Secrets and variables > Actions > Variables)

| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_REGISTRY_NAME` | ACR name (without `.azurecr.io`) | `onyxregistry` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_TENANT_ID` | Azure AD tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_RESOURCE_GROUP` | Resource group name | `onyx-rg` |
| `AZURE_KEY_VAULT_NAME` | Key Vault name | `onyx-kv` |
| `AZURE_VM_NAME_DEV` | Dev VM name | `onyx-vm-dev` |
| `AZURE_VM_NAME_STAGING` | Staging VM name | `onyx-vm-staging` |
| `AZURE_VM_NAME_PROD` | Prod VM name | `onyx-vm-prod` |

## Usage

### Building images (automatic on tag)

Images are automatically built and pushed to ACR when a tag is created:

```bash
# Stable tag (also applies :latest)
git tag v1.0.0
git push origin v1.0.0

# Beta tag (also applies :beta)
git tag v1.0.0-beta.1
git push origin v1.0.0-beta.1

# The tag-nightly.yml workflow creates nightly tags (applies :edge)
```

### Manual deployment

Via the GitHub Actions UI or CLI:

```bash
# Deploy to dev
gh workflow run deploy.yml -f environment=dev -f image-tag=latest

# Deploy to staging
gh workflow run deploy.yml -f environment=staging -f image-tag=v1.0.0

# Deploy to prod (requires confirmation)
gh workflow run deploy.yml -f environment=prod -f image-tag=v1.0.0 -f confirm-prod=DEPLOY-PROD
```

### Initial VM setup

```bash
gh workflow run setup-vm.yml -f environment=dev
```

## Tagging logic

| Tag type | Pattern | Docker tags applied |
|----------|---------|---------------------|
| Stable | `v1.2.3` | `v1.2.3`, `latest` |
| Beta | `v1.2.3-beta.1` | `v1.2.3-beta.1`, `beta` |
| Nightly | `nightly-20240101` | `nightly-20240101`, `edge` |
| Other | `feature-xyz` | `feature-xyz` |

## Built images

| Image | Dockerfile | Description |
|-------|------------|-------------|
| `onyx-backend` | `backend/Dockerfile` | Backend API |
| `onyx-web-server` | `web/Dockerfile` | Next.js frontend |
| `onyx-model-server` | `backend/Dockerfile.model_server` | ML model server |

## Architecture

- **Target architecture**: `linux/amd64` only (no multi-arch)
- **Registry**: Azure Container Registry (ACR)
- **Deployment**: Via `az vm run-command` (no SSH)
- **Secrets**: Azure Key Vault

## VM structure

```
/opt/onyx/
├── .env                 # Configuration (ACR_REGISTRY, IMAGE_TAG, etc.)
├── docker-compose.yml   # Base composition
├── docker-compose.dev.yml
├── docker-compose.prod.yml
└── docker-compose.prod.eleven.yml
```

## Troubleshooting

### Build fails with "unauthorized"
- Verify that `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` are correct
- Verify that the Service Principal has `AcrPush` rights on the ACR

### Deployment fails with "VM not found"
- Verify that `AZURE_VM_NAME_*` matches the exact VM name
- Verify that `AZURE_RESOURCE_GROUP` is correct

### Containers do not start on the VM
```bash
# Connect to the VM and check logs
ssh user@vm-ip
cd /opt/onyx
docker compose logs -f
```

### Health check fails
- Verify that ports are open in the NSG (Network Security Group)
- Verify that the application has started: `docker compose ps`
