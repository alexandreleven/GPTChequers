import logging
from typing import List
from uuid import UUID

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

logger = logging.getLogger(__name__)


def delete_elasticsearch_chunks_bulk(
    doc_chunk_ids: List[UUID],
    index_name: str,
    es_client: Elasticsearch = None,
) -> None:
    """
    Delete multiple document chunks from Elasticsearch using bulk API.
    This is more efficient than individual deletions for large numbers of documents.

    Args:
        doc_chunk_ids: List of document chunk UUIDs to delete
        index_name: Name of the index
        es_client: Elasticsearch client (optional, will create one if not provided)
    """
    if not doc_chunk_ids:
        logger.debug("No chunks to delete")
        return

    # Prepare bulk deletion actions for helpers.bulk
    bulk_actions = []
    for doc_chunk_id in doc_chunk_ids:
        bulk_actions.append(
            {"_op_type": "delete", "_index": index_name, "_id": str(doc_chunk_id)}
        )

    # Execute bulk deletion
    if bulk_actions:
        try:
            success, errors = bulk(
                client=es_client,
                actions=bulk_actions,
                refresh=True,
                raise_on_error=False,
                stats_only=False,
            )

            # Log only if there are errors
            if errors:
                logger.error(f"Failed to delete {len(errors)} documents")
        except Exception as e:
            logger.error(f"Bulk deletion failed: {str(e)}")
            raise
