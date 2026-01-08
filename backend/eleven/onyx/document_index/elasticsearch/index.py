import time
from uuid import UUID

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from sqlalchemy.orm import Session

from eleven.onyx.document_index.elasticsearch.chunk_retrieval import batch_id_retrieval
from eleven.onyx.document_index.elasticsearch.chunk_retrieval import (
    individual_id_retrieval,
)
from eleven.onyx.document_index.elasticsearch.chunk_retrieval import query_elasticsearch
from eleven.onyx.document_index.elasticsearch.deletion import (
    delete_elasticsearch_chunks_bulk,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    ACCESS_CONTROL_LIST,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BOOST
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOCUMENT_SETS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    ELASTICSEARCH_BATCH_SIZE,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import EMBEDDINGS
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import HIDDEN
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    INDEX_SETTINGS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    MAPPING_TEMPLATE,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    NUM_CANDIDATES,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    NUM_RETURNED_HITS,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    TITLE_EMBEDDING,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    USER_PROJECT,
)
from eleven.onyx.document_index.elasticsearch.indexing_utils import (
    batch_index_elasticsearch_chunks,
)
from eleven.onyx.document_index.elasticsearch.indexing_utils import (
    check_for_final_chunk_existence,
)
from eleven.onyx.document_index.elasticsearch.shared_utils.elasticsearch_request_builders import (
    build_admin_search_query,
)
from eleven.onyx.document_index.elasticsearch.shared_utils.elasticsearch_request_builders import (
    build_elastic_filters,
)
from eleven.onyx.document_index.elasticsearch.shared_utils.elasticsearch_request_builders import (
    build_random_search_query,
)
from eleven.onyx.document_index.elasticsearch.utils import (
    get_elasticsearch_client,
)
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.document_index_utils import (
    get_document_chunk_ids,
)
from onyx.document_index.interfaces import DocMetadataAwareIndexChunk
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentInsertionRecord
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.interfaces import UpdateRequest
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger()


