from onyx.configs.constants import SOURCE_TYPE

# Elasticsearch constants
ELASTICSEARCH_TIMEOUT = 120  # seconds
ELASTICSEARCH_BATCH_SIZE = 10  # Similar to Vespa batch size NOTE it is not used
TITLE_CONTENT_RATIO = 0.3  # Ratio for weighting title vs content in hybrid search
DOC_TIME_DECAY = 1.0  # Base time decay factor for document recency
NUM_RETURNED_HITS = 10  # Default number of hits to return
NUM_CANDIDATES = 10000  # Default number of candidates for KNN search

# Field names in Elasticsearch
TENANT_ID = "tenant_id"
DOCUMENT_ID = "document_id"
CHUNK_ID = "chunk_id"
BLURB = "blurb"
CONTENT = "content"
SOURCE_LINKS = "source_links"
SEMANTIC_IDENTIFIER = "semantic_identifier"
TITLE = "title"
SKIP_TITLE_EMBEDDING = "skip_title"
SECTION_CONTINUATION = "section_continuation"
EMBEDDINGS = "embeddings"
TITLE_EMBEDDING = "title_embedding"
ACCESS_CONTROL_LIST = "access_control_list"
DOCUMENT_SETS = "document_sets"
LARGE_CHUNK_REFERENCE_IDS = "large_chunk_reference_ids"
METADATA = "metadata"
METADATA_LIST = "metadata_list"
MIN_YEAR = "min_year"
METADATA_SUFFIX = "metadata_suffix"
BOOST = "boost"
DOC_UPDATED_AT = "doc_updated_at"  # Indexed as seconds since epoch
PRIMARY_OWNERS = "primary_owners"
SECONDARY_OWNERS = "secondary_owners"
RECENCY_BIAS = "recency_bias"
HIDDEN = "hidden"
CONTENT_SUMMARY = "content_summary"  # For highlighting matching keywords/sections

# Elasticsearch index settings
INDEX_SETTINGS = {
    "settings": {
        "number_of_shards": 3,
        "number_of_replicas": 1,
        "analysis": {"analyzer": {"default": {"type": "standard"}}},
    }
}

# Elasticsearch mapping template
MAPPING_TEMPLATE = {
    "mappings": {
        "properties": {
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
            EMBEDDINGS: {
                "type": "dense_vector",
                "dims": "VARIABLE_DIM",
                "index": True,
                "similarity": "cosine",
            },
            TITLE_EMBEDDING: {
                "type": "dense_vector",
                "dims": "VARIABLE_DIM",
                "index": True,
                "similarity": "cosine",
            },
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
            LARGE_CHUNK_REFERENCE_IDS: {"type": "integer"},
            METADATA: {"type": "object"},
            METADATA_LIST: {"type": "keyword"},
            METADATA_SUFFIX: {"type": "keyword"},
            BOOST: {"type": "float"},
            DOC_UPDATED_AT: {"type": "date", "format": "epoch_second"},
            PRIMARY_OWNERS: {"type": "keyword"},
            SECONDARY_OWNERS: {"type": "keyword"},
            RECENCY_BIAS: {"type": "float"},
            HIDDEN: {"type": "boolean"},
            CONTENT_SUMMARY: {"type": "text"},
            SKIP_TITLE_EMBEDDING: {"type": "boolean"},
        }
    }
}

# Elasticsearch dimension replacement pattern
ELASTICSEARCH_DIM_REPLACEMENT_PAT = "VARIABLE_DIM"
