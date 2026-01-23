from uuid import UUID

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from sqlalchemy.orm import Session

from eleven.onyx.document_index.elasticsearch.chunk_retrieval import batch_id_retrieval
from eleven.onyx.document_index.elasticsearch.chunk_retrieval import (
    individual_id_retrieval,
)
from eleven.onyx.document_index.elasticsearch.chunk_retrieval import query_elasticsearch
from eleven.onyx.document_index.elasticsearch.chunk_utils import cleanup_chunks
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
from onyx.context.search.models import InferenceChunk
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
from onyx.document_index.interfaces_new import TenantState
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger()


class ElasticsearchIndex(DocumentIndex):
    """Elasticsearch implementation of DocumentIndex.

    This class provides document indexing, retrieval, and management operations
    for an Elasticsearch search engine instance. It handles the complete lifecycle
    of document chunks within a specific Elasticsearch index.

    Key Features:
    - Hybrid search (keyword + vector similarity)
    - Chunk content enrichment during indexing
    - Chunk content cleaning during retrieval
    - Access control and filtering
    - Multi-index support (primary + secondary)
    - Multitenant support via TenantState
    """

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

        # Store tenant state for consistency with new interface pattern
        # Note: tenant_id will be provided via method parameters for backwards compatibility
        self._tenant_state = TenantState(
            tenant_id="",  # Will be provided via method parameters
            multitenant=multitenant,
        )
        self.multitenant = multitenant

        if es_client:
            self.es_client = es_client
        else:
            self.es_client = get_elasticsearch_client()

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

        # Calculate total number of batches for progress tracking
        total_batches = (
            len(chunks) + ELASTICSEARCH_BATCH_SIZE - 1
        ) // ELASTICSEARCH_BATCH_SIZE

        for batch_idx, chunk_batch in enumerate(
            batch_generator(chunks, ELASTICSEARCH_BATCH_SIZE)
        ):
            # Index the batch without refresh (defer refresh to end for performance)
            batch_index_elasticsearch_chunks(
                chunks=chunk_batch,
                index_name=self.index_name,
                es_client=self.es_client,
                tenant_id=tenant_id,
                refresh=False,  # Don't refresh per batch - much faster
            )

            # Log progress periodically (every 10 batches or at completion)
            if batch_idx % 10 == 0 or batch_idx == total_batches - 1:
                chunks_indexed = min(
                    (batch_idx + 1) * ELASTICSEARCH_BATCH_SIZE, len(chunks)
                )
                logger.info(
                    f"Indexed {chunks_indexed}/{len(chunks)} chunks "
                    f"({(chunks_indexed * 100 / len(chunks)):.1f}%)"
                )

        all_cleaned_doc_ids = {chunk.source_document.id for chunk in chunks}

        # Refresh index once at the end to make all documents searchable
        # This is MUCH faster than refreshing after every batch
        try:
            self.es_client.indices.refresh(index=self.index_name)
            logger.info(
                f"Index refresh completed - all {len(chunks)} chunks now searchable"
            )
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
    ) -> list[InferenceChunk]:
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
            List of retrieved document chunks as InferenceChunk objects (cleaned)
        """
        if not chunk_requests:
            return []

        # Build filter clauses including SharePoint filters if user_id is provided
        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Choose retrieval method based on the number of requests and batch_retrieval flag
        if batch_retrieval and len(chunk_requests) > 1:
            raw_chunks = batch_id_retrieval(
                index_name=self.index_name,
                chunk_requests=chunk_requests,
                filter_clauses=filter_clauses,
                es_client=self.es_client,
            )
        else:
            raw_chunks = individual_id_retrieval(
                index_name=self.index_name,
                chunk_requests=chunk_requests,
                filter_clauses=filter_clauses,
                es_client=self.es_client,
            )

        # Clean chunks to remove indexing-time enrichments (title prefix, metadata suffix, etc.)
        return cleanup_chunks(raw_chunks)

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,  # kept for API compatibility, NOT used by ES
        time_decay_multiplier: float,  # not supported natively, ignored
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunk]:
        """
        Hybrid search using Elasticsearch native hybrid search (retriever.rrf)

        - BM25 keyword search (standard retriever)
        - Vector KNN search (knn retriever)
        - Fusion via Reciprocal Rank Fusion (RRF)

        NOTE:
        - Elasticsearch does NOT support alpha-weighted hybrid (BM25 vs vector)
        - hybrid_alpha is ignored by design
        """

        # Filters

        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Final query text

        final_query = " ".join(final_keywords) if final_keywords else query

        if title_content_ratio is None:
            title_content_ratio = TITLE_CONTENT_RATIO

        title_boost = title_content_ratio * 10
        content_boost = (1 - title_content_ratio) * 10

        # Ranking profile tuning

        if ranking_profile_type == QueryExpansionType.KEYWORD:
            text_match_boost = 1.5
            num_candidates = min(NUM_CANDIDATES, num_to_retrieve * 5)
            rrf_rank_constant = 20
        else:  # SEMANTIC
            text_match_boost = 1.0
            num_candidates = NUM_CANDIDATES
            rrf_rank_constant = 60

        # Text (BM25) query
        text_query = {
            "multi_match": {
                "query": final_query,
                "fields": [
                    f"semantic_identifier^{title_boost * text_match_boost}",
                    f"content^{content_boost * text_match_boost}",
                ],
                "type": "best_fields",
                "tie_breaker": 0.3,
            }
        }

        standard_retriever = {
            "standard": {
                "query": {
                    "bool": {
                        "must": [text_query],
                        "filter": {"bool": {"must": filter_clauses}},
                    }
                }
            }
        }

        retrievers = [standard_retriever]

        # Vector retriever (if embedding provided)
        if query_embedding is not None and len(query_embedding) > 0:
            knn_retriever = {
                "knn": {
                    "field": EMBEDDINGS,
                    "query_vector": query_embedding,
                    "k": num_to_retrieve,
                    "num_candidates": num_candidates,
                    "filter": {"bool": {"must": filter_clauses}},
                }
            }
            retrievers.append(knn_retriever)

        # Elasticsearch search params (HYBRID)
        params = {
            "index": self.index_name,
            "size": num_to_retrieve,
            "from": offset,
            "_source": {"excludes": ["vector"]},
            "retriever": {
                "rrf": {
                    "retrievers": retrievers,
                    "rank_window_size": num_to_retrieve * 2,
                    "rank_constant": rrf_rank_constant,
                }
            },
        }

        # Execute + cleanup
        raw_chunks = query_elasticsearch(params)
        return cleanup_chunks(raw_chunks)

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int = NUM_RETURNED_HITS,
        offset: int = 0,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunk]:
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
            List of retrieved document chunks as InferenceChunk objects (cleaned)
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

        # Standard retriever with admin search query
        standard_retriever = {
            "standard": {
                "query": query_body,
            }
        }

        # Elasticsearch search params (STANDARD)
        params = {
            "index": self.index_name,
            "size": num_to_retrieve,
            "from": offset,
            "_source": {"excludes": ["vector"]},
            "retriever": {
                "rrf": {
                    "retrievers": [standard_retriever],
                    "rank_window_size": num_to_retrieve * 2,
                    "rank_constant": 20,
                }
            },
        }

        # Retrieve and clean chunks
        raw_chunks = query_elasticsearch(params)
        return cleanup_chunks(raw_chunks)

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
        user_id: UUID = None,
        db_session: Session = None,
    ) -> list[InferenceChunk]:
        """Retrieve random documents

        This method retrieves a random selection of documents that match the given filters.

        Args:
            filters: Filters to apply to the retrieval
            num_to_retrieve: Number of random documents to retrieve
            user_id: Optional user ID for SharePoint filtering
            db_session: Optional database session for SharePoint filtering

        Returns:
            List of randomly selected document chunks as InferenceChunk objects (cleaned)
        """
        # Build filter clauses including SharePoint filters
        filter_clauses = build_elastic_filters(
            filters, user_id=user_id, db_session=db_session
        )

        # Build the random search query
        query_body = build_random_search_query(filter_clauses)

        # Standard retriever with random search query
        standard_retriever = {
            "standard": {
                "query": query_body,
            }
        }

        # Elasticsearch search params (STANDARD)
        params = {
            "index": self.index_name,
            "size": num_to_retrieve,
            "from": 0,
            "_source": {"excludes": ["vector"]},
            "retriever": {
                "rrf": {
                    "retrievers": [standard_retriever],
                    "rank_window_size": num_to_retrieve * 2,
                    "rank_constant": 20,
                }
            },
        }

        # Retrieve and clean chunks
        raw_chunks = query_elasticsearch(params)
        return cleanup_chunks(raw_chunks)

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
