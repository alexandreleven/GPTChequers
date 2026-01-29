from collections.abc import Callable
from typing import Any
from typing import IO

from eleven.onyx.file_processing.image_utils import convert_pdf_pages_to_images
from eleven.onyx.file_processing.image_utils import convert_pptx_slides_to_images
from eleven.onyx.prompts.image_analysis import IMAGE_DESCRIPTION_SYSTEM_PROMPT
from eleven.onyx.utils.slides_utils import is_slides_document
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.file_processing.extract_file_text import (
    extract_text_and_images as base_onyx_extract_text_and_images,
)
from onyx.file_processing.extract_file_text import ExtractionResult
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.image_summarization import (
    summarize_image_with_error_handling,
)
from onyx.llm.factory import get_default_llm_with_vision
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _should_use_vision_parsing(file: IO[Any], file_name: str) -> bool:
    """Check if vision-based parsing should be used for this file.

    For slides documents (PPTX), vision parsing is automatically enabled to extract slide content.
    For other files, vision parsing is only enabled if the global flag is set.

    Args:
        file: File-like object to check
        file_name: Name of the file to check

    Returns:
        True if vision parsing should be enabled
    """

    if get_image_extraction_and_analysis_enabled():
        logger.debug("Image extraction and analysis disabled, skipping vision parsing")
        return True

    # Slides documents always use vision parsing for slide extraction
    if not is_slides_document(file_name):
        return True

    return False


def _parse_text_with_vision(
    file: IO[Any],
    file_name: str,
    pdf_pass: str | None = None,
    content_type: str | None = None,
    image_callback: Callable[[bytes, str], None] | None = None,
) -> ExtractionResult:
    """Extract text using vision-based parsing.

    Converts document pages to images and uses vision models to extract text.

    Args:
        file: File-like object to extract content from
        file_name: Name of the file
        pdf_pass: Optional password for encrypted PDFs
        content_type: Optional MIME type override
        image_callback: Optional callback for streaming image extraction

    Returns:
        ExtractionResult with text content, embedded images, and metadata
    """
    logger.info(f"Vision parsing requested for {file_name}")

    try:
        images = None
        extension = get_file_ext(file_name)
        if extension == ".pdf":
            images = convert_pdf_pages_to_images(file, pdf_pass)
        elif extension == ".pptx":
            images = convert_pptx_slides_to_images(file, file_name)

        if not images:
            logger.warning("No images extracted, falling back to standard extraction")
            return base_onyx_extract_text_and_images(
                file, file_name, pdf_pass, content_type, image_callback
            )

        llm = get_default_llm_with_vision()
        if not llm:
            logger.warning(
                "No vision-enabled LLM available, falling back to standard extraction"
            )
            return base_onyx_extract_text_and_images(
                file, file_name, pdf_pass, content_type, image_callback
            )

        text_parts = []
        for idx, image_data in enumerate(images):
            summary = summarize_image_with_error_handling(
                llm=llm,
                image_data=image_data,
                system_prompt=IMAGE_DESCRIPTION_SYSTEM_PROMPT,
                context_name=f"{file_name} - page {idx + 1}",
            )
            if summary:
                slide_number = idx + 1
                slide_marker = f"<!-- Slide number: {slide_number} -->"
                text_parts.append(f"{slide_marker}\n\n{summary}")

        return ExtractionResult(
            text_content="\n\n".join(text_parts),
            embedded_images=[],
            metadata={},
        )

    except Exception as e:
        logger.exception(f"Vision parsing error for {file_name}: {e}")
        return base_onyx_extract_text_and_images(
            file, file_name, pdf_pass, content_type, image_callback
        )


def extract_text_and_images(
    file: IO[Any],
    file_name: str,
    pdf_pass: str | None = None,
    content_type: str | None = None,
    image_callback: Callable[[bytes, str], None] | None = None,
) -> ExtractionResult:
    """Extract text and images with Eleven-specific logic.

    Uses vision-based parsing when enabled, otherwise falls back to standard extraction.

    Args:
        file: File-like object to extract content from
        file_name: Name of the file
        pdf_pass: Optional password for encrypted PDFs
        content_type: Optional MIME type override
        image_callback: Optional callback for streaming image extraction

    Returns:
        ExtractionResult with text content, embedded images, and metadata
    """
    if _should_use_vision_parsing(file, file_name):
        return _parse_text_with_vision(
            file, file_name, pdf_pass, content_type, image_callback
        )

    return base_onyx_extract_text_and_images(
        file, file_name, pdf_pass, content_type, image_callback
    )
