#!/usr/bin/env python3
"""
Script: load-env-vars-managed-identity.py
Purpose: Load secrets from Azure Key Vault and output shell export commands.
         Uses Managed Identity only (for use on Azure VM with assigned identity).

Usage:
    eval $(python load-env-vars-managed-identity.py backend)
    eval $(python load-env-vars-managed-identity.py web)

The script uses Azure Managed Identity for authentication (no az login needed).
Secrets are never written to disk or logged.
"""

import os
import sys

from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient

# Hardcoded secret lists
BACKEND_SECRETS = [
    "OPENID_CONFIG_URL",
    "OAUTH_CLIENT_ID",
    "DB_READONLY_USER",
    "POSTGRES_USER",
    "ELASTICSEARCH_CLOUD_URL",
    "DB_READONLY_PASSWORD",
    "ELASTICSEARCH_API_KEY",
    "GEN_AI_API_KEY_AZURE",
    "OAUTH_CLIENT_SECRET",
    "POSTGRES_PASSWORD",
]

WEB_SECRETS = [
    "OPENID_CONFIG_URL",
    "OAUTH_CLIENT_ID",
]


def env_name_to_keyvault_secret(env_name: str) -> str:
    """Convert env var name (e.g. OAUTH_CLIENT_ID) to Key Vault secret name (e.g. oauth-client-id)."""
    return env_name.lower().replace("_", "-")


def shell_escape(value: str) -> str:
    """Escape a value for safe use in shell single quotes."""
    return value.replace("'", "'\"'\"'")


def load_secrets(secret_list: list[str], vault_name: str) -> None:
    """Load secrets from Key Vault and print export commands."""
    vault_url = f"https://{vault_name}.vault.azure.net"

    try:
        credential = ManagedIdentityCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
    except Exception as e:
        print(
            f"# Error: Failed to initialize Azure Key Vault client: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    for env_var_name in secret_list:
        secret_name = env_name_to_keyvault_secret(env_var_name)

        try:
            secret = client.get_secret(secret_name)
            value = secret.value

            if value:
                # Output export command (value is shell-escaped)
                escaped_value = shell_escape(value)
                print(f"export {env_var_name}='{escaped_value}'")
                print(f"# Loaded {secret_name} as {env_var_name}", file=sys.stderr)
            else:
                print(f"# Warning: secret '{secret_name}' is empty", file=sys.stderr)

        except Exception as e:
            print(
                f"# Warning: could not retrieve secret '{secret_name}' for '{env_var_name}': {e}",
                file=sys.stderr,
            )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("backend", "web"):
        print(
            "Usage: python load-env-vars-managed-identity.py <backend|web>",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]

    vault_name = os.environ.get("AZURE_KEY_VAULT_NAME")
    if not vault_name:
        print(
            "# Error: AZURE_KEY_VAULT_NAME environment variable not set",
            file=sys.stderr,
        )
        sys.exit(1)

    secret_list = BACKEND_SECRETS if mode == "backend" else WEB_SECRETS

    load_secrets(secret_list, vault_name)


if __name__ == "__main__":
    main()
