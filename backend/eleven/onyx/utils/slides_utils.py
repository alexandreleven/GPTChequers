from typing import Union

from onyx.connectors.models import IndexingDocument


def is_slides_document(document_or_file_name: Union[IndexingDocument, str]) -> bool:
    """Check if the document or file is a slides document (PPTX).

    For now, returns True if it's a PPTX file.

    Args:
        document_or_file_name: Either an IndexingDocument or a file name string

    Returns:
        True if the document/file is a PPTX file, False otherwise
    """
    if isinstance(document_or_file_name, str):
        # Check file extension
        return document_or_file_name.lower().endswith(".pptx")

    # Check metadata first (more reliable)
    if (
        document_or_file_name.metadata.get("sharepoint_file_extension", "").lower()
        == "pptx"
    ):
        return True

    # Fallback to semantic identifier if it contains file extension
    semantic_id = document_or_file_name.semantic_identifier.lower()
    if semantic_id.endswith(".pptx"):
        return True

    return False
