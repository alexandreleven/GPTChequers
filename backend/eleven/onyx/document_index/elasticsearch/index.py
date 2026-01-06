from elasticsearch import Elasticsearch

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.vespa.vespa_document_index import TenantState


class ElasticsearchIndex(DocumentIndex):
    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
        large_chunks_enabled: bool,
        elasticsearch_client: Elasticsearch | None = None,
    ) -> None:
        self.index_name = index_name
        self.tenant_state = tenant_state
        self.large_chunks_enabled = large_chunks_enabled
        self.elasticsearch_client = Elasticsearch()
        self._multitenant = tenant_state.multitenant
        if self._multitenant:
            assert (
                self._tenant_id
            ), "Bug: Must supply a tenant id if in multitenant mode."

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        raise NotImplementedError
