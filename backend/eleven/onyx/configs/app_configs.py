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
METADATA_TO_INCLUDE = [
    # Core identification
    "notion_name",
    "notion_type",
    "notion_client",
    # Business context
    "notion_business_issue",
    "notion_key_business_concepts",
    "notion_industry_macro",
    # Additional context
    "notion_person",
    "notion_date",
    "notion_stack",
    "notion_tech_enablers",
    "notion_assignements",
    # SharePoint metadata
    "sharepoint_drive",
    "sharepoint_file_extension",
]
