import uuid
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from retry import retry

from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    ACCESS_CONTROL_LIST,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BLURB
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BOOST
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import CHUNK_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import CONTENT
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    CONTENT_SUMMARY,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOC_UPDATED_AT,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import DOCUMENT_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOCUMENT_SETS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import EMBEDDINGS
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import HIDDEN
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
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import SOURCE_TYPE
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TENANT_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TITLE
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    TITLE_EMBEDDING,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.document_index.document_index_utils import get_uuid_from_chunk
from onyx.document_index.document_index_utils import get_uuid_from_chunk_info_old
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.vespa.shared_utils.utils import (
    remove_invalid_unicode_chars,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _elasticsearch_get_updated_at_attribute(t: datetime | None) -> int:
    # NOTE this differs from the vespa implementation in that we don't return None
    # because queries are failing when the field is missing
    if not t:
        return int(datetime.now(timezone.utc).timestamp())
    if t.tzinfo != timezone.utc:
        raise ValueError("Connectors must provide document update time in UTC")
    return int(t.timestamp())


def prepare_elasticsearch_document(
    chunk: DocMetadataAwareIndexChunk,
    index_name: str,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """
    Prepare a document for indexing in Elasticsearch from a chunk.

    Args:
        chunk: The chunk to prepare for indexing
        index_name: The name of the Elasticsearch index
        tenant_id: Optional tenant ID for multi-tenant setups

    Returns:
        A dictionary with the document fields ready for Elasticsearch indexing
    """
    document = chunk.source_document
    title = document.semantic_identifier if document.semantic_identifier else None

    # Generate UUID for the document
    chunk_uuid = str(get_uuid_from_chunk(chunk))

    embeddings = chunk.embeddings

    # TODO mini chunk can't be passed as fields in a document
    # We need to workaround to pass mini chunks in multiple documents
    embeddings_name_vector_map = {"full_chunk": embeddings.full_embedding}

    if embeddings.mini_chunk_embeddings:
        for ind, m_c_embed in enumerate(embeddings.mini_chunk_embeddings):
            embeddings_name_vector_map[f"mini_chunk_{ind}"] = m_c_embed

    title = document.get_title_for_document_index()

    # Format access control list as nested objects with value and weight
    access_control_list = []
    if hasattr(chunk, "access") and chunk.access:
        acl_items = chunk.access.to_acl()
        for acl_item in acl_items:
            if acl_item:  # Skip empty strings
                access_control_list.append(
                    {"value": acl_item, "weight": 1}  # Default weight
                )

    # If access_control_list is empty, add a default entry to avoid Elasticsearch errors
    if not access_control_list:
        access_control_list = [{"value": "default", "weight": 1}]

    # Format document sets as nested objects with value and weight
    document_sets = []
    if hasattr(chunk, "document_sets") and chunk.document_sets:
        for doc_set in chunk.document_sets:
            if doc_set:  # Skip empty strings
                document_sets.append({"value": doc_set, "weight": 1})  # Default weight

    else:
        document_sets = []

    # Prepare the document fields
    es_document = {
        "_index": index_name,
        "_id": str(chunk_uuid),
        "_source": {
            DOCUMENT_ID: document.id,
            CHUNK_ID: chunk.chunk_id,
            BLURB: remove_invalid_unicode_chars(chunk.blurb) if chunk.blurb else "",
            TITLE: remove_invalid_unicode_chars(title) if title else "",
            SKIP_TITLE_EMBEDDING: not title,
            CONTENT: remove_invalid_unicode_chars(
                f"{chunk.title_prefix or ''}{chunk.content or ''}{chunk.metadata_suffix_keyword or ''}"
            ),
            CONTENT_SUMMARY: (
                remove_invalid_unicode_chars(chunk.content) if chunk.content else ""
            ),
            SOURCE_TYPE: str(document.source.value),
            SOURCE_LINKS: chunk.source_links,
            SEMANTIC_IDENTIFIER: remove_invalid_unicode_chars(
                document.semantic_identifier if document.semantic_identifier else ""
            ),
            SECTION_CONTINUATION: bool(chunk.section_continuation),
            LARGE_CHUNK_REFERENCE_IDS: (
                chunk.large_chunk_reference_ids
                if isinstance(chunk.large_chunk_reference_ids, list)
                else []
            ),
            METADATA: document.metadata,
            METADATA_LIST: (
                chunk.source_document.get_metadata_str_attributes()
                if chunk.source_document.get_metadata_str_attributes()
                else ""
            ),
            METADATA_SUFFIX: chunk.metadata_suffix_keyword,
            EMBEDDINGS: chunk.embeddings.full_embedding,
            TITLE_EMBEDDING: chunk.title_embedding,
            DOC_UPDATED_AT: _elasticsearch_get_updated_at_attribute(
                document.doc_updated_at
            ),
            PRIMARY_OWNERS: get_experts_stores_representations(document.primary_owners)
            or [],
            SECONDARY_OWNERS: get_experts_stores_representations(
                document.secondary_owners
            )
            or [],
            ACCESS_CONTROL_LIST: access_control_list,
            DOCUMENT_SETS: document_sets,
            BOOST: (
                float(chunk.boost)
                if hasattr(chunk, "boost") and chunk.boost is not None
                else 1.0
            ),
            HIDDEN: bool(chunk.hidden) if hasattr(chunk, "hidden") else False,
        },
    }

    # Add tenant ID if provided
    if tenant_id:
        es_document["_source"][TENANT_ID] = tenant_id

    return es_document


@retry(tries=3, delay=1, backoff=2)
def _does_doc_chunk_exist(
    doc_chunk_id: uuid.UUID, index_name: str, es_client: Elasticsearch
) -> bool:
    """
    Check if a document chunk exists in Elasticsearch.

    Args:
        doc_chunk_id: UUID of the document chunk
        index_name: Name of the Elasticsearch index
        es_client: Elasticsearch client instance

    Returns:
        True if the document exists, False otherwise
    """
    try:
        # Use Elasticsearch's exists API to check if document exists
        return es_client.exists(index=index_name, id=str(doc_chunk_id))
    except Exception as e:
        logger.debug(f"Failed to check for document with ID {doc_chunk_id}: {e}")
        raise RuntimeError(
            f"Unexpected error checking document existence in Elasticsearch: "
            f"error={str(e)} "
            f"index={index_name} "
            f"doc_chunk_id={doc_chunk_id}"
        )


def check_for_final_chunk_existence(
    minimal_doc_info: MinimalDocumentIndexingInfo,
    start_index: int,
    index_name: str,
    es_client: Elasticsearch,
) -> int:
    """
    Find the next available chunk index for a document.

    This function checks for the existence of document chunks starting from start_index
    and returns the first index that doesn't exist.

    Args:
        minimal_doc_info: Basic document information
        start_index: Index to start checking from
        index_name: Name of the Elasticsearch index
        es_client: Elasticsearch client instance

    Returns:
        The first chunk index that doesn't exist
    """
    index = start_index
    while True:
        doc_chunk_id = get_uuid_from_chunk_info_old(
            document_id=minimal_doc_info.doc_id,
            chunk_id=index,
            large_chunk_reference_ids=[],
        )
        if not _does_doc_chunk_exist(doc_chunk_id, index_name, es_client):
            return index
        index += 1


def batch_index_elasticsearch_chunks(
    chunks: List[DocMetadataAwareIndexChunk],
    index_name: str,
    es_client: Elasticsearch,
    tenant_id: str | None = None,
) -> List[str]:
    """
    Index a batch of chunks into Elasticsearch using bulk API.

    Args:
        chunks: List of chunks to index
        index_name: Name of the Elasticsearch index
        es_client: Elasticsearch client
        tenant_id: Optional tenant ID for multi-tenant setups

    Returns:
        List of document IDs that were successfully indexed
    """
    if not chunks:
        return {"success": [], "failed": {}}

    bulk_actions = []
    chunk_id_map = {}  # Maps action _id to original chunk ID

    for chunk in chunks:
        try:
            doc_data = prepare_elasticsearch_document(
                chunk=chunk, index_name=index_name, tenant_id=tenant_id
            )
            action = {
                "_op_type": "index",
                "_index": index_name,
                "_id": doc_data["_id"],
                "_source": doc_data["_source"],
            }
            bulk_actions.append(action)
            chunk_id_map[doc_data["_id"]] = chunk.source_document.id
        except Exception as e:
            logger.exception(
                f"Error preparing document {chunk.source_document.id}: {e}"
            )

    if not bulk_actions:
        return {"success": [], "failed": {}}

    try:
        success, errors = bulk(
            client=es_client,
            actions=bulk_actions,
            refresh=True,
            raise_on_error=False,
            stats_only=False,
        )

        failed_documents = {}
        if errors:
            for error in errors:
                if "index" in error and "_id" in error["index"]:
                    error_id = error["index"]["_id"]
                    error_reason = error["index"].get("error", "Unknown error")
                    failed_documents[chunk_id_map.get(error_id, error_id)] = (
                        error_reason
                    )
                    logger.error(f"Failed to index document {error_id}: {error_reason}")

        successful_ids = [
            chunk_id_map[_id] for _id in chunk_id_map if _id not in failed_documents
        ]
        return successful_ids, failed_documents

    except Exception:
        logger.exception("Bulk indexing failed.")
        raise
