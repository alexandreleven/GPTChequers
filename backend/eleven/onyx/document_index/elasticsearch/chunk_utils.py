"""Utilities for chunk content enrichment and cleaning.

This module provides functions to:
1. Enrich chunks during indexing (add title prefix, metadata suffix, contextual RAG)
2. Clean chunks during retrieval (remove enrichments to return original content)

These operations match the patterns used in Vespa and OpenSearch implementations.
"""

from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger

logger = setup_logger()


def enrich_chunk_content(chunk: DocMetadataAwareIndexChunk) -> str:
    """Enrich chunk content during indexing by prepending title and appending metadata.

    This improves search quality by:
    - Prepending title for better keyword/semantic matching
    - Appending metadata suffix for displaying extra info
    - Supporting contextual RAG with doc_summary and chunk_context

    The enrichments are removed during retrieval by cleanup_chunks().

    Args:
        chunk: The chunk to enrich

    Returns:
        Enriched content string with title prefix and metadata suffix
    """
    content = chunk.content

    # Prepend title if available (improves search matching)
    if chunk.source_document.title and chunk.source_document.title.strip():
        content = chunk.source_document.title + RETURN_SEPARATOR + content

    # Append metadata suffix if available (for displaying extra context)
    # Note: metadata_suffix would need to be added to the chunk structure
    # Currently not in DocMetadataAwareIndexChunk, but keeping for future compatibility

    return content


def cleanup_chunks(chunks: list[InferenceChunkUncleaned]) -> list[InferenceChunk]:
    """Remove indexing-time content additions from chunks retrieved from Elasticsearch.

    During indexing, chunks are augmented with additional text to improve search
    quality:
    - Title prepended to content (for better keyword/semantic matching)
    - Metadata suffix appended to content
    - Contextual RAG: doc_summary (beginning) and chunk_context (end)

    This function strips these additions before returning chunks to users,
    restoring the original document content. Cleaning is applied in sequence:
    1. Title removal:
        - Full match: Strips exact title from beginning
        - Partial match: If content starts with title[:BLURB_SIZE], splits on
          RETURN_SEPARATOR to remove title section
    2. Metadata suffix removal:
        - Strips metadata_suffix from end, plus trailing RETURN_SEPARATOR
    3. Contextual RAG removal:
        - Strips doc_summary from beginning (if present)
        - Strips chunk_context from end (if present)

    Args:
        chunks: Chunks as retrieved from Elasticsearch with indexing augmentations
            intact.

    Returns:
        Clean InferenceChunk objects with augmentations removed, containing only
            the original document content that should be shown to users.
    """

    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
        """Remove title prefix from chunk content."""
        if not chunk.title or not chunk.content:
            return chunk.content

        # Try exact match first
        if chunk.content.startswith(chunk.title):
            return chunk.content[len(chunk.title) :].lstrip()

        # BLURB SIZE is by token instead of char but each token is at least 1 char
        # If this prefix matches the content, it's assumed the title was prepended
        if chunk.content.startswith(chunk.title[:BLURB_SIZE]):
            return (
                chunk.content.split(RETURN_SEPARATOR, 1)[-1]
                if RETURN_SEPARATOR in chunk.content
                else chunk.content
            )

        return chunk.content

    def _remove_metadata_suffix(chunk: InferenceChunkUncleaned) -> str:
        """Remove metadata suffix from chunk content."""
        if not chunk.metadata_suffix:
            return chunk.content
        return chunk.content.removesuffix(chunk.metadata_suffix).rstrip(
            RETURN_SEPARATOR
        )

    def _remove_contextual_rag(chunk: InferenceChunkUncleaned) -> str:
        """Remove contextual RAG additions (doc_summary and chunk_context)."""
        content = chunk.content

        # Remove document summary from beginning
        if chunk.doc_summary and content.startswith(chunk.doc_summary):
            content = content[len(chunk.doc_summary) :].lstrip()

        # Remove chunk context from end
        if chunk.chunk_context and content.endswith(chunk.chunk_context):
            content = content[: len(content) - len(chunk.chunk_context)].rstrip()

        return content

    # Apply all cleaning operations to each chunk
    for chunk in chunks:
        chunk.content = _remove_title(chunk)
        chunk.content = _remove_metadata_suffix(chunk)
        chunk.content = _remove_contextual_rag(chunk)

    return [chunk.to_inference_chunk() for chunk in chunks]
