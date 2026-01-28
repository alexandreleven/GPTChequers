import inspect
import re

from eleven.onyx.utils.slides_utils import is_slides_document
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.indexing.chunker import Chunker as BaseOnyxChunker
from onyx.indexing.models import DocAwareChunk


class Chunker(BaseOnyxChunker):
    """Chunker with special handling for slides documents (PPTX)."""

    def __init__(self, *args, **kwargs):
        self._onyx_chunker = BaseOnyxChunker(*args, **kwargs)

    def _split_text_into_slides(self, text: str) -> list[tuple[int, str]]:
        """
        Split text into slides based on <!-- Slide number: X --> markers.
        Returns list of (slide_number, slide_text_with_marker) tuples.
        Keeps the marker in the slide text.
        """
        slide_pattern = r"<!--\s*Slide\s+number:\s*(\d+)\s*-->"
        matches = list(re.finditer(slide_pattern, text))

        if not matches:
            return [(1, text)]

        slides = []
        for i, match in enumerate(matches):
            slide_number = int(match.group(1))
            start_pos = match.start()  # Include the marker
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            slide_text = text[start_pos:end_pos].strip()
            slides.append((slide_number, slide_text))

        return slides

    def _chunk_document_with_sections(
        self,
        document: IndexingDocument,
        sections: list,
        title_prefix: str,
        metadata_suffix_semantic: str,
        metadata_suffix_keyword: str,
        content_token_limit: int,
    ) -> list[DocAwareChunk]:
        """
        Override for PPTX files: transform slides into sections, then use base chunker logic.
        For non-PPTX files, delegate to base implementation.
        """
        if not is_slides_document(document):
            return super()._chunk_document_with_sections(
                document,
                sections,
                title_prefix,
                metadata_suffix_semantic,
                metadata_suffix_keyword,
                content_token_limit,
            )

        # For PPTX: transform slides into sections, then use base chunker
        slide_sections = []
        max_slide_tokens = 0

        for section in sections:
            section_text = str(section.text or "")
            section_link_text = section.link or ""
            image_file_id = None

            # Split into slides (keeping markers)
            slides = self._split_text_into_slides(section_text)

            # Create one section per slide and track max slide size
            for slide_num, slide_text in slides:
                slide_tokens = len(self._onyx_chunker.tokenizer.encode(slide_text))
                max_slide_tokens = max(max_slide_tokens, slide_tokens)

                slide_sections.append(
                    Section(
                        text=slide_text,
                        link=section_link_text,
                        image_file_id=image_file_id,
                    )
                )

        # Ensure content_token_limit is at least as large as the biggest slide
        # This prevents slides from being cut in the middle
        content_token_limit = max(content_token_limit, max_slide_tokens)

        # Use base chunker logic with slide-based sections
        return self._onyx_chunker._chunk_document_with_sections(
            document,
            slide_sections,
            title_prefix,
            metadata_suffix_semantic,
            metadata_suffix_keyword,
            content_token_limit,
        )

    def __getattr__(self, name: str):
        attr = getattr(self._onyx_chunker, name)
        # Only wrap actual methods/functions, not callable objects like SentenceChunker
        if inspect.ismethod(attr) or inspect.isfunction(attr):
            return lambda *args, **kwargs: attr(*args, **kwargs)
        return attr
