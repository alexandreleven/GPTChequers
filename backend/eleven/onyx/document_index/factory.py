import httpx

from eleven.onyx.configs.app_configs import DOCUMENT_INDEX_TYPE
from eleven.onyx.configs.constants import DocumentIndexType
from eleven.onyx.document_index.elasticsearch.index import ElasticsearchIndex
from onyx.db.models import SearchSettings
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.vespa.index import VespaIndex
from shared_configs.configs import MULTI_TENANT


# Do not rename this function, it is used by the versioned implementation
def _get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    httpx_client: httpx.Client | None = None,
) -> DocumentIndex:
    """Primary index is the index that is used for querying/updating etc.
    Secondary index is for when both the currently used index and the upcoming
    index both need to be updated, updates are applied to both indices"""

    secondary_index_name: str | None = None
    secondary_large_chunks_enabled: bool | None = None
    if secondary_search_settings:
        secondary_index_name = secondary_search_settings.index_name
        secondary_large_chunks_enabled = secondary_search_settings.large_chunks_enabled

    # Return the appropriate index based on the configured document index type
    if DOCUMENT_INDEX_TYPE == DocumentIndexType.ELASTICSEARCH.value:
        # httpx_client is not used by ElasticsearchIndex
        return ElasticsearchIndex(
            index_name=search_settings.index_name,
            secondary_index_name=secondary_index_name,
            large_chunks_enabled=search_settings.large_chunks_enabled,
            secondary_large_chunks_enabled=secondary_large_chunks_enabled,
            multitenant=MULTI_TENANT,
        )

    elif DOCUMENT_INDEX_TYPE == DocumentIndexType.COMBINED.value:
        return VespaIndex(
            index_name=search_settings.index_name,
            secondary_index_name=secondary_index_name,
            large_chunks_enabled=search_settings.large_chunks_enabled,
            secondary_large_chunks_enabled=secondary_large_chunks_enabled,
            multitenant=MULTI_TENANT,
            httpx_client=httpx_client,
        )
    else:
        raise ValueError(f"Invalid document index type: {DOCUMENT_INDEX_TYPE}")
