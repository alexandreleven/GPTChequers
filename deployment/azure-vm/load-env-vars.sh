#!/usr/bin/env bash

# set -euo pipefail

###########################################
# Script: load-env-vars.sh
# Purpose:
#   Load secrets from an Azure Key Vault and expose them as environment variables in the current shell (via source).
#
# Constraints:
#   - Secrets are never written to disk.
#   - Assumes `az` (Azure CLI) is installed and authenticated (az login, managed identity, etc.).
#
# Typical usage:
#   source /path/to/load-env-vars.sh /path/to/.env-vars-backend.conf (or web)
#
# The .conf file lists environment variable names (e.g. OPENID_CONFIG_URL, one per line); comments (#) and empty lines are ignored.
# These names are converted to Key Vault secret names (e.g. openid-config-url) and fetched, then exported with the original env var name.
#
# Docker / docker-compose integration:
#   source /app/load-env-vars.sh /app/.env-vars-backend.conf
#   - Exports are in memory only for the current process.
###########################################

if ! command -v az >/dev/null 2>&1; then
  echo "Error: Azure CLI 'az' is not installed or not found in PATH." >&2
  exit 1
fi

# Authenticate with Azure (managed identity on VM, or use mounted credentials in local dev)
az login --identity
az acr login --name "$ACR_NAME"

# Convert env var name (e.g. OAUTH_CLIENT_ID) to Key Vault secret name (e.g. oauth-client-id)
env_name_to_keyvault_secret() {
  local env_name="$1"
  echo "${env_name,,}" | tr '_' '-'
}

load_one_secret() {
  local env_var_name="$1"

  # Convert env var name (e.g. OPENID_CONFIG_URL) to Key Vault secret name (e.g. openid-config-url)
  local secret_name
  secret_name="$(env_name_to_keyvault_secret "$env_var_name")"

  # Fetch secret value from Azure Key Vault (never written to disk)
  local value
  if ! value="$(az keyvault secret show \
      --vault-name "$AZURE_KEY_VAULT_NAME" \
      --name "$secret_name" \
      --query value -o tsv 2>/dev/null)"; then
    echo "Warning: could not retrieve secret '$secret_name' (for env var '$env_var_name') from Key Vault '$AZURE_KEY_VAULT_NAME'." >&2
    return 1
  fi

  if [[ -z "${value}" ]]; then
    echo "Warning: secret '$secret_name' (for env var '$env_var_name') is empty, no environment variable set." >&2
    return 0
  fi

  # Export in memory only for the current shell. Never log the value.
  export "$env_var_name"="$value"

  echo "Secret '$secret_name' loaded as environment variable '$env_var_name'." >&2
}

# Get .conf file path from first argument
conf_file="${1:?Usage: source load-env-vars.sh <path-to-.conf>}"

if [[ ! -f "$conf_file" ]]; then
  echo "Error: config file '$conf_file' not found." >&2
  exit 1
fi

# Read .conf file line by line and load each secret
while IFS= read -r env_var_name; do
  # Strip comments (everything after #) and trim whitespace
  env_var_name="${env_var_name%%#*}"
  env_var_name="${env_var_name// /}"
  # Skip empty lines
  [[ -z "$env_var_name" ]] && continue
  # Load this secret from Key Vault (converting env var name to Key Vault secret name)
  load_one_secret "$env_var_name"
done < "$conf_file"