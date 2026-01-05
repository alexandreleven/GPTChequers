import os

from eleven.onyx.configs.constants import DocumentIndexType

DOCUMENT_INDEX_TYPE = os.environ.get(
    "DOCUMENT_INDEX_TYPE", DocumentIndexType.COMBINED.value
)
