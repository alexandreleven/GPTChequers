from enum import Enum


class DocumentIndexType(str, Enum):
    COMBINED = "combined"  # Vespa
    SPLIT = "split"  # Typesense + Qdrant
    ELASTICSEARCH = "elasticsearch"  # Elasticsearch