class ElasticsearchIndex(DocumentIndex):
    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        large_chunks_enabled: bool,
        secondary_large_chunks_enabled: bool | None,
        multitenant: bool = False,
        es_client: Elasticsearch | None = None,
    ) -> None:
        self.index_name = index_name
        self.secondary_index_name = secondary_index_name

        self.large_chunks_enabled = large_chunks_enabled
        self.secondary_large_chunks_enabled = secondary_large_chunks_enabled

        self.multitenant = multitenant

        if es_client:
            self.es_client = es_client
        else:
            self.es_client = get_elasticsearch_client()
        self.multitenant = multitenant

        self.index_to_large_chunks_enabled: dict[str, bool] = {}
        self.index_to_large_chunks_enabled[index_name] = large_chunks_enabled
        if secondary_index_name and secondary_large_chunks_enabled:
            self.index_to_large_chunks_enabled[secondary_index_name] = (
                secondary_large_chunks_enabled
            )

    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,
        secondary_index_embedding_precision: EmbeddingPrecision | None,
    ) -> None:
        """Create Elasticsearch indices if they don't exist"""
        # Basic index mapping
        mapping = MAPPING_TEMPLATE.copy()
        mapping["mappings"]["properties"][EMBEDDINGS]["dims"] = primary_embedding_dim
        mapping["mappings"]["properties"][TITLE_EMBEDDING][
            "dims"
        ] = primary_embedding_dim

        # Integrate index settings with mapping
        index_config = {**INDEX_SETTINGS, **mapping}

        # Create primary index if it doesn't exist
        if not self.es_client.indices.exists(index=self.index_name):
            self.es_client.indices.create(index=self.index_name, body=index_config)
            logger.info(f"Created primary index: {self.index_name}")

        # Create secondary index if specified
        if self.secondary_index_name and secondary_index_embedding_dim:
            secondary_mapping = mapping.copy()
            secondary_mapping["mappings"]["properties"][EMBEDDINGS][
                "dims"
            ] = secondary_index_embedding_dim

            # Integrate index settings with secondary mapping
            secondary_index_config = {**INDEX_SETTINGS, **secondary_mapping}

            if not self.es_client.indices.exists(index=self.secondary_index_name):
                self.es_client.indices.create(
                    index=self.secondary_index_name, body=secondary_index_config
                )
                logger.info(f"Created secondary index: {self.secondary_index_name}")

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
    ) -> None:
        """Register multitenant indices"""
        # Implementation for multitenancy would go here

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[DocumentInsertionRecord]:
        """Index document chunks into Elasticsearch"""

        doc_id_to_previous_chunk_cnt = index_batch_params.doc_id_to_previous_chunk_cnt
        doc_id_to_new_chunk_cnt = index_batch_params.doc_id_to_new_chunk_cnt
        tenant_id = index_batch_params.tenant_id
        large_chunks_enabled = index_batch_params.large_chunks_enabled

        # needed so the final DocumentInsertionRecord returned can have the original document ID
        new_document_id_to_original_document_id: dict[str, str] = {}
        for ind, chunk in enumerate(chunks):
            old_chunk = chunks[ind]
            new_document_id_to_original_document_id[chunk.source_document.id] = (
                old_chunk.source_document.id
            )

        existing_docs: set[str] = set()
        enriched_doc_infos: list[EnrichedDocumentIndexingInfo] = [
            ElasticsearchIndex.enrich_basic_chunk_info(
                index_name=self.index_name,
                document_id=doc_id,
                previous_chunk_count=doc_id_to_previous_chunk_cnt.get(doc_id),
                new_chunk_count=doc_id_to_new_chunk_cnt.get(doc_id, 0),
                es_client=self.es_client,
            )
            for doc_id in doc_id_to_new_chunk_cnt.keys()
        ]

        for cleaned_doc_info in enriched_doc_infos:
            # If the document has previously indexed chunks, we know it previously existed
            if cleaned_doc_info.chunk_end_index:
                existing_docs.add(cleaned_doc_info.doc_id)

        # Get the list of chunks that need to be deleted
        chunks_to_delete = get_document_chunk_ids(
            enriched_document_info_list=enriched_doc_infos,
            tenant_id=tenant_id,
            large_chunks_enabled=large_chunks_enabled,
        )

        # Delete chunks that are no longer needed
        if chunks_to_delete:
            logger.info(f"Deleting {len(chunks_to_delete)} old chunks")
            delete_elasticsearch_chunks_bulk(
                doc_chunk_ids=chunks_to_delete,
                index_name=self.index_name,
                es_client=self.es_client,
            )

        logger.info(f"Starting to index {len(chunks)} chunks into Elasticsearch")

        for batch_idx, chunk_batch in enumerate(
            batch_generator(chunks, ELASTICSEARCH_BATCH_SIZE)
        ):
            logger.info(f"Processing batch {batch_idx + 1}/{ELASTICSEARCH_BATCH_SIZE}")
            batch_index_elasticsearch_chunks(
                chunks=chunk_batch,
                index_name=self.index_name,
                es_client=self.es_client,
                tenant_id=tenant_id,
            )

            # Add small delay between batches to avoid rate limiting
            if batch_idx < ELASTICSEARCH_BATCH_SIZE - 1:  # Don't sleep after last batch
                time.sleep(0.5)  # 500ms delay between batches

        all_cleaned_doc_ids = {chunk.source_document.id for chunk in chunks}

        # Refresh index to make documents immediately available for search
        try:
            self.es_client.indices.refresh(index=self.index_name)
        except Exception as e:
            logger.warning(f"Error refreshing index: {str(e)}")

        return {
            DocumentInsertionRecord(
                document_id=new_document_id_to_original_document_id[cleaned_doc_id],
                already_existed=cleaned_doc_id in existing_docs,
            )
            for cleaned_doc_id in all_cleaned_doc_ids
        }

    def _prepare_update_body(
        self,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> dict:
        """Prepare the update body for document chunk updates"""
        update_body = {}

        if fields is not None:
            if fields.boost is not None:
                update_body[BOOST] = fields.boost

            # Format document sets as nested objects with value and weight
            if fields.document_sets is not None:
                document_sets = []
                if fields.document_sets:  # Check if not empty
                    for doc_set in fields.document_sets:
                        document_sets.append(
                            {"value": doc_set, "weight": 1}  # Default weight
                        )
                update_body[DOCUMENT_SETS] = document_sets

            # Format access control list as nested objects with value and weight
            if fields.access is not None:
                access_control_list = []
                if fields.access:  # Check if not None
                    acl_items = fields.access.to_acl()
                    if acl_items:  # Check if not empty
                        for acl_item in acl_items:
                            access_control_list.append(
                                {"value": acl_item, "weight": 1}  # Default weight
                            )
                update_body[ACCESS_CONTROL_LIST] = access_control_list

            if fields.hidden is not None:
                update_body[HIDDEN] = fields.hidden

        if user_fields is not None:
            if user_fields.user_projects is not None:
                update_body[USER_PROJECT] = user_fields.user_projects

        if not update_body:
            logger.error("Update request received but nothing to update.")
            return {}

        return update_body

    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> None:
        """Update a single document's fields we do not follow the same logic as Vespa"""
        # NOTE we choose to use bulk update as we assume only few chunks would be updated each time,
        # a more scalable approach could be to use the update by query API

        if fields is None and user_fields is None:
            logger.warning(
                f"Tried to update document {doc_id} with no updated fields or user fields."
            )
            return

        update_body = self._prepare_update_body(fields, user_fields)

        doc_chunk_ids = []
        for (
            index_name,
            large_chunks_enabled,
        ) in self.index_to_large_chunks_enabled.items():
            enriched_doc_infos = ElasticsearchIndex.enrich_basic_chunk_info(
                index_name=index_name,
                document_id=doc_id,
                previous_chunk_count=chunk_count,
                new_chunk_count=0,
                es_client=self.es_client,
            )

            doc_chunk_ids.extend(
                get_document_chunk_ids(
                    enriched_document_info_list=[enriched_doc_infos],
                    tenant_id=tenant_id,
                    large_chunks_enabled=large_chunks_enabled,
                )
            )

        if update_body:
            actions = [
                {
                    "_op_type": "update",
                    "_index": index_name,
                    "_id": str(chunk_id),
                    "doc": update_body,  # Partial update
                }
                for chunk_id in doc_chunk_ids
            ]

            try:
                success, failed = bulk(self.es_client, actions)
                logger.info(f"Successfully updated {success} documents.")
                if failed:
                    logger.error(f"Failed to update {len(failed)} documents.")
            except Exception as e:
                logger.error(f"Bulk update failed: {str(e)}")

    def update(self, update_requests: list[UpdateRequest], *, tenant_id: str) -> None:
        """Update multiple documents"""
        for request in update_requests:
            for doc_info in request.minimal_document_indexing_info:
                self.update_single(
                    doc_info.doc_id,
                    tenant_id=tenant_id,
                    chunk_count=None,
                    fields=VespaDocumentFields(
                        boost=request.boost,
                        hidden=request.hidden,
                        document_sets=request.document_sets,
                        access=request.access,
                    ),
                    user_fields=None,
                )

    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        """Delete a single document's chunks"""
        # NOTE we choose to use bulk delete as we assume only few chunks would be deleted each time,
        # a more scalable approach could be to use the delete by query API
        doc_chunk_count = 0

        doc_chunk_ids = []
        for (
            index_name,
            large_chunks_enabled,
        ) in self.index_to_large_chunks_enabled.items():
            enriched_doc_infos = ElasticsearchIndex.enrich_basic_chunk_info(
                index_name=index_name,
                document_id=doc_id,
                previous_chunk_count=chunk_count,
                new_chunk_count=0,
                es_client=self.es_client,
            )

            doc_chunk_ids.extend(
                get_document_chunk_ids(
                    enriched_document_info_list=[enriched_doc_infos],
                    tenant_id=tenant_id,
                    large_chunks_enabled=large_chunks_enabled,
                )
            )

            doc_chunk_count += len(doc_chunk_ids)

        if doc_chunk_ids:
            actions = [
                {
                    "_op_type": "delete",
                    "_index": index_name,
                    "_id": str(chunk_id),
                }
                for chunk_id in doc_chunk_ids
            ]

            try:
                success, failed = bulk(self.es_client, actions)
                logger.info(f"Successfully deleted {success} documents.")
                if failed:
                    logger.error(f"Failed to delete {len(failed)} documents.")
            except Exception as e:
                logger.error(f"Bulk delete failed: {str(e)}")

        return doc_chunk_count

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunkUncleaned]:
        """Retrieve chunks by document ID

        This method retrieves document chunks by their document IDs. It supports both
        individual retrieval and batch retrieval for better performance.

        Args:
            chunk_requests: List of document chunk requests
            filters: Filters to apply to the retrieval
            batch_retrieval: Whether to use batch retrieval (more efficient for many documents)
            user_id: Optional user ID for SharePoint filtering
            db_session: Optional database session for SharePoint filtering

        Returns:
            List of retrieved document chunks as InferenceChunkUncleaned objects
        """
        if not chunk_requests:
            return []

        # Build filter clauses including SharePoint filters if user_id is provided
        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Choose retrieval method based on the number of requests and batch_retrieval flag
        if batch_retrieval and len(chunk_requests) > 1:
            return batch_id_retrieval(
                index_name=self.index_name,
                chunk_requests=chunk_requests,
                filter_clauses=filter_clauses,
                es_client=self.es_client,
            )
        else:
            return individual_id_retrieval(
                index_name=self.index_name,
                chunk_requests=chunk_requests,
                filter_clauses=filter_clauses,
                es_client=self.es_client,
            )

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunkUncleaned]:
        """Hybrid search combining keyword and vector search

        This implementation uses Elasticsearch's hybrid search capabilities:
        1. BM25 text search for keyword matching
        2. Vector similarity using KNN search
        3. Results combined using Reciprocal Rank Fusion (RRF)

        Parameters:
        - ranking_profile_type: KEYWORD favors exact matches, SEMANTIC favors semantic similarity
        - title_content_ratio: Weight given to title (0-1), with 1-ratio given to content
        - hybrid_alpha: Weight for vector similarity (1.0) vs BM25 (0.0)

        Key differences from Vespa:
        - Elasticsearch doesn't support mini-chunks, so we only use the main embedding
        - We use RRF ranking instead of a custom function score
        """
        # Build filter clauses for Elasticsearch including SharePoint filters
        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Use final_keywords if provided, otherwise use the original query
        final_query = " ".join(final_keywords) if final_keywords else query

        # Set default title_content_ratio if not provided
        if title_content_ratio is None:
            title_content_ratio = TITLE_CONTENT_RATIO

        # Calculate boost values for title and content based on title_content_ratio
        # title_content_ratio of 0.10 means 10% weight on title, 90% on content
        title_boost = (
            title_content_ratio * 10
        )  # Scale up for Elasticsearch boost values
        content_boost = (1 - title_content_ratio) * 10

        # Adjust boosts based on ranking_profile_type
        # KEYWORD: boost exact matches more, reduce semantic weight
        # SEMANTIC: boost semantic similarity more
        if ranking_profile_type == QueryExpansionType.KEYWORD:
            # For keyword queries, we want more emphasis on exact text matches
            # Increase text match weight, decrease vector weight
            text_match_boost = 1.5
            logger.debug("Using KEYWORD ranking profile with boosted text matching")
        else:  # SEMANTIC
            # For semantic queries, we want balanced or more vector-focused search
            text_match_boost = 1.0
            logger.debug("Using SEMANTIC ranking profile with balanced search")

        # Build a multi_match query that searches across title and content with appropriate weights
        # This respects the title_content_ratio parameter
        text_query = {
            "multi_match": {
                "query": final_query,
                "fields": [
                    f"semantic_identifier^{title_boost * text_match_boost}",  # Title field
                    f"content^{content_boost * text_match_boost}",  # Content field
                ],
                "type": "best_fields",
                "tie_breaker": 0.3,
            }
        }

        # Build the complete query
        query_obj = {
            "bool": {
                "must": [text_query],
                "filter": {"bool": {"must": filter_clauses}},
            }
        }

        # This approach uses standard Elasticsearch query with KNN
        params = {
            "index": self.index_name,
            "dsl_query": query_obj,
            "num_to_retrieve": num_to_retrieve,
            "offset": offset,
            "_source": {
                "excludes": ["vector"]  # Exclude the embedding vector from the results
            },
        }

        # Add vector search parameters if we have an embedding
        # The vector search weight is controlled by hybrid_alpha and ranking_profile_type
        if query_embedding is not None and len(query_embedding) > 0:
            # Adjust num_candidates based on ranking_profile_type
            # KEYWORD: fewer candidates (faster, more focused on text)
            # SEMANTIC: more candidates (better semantic coverage)
            if ranking_profile_type == QueryExpansionType.KEYWORD:
                effective_num_candidates = min(NUM_CANDIDATES, num_to_retrieve * 5)
            else:  # SEMANTIC
                effective_num_candidates = NUM_CANDIDATES

            params["knn"] = {
                "field": EMBEDDINGS,
                "query_vector": query_embedding,
                "k": num_to_retrieve,
                "num_candidates": effective_num_candidates,
                "filter": {
                    "bool": {
                        "must": filter_clauses,
                    }
                },
            }

            # RRF (Reciprocal Rank Fusion) combines text and vector results
            # The rank_constant can be adjusted based on ranking_profile_type
            # Higher rank_constant = more weight to lower-ranked results
            if ranking_profile_type == QueryExpansionType.KEYWORD:
                # Lower rank_constant for keyword: top matches matter more
                rrf_rank_constant = 20
            else:  # SEMANTIC
                # Higher rank_constant for semantic: give more chance to diverse results
                rrf_rank_constant = 60

            params["rank"] = {
                "rrf": {
                    "rank_window_size": num_to_retrieve * 2,
                    "rank_constant": rrf_rank_constant,
                }
            }

        return query_elasticsearch(params)

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int = NUM_RETURNED_HITS,
        offset: int = 0,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunkUncleaned]:
        """Admin search functionality

        This method provides a search interface for admin purposes, focusing on
        finding documents by title or content. It prioritizes title matches over
        content matches, similar to Vespa's admin_search ranking profile.

        Args:
            query: The text query
            filters: Filters to apply to the search
            num_to_retrieve: Number of results to retrieve
            offset: Offset for pagination
            user_id: Optional user ID for SharePoint filtering
            db_session: Optional database session for SharePoint filtering

        Returns:
            List of retrieved document chunks as InferenceChunkUncleaned objects
        """
        # Build filter clauses including SharePoint filters
        filter_clauses = build_elastic_filters(
            filters,
            include_hidden=True,
            user_id=user_id,
            db_session=db_session,
        )

        # Build the admin search query
        query_body = build_admin_search_query(query, filter_clauses)

        # Prepare parameters for query_elasticsearch
        params = {
            "index": self.index_name,
            "dsl_query": query_body,
            "num_to_retrieve": num_to_retrieve,
            "offset": offset,
        }

        # Use the query_elasticsearch function for consistent processing
        return query_elasticsearch(params)

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunkUncleaned]:
        """Retrieve random documents

        This method retrieves a random selection of documents that match the given filters.

        Args:
            filters: Filters to apply to the retrieval
            num_to_retrieve: Number of random documents to retrieve
            user_id: Optional user ID for SharePoint filtering
            db_session: Optional database session for SharePoint filtering

        Returns:
            List of randomly selected document chunks as InferenceChunkUncleaned objects
        """
        # Build filter clauses including SharePoint filters
        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Build the random search query
        query_body = build_random_search_query(filter_clauses)

        # Prepare parameters for query_elasticsearch
        params = {
            "index": self.index_name,
            "dsl_query": query_body,
            "num_to_retrieve": num_to_retrieve,
            "offset": 0,
        }

        # Use the query_elasticsearch function for consistent processing
        return query_elasticsearch(params)

    @classmethod
    def enrich_basic_chunk_info(
        cls,
        index_name: str,
        document_id: str,
        previous_chunk_count: int | None = None,
        new_chunk_count: int = 0,
        es_client: Elasticsearch = None,
    ) -> EnrichedDocumentIndexingInfo:
        """
        Enrich basic document information with chunk count details.

        Args:
            index_name: Name of the Elasticsearch index
            document_id: ID of the document
            previous_chunk_count: Previous number of chunks for this document (if known)
            new_chunk_count: New number of chunks for this document
            es_client: Elasticsearch client instance

        Returns:
            Enriched document information with chunk range details
        """
        last_indexed_chunk = previous_chunk_count

        # If the document has no `chunk_count` in the database, we know that it
        # has the old chunk ID system and we must check for the final chunk index
        is_old_version = False
        if last_indexed_chunk is None:
            is_old_version = True
            minimal_doc_info = MinimalDocumentIndexingInfo(
                doc_id=document_id, chunk_start_index=new_chunk_count
            )
            last_indexed_chunk = check_for_final_chunk_existence(
                minimal_doc_info=minimal_doc_info,
                start_index=new_chunk_count,
                index_name=index_name,
                es_client=es_client,
            )

        enriched_doc_info = EnrichedDocumentIndexingInfo(
            doc_id=document_id,
            chunk_start_index=new_chunk_count,
            chunk_end_index=last_indexed_chunk,
            old_version=is_old_version,
        )
        return enriched_doc_info

    @classmethod
    def delete_entries_by_tenant_id(
        cls,
        *,
        tenant_id: str,
        index_name: str,
    ) -> None:
        """Not implemented for Elasticsearch see Vespa implementation if needed"""
        raise NotImplementedError(
            "Elasticsearch does not support deleting by tenant ID"
        )
