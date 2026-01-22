import json
import string
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from elasticsearch import Elasticsearch
from retry import retry

from eleven.onyx.document_index.elasticsearch.utils import get_elasticsearch_client
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.vespa_constants import BLURB
from onyx.document_index.vespa_constants import BOOST
from onyx.document_index.vespa_constants import CHUNK_CONTEXT
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import CONTENT_SUMMARY
from onyx.document_index.vespa_constants import DOC_SUMMARY
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import IMAGE_FILE_NAME
from onyx.document_index.vespa_constants import LARGE_CHUNK_REFERENCE_IDS
from onyx.document_index.vespa_constants import METADATA
from onyx.document_index.vespa_constants import METADATA_SUFFIX
from onyx.document_index.vespa_constants import PRIMARY_OWNERS
from onyx.document_index.vespa_constants import RECENCY_BIAS
from onyx.document_index.vespa_constants import SECONDARY_OWNERS
from onyx.document_index.vespa_constants import SECTION_CONTINUATION
from onyx.document_index.vespa_constants import SEMANTIC_IDENTIFIER
from onyx.document_index.vespa_constants import SOURCE_LINKS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TITLE
from onyx.utils.logger import setup_logger

logger = setup_logger()


@retry(tries=3, delay=1, backoff=2)
def query_elasticsearch(
    query_params: Mapping[str, Any],
) -> list[InferenceChunkUncleaned]:
    """Query Elasticsearch and convert results to InferenceChunkUncleaned objects.

    Args:
        query_params: A mapping containing:
            - index: The name of the index to query
            - dsl_query: The Elasticsearch DSL query object
            - num_to_retrieve: The number of results to retrieve
            - offset: The offset for pagination
            - _source: (optional) The _source parameter
            - knn: (optional) The knn parameter
            - rank: (optional) The rank parameter

    Returns:
        A list of InferenceChunkUncleaned objects representing the search results.
    """
    index_name = query_params["index"]

    # Build the query body
    query_body = {k: v for k, v in query_params.items() if k != "index"}

    try:
        with get_elasticsearch_client() as es_client:
            response = es_client.search(
                index=index_name,
                body=query_body,
                explain=True,
            )
            hits = response["hits"]["hits"]
    except Exception as e:
        logger.error(f"Error querying Elasticsearch: {e}")
        # Try to get the response if it exists in the exception
        if hasattr(e, "response") and e.response:
            # Log the partial response (if present)
            logger.error(f"Partial response: {e.response}")
        else:
            # No partial response, just the error
            logger.error("No partial response available.")
        raise e

    if not hits:
        logger.warning(f"No hits found for query: {query_body}")

    for hit in hits:
        if hit["_source"].get(CONTENT) is None:
            identifier = hit["_source"].get("documentid") or hit["_id"]
            logger.error(
                f"Elasticsearch Index with Elasticsearch ID {identifier} has no contents. "
                f"This is invalid because the vector is not meaningful and keywordsearch cannot "
                f"fetch this document"
            )

    filtered_hits = [hit for hit in hits if hit["_source"].get(CONTENT) is not None]
    inference_chunks = [
        _elasticsearch_hit_to_inference_chunk(hit) for hit in filtered_hits
    ]
    return inference_chunks


def _process_dynamic_summary(
    dynamic_summary: str, max_summary_length: int = 400
) -> list[str]:
    if not dynamic_summary:
        return []

    current_length = 0
    processed_summary: list[str] = []
    for summary_section in dynamic_summary.split("<sep />"):
        # if we're past the desired max length, break at the last word
        if current_length + len(summary_section) >= max_summary_length:
            summary_section = summary_section[: max_summary_length - current_length]
            summary_section = summary_section.lstrip()  # remove any leading whitespace

            # handle the case where the truncated section is either just a
            # single (partial) word or if it's empty
            first_space = summary_section.find(" ")
            if first_space == -1:
                # add ``...`` to previous section
                if processed_summary:
                    processed_summary[-1] += "..."
                break

            # handle the valid truncated section case
            summary_section = summary_section.rsplit(" ", 1)[0]
            if summary_section[-1] in string.punctuation:
                summary_section = summary_section[:-1]
            summary_section += "..."
            processed_summary.append(summary_section)
            break

        processed_summary.append(summary_section)
        current_length += len(summary_section)

    return processed_summary


