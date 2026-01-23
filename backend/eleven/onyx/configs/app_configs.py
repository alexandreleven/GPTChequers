"""Eleven Onyx application configuration."""

import os

from eleven.onyx.configs.constants import DocumentIndexType

DOCUMENT_INDEX_TYPE = os.environ.get(
    "DOCUMENT_INDEX_TYPE", DocumentIndexType.COMBINED.value
)

ELASTICSEARCH_CLOUD_URL = os.environ.get("ELASTICSEARCH_CLOUD_URL", None)
ELASTICSEARCH_API_KEY = os.environ.get("ELASTICSEARCH_API_KEY", None)
ELASTICSEARCH_REQUEST_TIMEOUT = os.environ.get("ELASTICSEARCH_REQUEST_TIMEOUT", 120)
MANAGED_ELASTICSEARCH = os.environ.get("MANAGED_ELASTICSEARCH", "").lower() == "true"

# Metadata keys to include during document indexing
NOTION_METADATA_TO_INCLUDE = os.environ.get("NOTION_METADATA_TO_INCLUDE", "")
