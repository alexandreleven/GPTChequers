"""Elasticsearch schema definition and management.

This module defines the schema for Elasticsearch indices and provides
utilities for schema validation and index settings management.

Patterns inspired by OpenSearch's DocumentSchema class.
"""

from typing import Any

from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    ACCESS_CONTROL_LIST,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BLURB
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BOOST
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    CHUNK_CONTEXT,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import CHUNK_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import CONTENT
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    CONTENT_SUMMARY,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOC_SUMMARY,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOC_UPDATED_AT,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOCUMENT_ID,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOCUMENT_SETS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import EMBEDDINGS
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import HIDDEN
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    IMAGE_FILE_NAME,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    LARGE_CHUNK_REFERENCE_IDS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import METADATA
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    METADATA_LIST,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    METADATA_SUFFIX,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    PRIMARY_OWNERS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    RECENCY_BIAS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SECONDARY_OWNERS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SECTION_CONTINUATION,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SEMANTIC_IDENTIFIER,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SKIP_TITLE_EMBEDDING,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SOURCE_LINKS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TENANT_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TITLE
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    TITLE_EMBEDDING,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    USER_PROJECT,
)
from onyx.configs.constants import SOURCE_TYPE


class ElasticsearchSchema:
    """Manages Elasticsearch schema definition and validation.

    This class provides static methods for:
    - Generating complete index mappings
    - Providing index settings
    - Validating existing indices against expected schema
    """

    @staticmethod
    def get_document_schema(vector_dimension: int, multitenant: bool) -> dict[str, Any]:
        """Returns the complete document schema for Elasticsearch indices.

        This defines the mappings for all fields used in document chunks.
        The schema is designed to support:
        - Hybrid search (keyword + vector)
        - Access control and filtering
        - Document metadata and relationships
        - Contextual RAG features

        Args:
            vector_dimension: The dimension of vector embeddings
            multitenant: Whether the index supports multitenancy

        Returns:
            A dictionary containing the mappings configuration for Elasticsearch
        """
        mappings = {
            "properties": {
                # Core document fields
                TENANT_ID: {"type": "keyword"},
                DOCUMENT_ID: {"type": "keyword"},
                CHUNK_ID: {"type": "integer"},
                BLURB: {"type": "text"},
                CONTENT: {"type": "text"},
                SOURCE_TYPE: {"type": "keyword"},
                SOURCE_LINKS: {"type": "object"},
                SEMANTIC_IDENTIFIER: {"type": "text"},
                TITLE: {"type": "text"},
                SECTION_CONTINUATION: {"type": "boolean"},
                # Vector embeddings for hybrid search
                EMBEDDINGS: {
                    "type": "dense_vector",
                    "dims": vector_dimension,
                    "index": True,
                    "similarity": "cosine",
                },
                TITLE_EMBEDDING: {
                    "type": "dense_vector",
                    "dims": vector_dimension,
                    "index": True,
                    "similarity": "cosine",
                },
                SKIP_TITLE_EMBEDDING: {"type": "boolean"},
                # Access control fields
                ACCESS_CONTROL_LIST: {
                    "type": "nested",
                    "properties": {
                        "value": {"type": "keyword"},
                        "weight": {"type": "integer"},
                    },
                },
                DOCUMENT_SETS: {
                    "type": "nested",
                    "properties": {
                        "value": {"type": "keyword"},
                        "weight": {"type": "integer"},
                    },
                },
                USER_PROJECT: {"type": "integer"},
                HIDDEN: {"type": "boolean"},
                # Document relationships and metadata
                LARGE_CHUNK_REFERENCE_IDS: {"type": "integer"},
                METADATA: {"type": "object"},
                METADATA_LIST: {"type": "keyword"},
                METADATA_SUFFIX: {"type": "keyword"},
                # Boosting and ranking fields
                BOOST: {"type": "float"},
                RECENCY_BIAS: {"type": "float"},
                DOC_UPDATED_AT: {"type": "date", "format": "epoch_second"},
                # Ownership fields
                PRIMARY_OWNERS: {"type": "keyword"},
                SECONDARY_OWNERS: {"type": "keyword"},
                # Display fields
                CONTENT_SUMMARY: {"type": "text"},
                IMAGE_FILE_NAME: {"type": "keyword"},
                # Contextual RAG fields
                DOC_SUMMARY: {"type": "text"},
                CHUNK_CONTEXT: {"type": "text"},
            }
        }

        # Remove tenant_id field if not multitenant
        if not multitenant:
            mappings["properties"].pop(TENANT_ID, None)

        return mappings

    @staticmethod
    def get_index_settings() -> dict[str, Any]:
        """Returns standard index settings for good performance.

        These settings are optimized for:
        - Reasonable indexing speed
        - Good search performance
        - Balanced resource usage

        Returns:
            A dictionary containing the settings configuration for Elasticsearch
        """
        return {
            "number_of_shards": 3,
            "number_of_replicas": 1,
            "analysis": {"analyzer": {"default": {"type": "standard"}}},
        }

    @staticmethod
    def get_bulk_index_settings() -> dict[str, Any]:
        """Returns optimized settings for bulk indexing operations.

        These settings disable refresh and reduce replicas to maximize
        indexing throughput. Should be restored to normal after bulk load.

        Returns:
            A dictionary containing optimized settings for bulk indexing
        """
        return {
            "number_of_shards": 3,
            "number_of_replicas": 0,  # No replication during bulk load
            "refresh_interval": "-1",  # Disable auto-refresh
            "analysis": {"analyzer": {"default": {"type": "standard"}}},
        }

    @staticmethod
    def validate_index_schema(
        index_name: str,
        actual_mappings: dict[str, Any],
        expected_mappings: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate that an index's schema matches expectations.

        Checks that all expected fields exist with correct types and configurations.
        This helps catch schema drift and configuration issues.

        Args:
            index_name: Name of the index being validated
            actual_mappings: The actual mappings from Elasticsearch
            expected_mappings: The expected mappings

        Returns:
            A tuple of (is_valid, error_messages)
            - is_valid: True if schema matches, False otherwise
            - error_messages: List of specific validation errors
        """
        errors = []

        # Extract the properties from actual mappings
        # Elasticsearch returns mappings in format: {index_name: {mappings: {properties: {...}}}}
        actual_props = (
            actual_mappings.get(index_name, {})
            .get("mappings", {})
            .get("properties", {})
        )
        expected_props = expected_mappings.get("properties", {})

        # Check for missing fields
        for field_name, field_config in expected_props.items():
            if field_name not in actual_props:
                errors.append(f"Missing field: {field_name}")
                continue

            # Check field type matches
            expected_type = field_config.get("type")
            actual_type = actual_props[field_name].get("type")

            if expected_type and actual_type != expected_type:
                errors.append(
                    f"Field '{field_name}' type mismatch: "
                    f"expected '{expected_type}', got '{actual_type}'"
                )

            # For dense_vector fields, check dimensions
            if expected_type == "dense_vector":
                expected_dims = field_config.get("dims")
                actual_dims = actual_props[field_name].get("dims")

                if expected_dims and actual_dims != expected_dims:
                    errors.append(
                        f"Field '{field_name}' dimensions mismatch: "
                        f"expected {expected_dims}, got {actual_dims}"
                    )

        is_valid = len(errors) == 0
        return is_valid, errors