def _elasticsearch_hit_to_inference_chunk(
    hit: dict[str, Any], null_score: bool = False
) -> InferenceChunkUncleaned:
    fields = cast(dict[str, Any], hit["_source"])

    # parse fields that are stored as strings, but are really json / datetime
    metadata = fields.get(METADATA, {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse metadata JSON string: {metadata}")
            metadata = {}
    elif not isinstance(metadata, dict):
        logger.error(f"Unexpected metadata type: {type(metadata)}")
        metadata = {}

    updated_at = (
        datetime.fromtimestamp(fields[DOC_UPDATED_AT], tz=timezone.utc)
        if DOC_UPDATED_AT in fields
        else None
    )
    match_highlights = _process_dynamic_summary(
        # fallback to regular `content` if the `content_summary` field
        # isn't present
        dynamic_summary=hit["_source"].get(CONTENT_SUMMARY, hit["_source"][CONTENT]),
    )
    semantic_identifier = fields.get(SEMANTIC_IDENTIFIER, "")
    if not semantic_identifier:
        logger.error(
            f"Chunk with blurb: {fields.get(BLURB, 'Unknown')[:50]}... has no Semantic Identifier"
        )

    source_links = fields.get(SOURCE_LINKS, {})
    source_links_dict_unprocessed = (
        json.loads(source_links) if isinstance(source_links, str) else source_links
    )
    source_links_dict = {
        int(k): v
        for k, v in cast(dict[str, str], source_links_dict_unprocessed).items()
    }

    return InferenceChunkUncleaned(
        chunk_id=fields[CHUNK_ID],
        blurb=fields.get(BLURB, ""),  # Unused
        content=fields[CONTENT],  # Includes extra title prefix and metadata suffix
        source_links=source_links_dict or {0: ""},
        section_continuation=fields[SECTION_CONTINUATION],
        document_id=fields[DOCUMENT_ID],
        source_type=fields[SOURCE_TYPE],
        # Still called `image_file_name` for backwards compatibility with Vespa
        image_file_id=fields.get(IMAGE_FILE_NAME),
        title=fields.get(TITLE),
        semantic_identifier=fields[SEMANTIC_IDENTIFIER],
        boost=fields.get(BOOST, 1),
        recency_bias=fields.get("matchfeatures", {}).get(RECENCY_BIAS, 1.0),
        score=None if null_score else hit.get("_score", 0),
        hidden=fields.get(HIDDEN, False),
        primary_owners=fields.get(PRIMARY_OWNERS),
        secondary_owners=fields.get(SECONDARY_OWNERS),
        large_chunk_reference_ids=fields.get(LARGE_CHUNK_REFERENCE_IDS, []),
        metadata=metadata,
        metadata_suffix=fields.get(METADATA_SUFFIX),
        doc_summary=fields.get(DOC_SUMMARY, ""),
        chunk_context=fields.get(CHUNK_CONTEXT, ""),
        match_highlights=match_highlights,
        updated_at=updated_at,
    )


def individual_id_retrieval(
    index_name: str,
    chunk_requests: list[VespaChunkRequest],
    filter_clauses: list[dict],
    es_client: Elasticsearch,
) -> list[InferenceChunkUncleaned]:
    """Retrieve document chunks individually

    This method retrieves each document chunk with a separate query.
    It's more suitable for a small number of documents.

    Args:
        index_name: The name of the Elasticsearch index
        chunk_requests: List of document chunk requests
        filter_clauses: Elasticsearch filter clauses
        es_client: Elasticsearch client instance

    Returns:
        List of retrieved document chunks as InferenceChunkUncleaned objects
    """
    results = []

    # Process each request individually
    for request in chunk_requests:
        try:
            # Create a bool query with must and filter clauses
            query = {
                "bool": {
                    "must": {"term": {"document_id": request.document_id}},
                    "filter": filter_clauses,
                }
            }

            response = es_client.search(
                index=index_name,
                body={"query": query},
                size=100,  # Limit to 100 chunks per document
            )

            # Process hits
            for hit in response["hits"]["hits"]:
                source = hit["_source"]

                # Check if we need to filter by chunk range
                if (
                    request.min_chunk_ind is not None
                    or request.max_chunk_ind is not None
                ):
                    chunk_id = int(source.get(CHUNK_ID, 0))

                    # Skip if chunk_id is outside the requested range
                    if (
                        request.min_chunk_ind is not None
                        and chunk_id < request.min_chunk_ind
                    ) or (
                        request.max_chunk_ind is not None
                        and chunk_id > request.max_chunk_ind
                    ):
                        continue

                # Convert to InferenceChunkUncleaned
                chunk = _elasticsearch_hit_to_inference_chunk(hit, null_score=True)
                if chunk:
                    results.append(chunk)

        except Exception as e:
            logger.error(f"Error retrieving document {request.document_id}: {str(e)}")
            # Continue with other requests even if one fails

    return results


def batch_id_retrieval(
    index_name: str,
    chunk_requests: list[VespaChunkRequest],
    filter_clauses: list[dict],
    es_client: Elasticsearch,
) -> list[InferenceChunkUncleaned]:
    """Retrieve document chunks in batch

    This method combines multiple document ID requests into a single query
    for better performance when retrieving many documents.

    Args:
        index_name: The name of the Elasticsearch index
        chunk_requests: List of document chunk requests
        filter_clauses: Elasticsearch filter clauses
        es_client: Elasticsearch client instance

    Returns:
        List of retrieved document chunks as InferenceChunkUncleaned objects
    """
    # Maximum number of terms in a terms query
    MAX_TERMS = 1000
    results = []

    # Process requests in batches
    for i in range(0, len(chunk_requests), MAX_TERMS):
        batch = chunk_requests[i : i + MAX_TERMS]
        doc_ids = [request.document_id for request in batch]

        try:
            # Create a bool query with terms and filter clauses
            query = {
                "bool": {
                    "must": {"terms": {"document_id": doc_ids}},
                    "filter": filter_clauses,
                }
            }

            response = es_client.search(
                index=index_name,
                body={"query": query},
                size=1000,  # Increased size for batch retrieval
            )

            # Process hits
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                doc_id = source.get(DOCUMENT_ID)
                chunk_id = int(source.get(CHUNK_ID, 0))

                # Find the corresponding request to check chunk range
                matching_requests = [req for req in batch if req.document_id == doc_id]
                if not matching_requests:
                    continue

                # Check if we need to filter by chunk range
                for request in matching_requests:
                    if (
                        request.min_chunk_ind is not None
                        and chunk_id < request.min_chunk_ind
                    ) or (
                        request.max_chunk_ind is not None
                        and chunk_id > request.max_chunk_ind
                    ):
                        continue

                    # Convert to InferenceChunkUncleaned
                    chunk = _elasticsearch_hit_to_inference_chunk(hit, null_score=True)
                    if chunk:
                        results.append(chunk)
                        break  # Break once we've added this chunk

        except Exception as e:
            logger.error(f"Error in batch retrieval: {str(e)}")
            # Fall back to individual retrieval for this batch
            individual_results = individual_id_retrieval(
                index_name=index_name,
                chunk_requests=batch,
                filter_clauses=filter_clauses,
                es_client=es_client,
            )
            results.extend(individual_results)

    return results
