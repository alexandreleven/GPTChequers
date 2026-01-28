import io
import os
import platform
import shutil
import subprocess
import tempfile
from typing import Any
from typing import IO

try:
    import fitz
except ImportError:
    fitz = None  # type: ignore

from onyx.utils.logger import setup_logger

logger = setup_logger()


def find_soffice_path() -> str | None:
    """Find LibreOffice soffice executable path.

    Returns:
        Path to soffice executable or None if not found
    """
    system = platform.system()

    if system == "Windows":
        possible_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Found LibreOffice at: {path}")
                return path
        logger.error("LibreOffice not found in common Windows locations")
        return None
    else:
        try:
            subprocess.run(["which", "soffice"], check=True, capture_output=True)
            logger.info("Found LibreOffice in system PATH")
            return "soffice"
        except subprocess.CalledProcessError:
            path = shutil.which("soffice")
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                logger.info(f"Found LibreOffice at: {path}")
                return path
            logger.error("LibreOffice not found in system PATH")
            return None


def convert_pdf_pages_to_images(
    file: IO[Any],
    pdf_pass: str | None = None,
) -> list[bytes]:
    """Convert PDF pages to images.

    Args:
        file: PDF file-like object
        pdf_pass: Optional password for encrypted PDFs

    Returns:
        List of image bytes, one per page
    """
    if fitz is None:
        logger.error(
            "PyMuPDF (fitz) is not installed. Please install it to use PDF to images conversion."
        )
        return []

    try:
        if isinstance(file, io.BytesIO):
            content = file.getvalue()
        else:
            file.seek(0)
            content = file.read()

        pdf_document = fitz.open(stream=content, filetype="pdf")

        if pdf_document.needs_pass:
            if pdf_pass is not None:
                decrypt_success = pdf_document.authenticate(pdf_pass) == 1
                if not decrypt_success:
                    logger.error("Failed to decrypt PDF with provided password")
                    pdf_document.close()
                    return []
            else:
                logger.warning("No password available to decrypt PDF, returning empty")
                pdf_document.close()
                return []

        images = []
        try:
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("jpeg")
                images.append(img_bytes)
        except Exception as e:
            logger.error(f"Error converting PDF pages to images: {e}")
        finally:
            pdf_document.close()

        return images

    except Exception as e:
        logger.error(f"Error reading PDF file: {e}", exc_info=True)
        return []


def convert_pptx_to_pdf(file: IO[Any], file_name: str) -> bytes | None:
    """Convert PowerPoint presentation to PDF.

    Args:
        file: PPTX file-like object
        file_name: Name of the PPTX file

    Returns:
        PDF bytes or None if conversion fails
    """
    soffice_path = find_soffice_path()
    if not soffice_path:
        logger.error("LibreOffice soffice not found. Please install LibreOffice.")
        return None

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_basename = os.path.basename(file_name)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            temp_input_path = os.path.join(temp_dir, f"{file_name_without_ext}.pptx")

            file.seek(0)
            file_content = file.read()
            with open(temp_input_path, "wb") as temp_file:
                temp_file.write(file_content)

            logger.debug(f"Temporary file created: {temp_input_path}")

            result = subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--norestore",
                    "--nofirststartwizard",
                    "--nologo",
                    "--invisible",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    temp_dir,
                    temp_input_path,
                ],
                check=True,
                capture_output=True,
            )

            logger.debug(
                f"LibreOffice output: {result.stdout.decode('utf-8', errors='replace')}"
            )
            if result.stderr:
                logger.debug(
                    f"LibreOffice stderr: {result.stderr.decode('utf-8', errors='replace')}"
                )

            pdf_path = os.path.join(temp_dir, f"{file_name_without_ext}.pdf")
            if not os.path.exists(pdf_path):
                logger.error(f"PDF file not created at {pdf_path}")
                return None

            logger.debug(f"PDF created successfully: {pdf_path}")

            # Validate PDF with PyPDF
            try:
                from pypdf import PdfReader

                with open(pdf_path, "rb") as pdf_file:
                    reader = PdfReader(pdf_file)
                    logger.debug(f"PDF is valid, {len(reader.pages)} pages")
            except Exception as pdf_error:
                logger.error(f"Invalid PDF: {pdf_error}")
                return None

            with open(pdf_path, "rb") as pdf_file:
                return pdf_file.read()

    except subprocess.CalledProcessError as e:
        stderr_msg = (
            e.stderr.decode("utf-8", errors="replace")
            if e.stderr
            else "No error message"
        )
        logger.error(f"LibreOffice conversion failed: {stderr_msg}")
        return None
    except Exception as e:
        logger.error(f"Error converting PPTX to PDF: {e}", exc_info=True)
        return None


def convert_pptx_slides_to_images(
    file: IO[Any], file_name: str | None = None
) -> list[bytes]:
    """Convert PowerPoint slides to images.

    Converts PPTX to PDF first, then PDF pages to images.

    Args:
        file: PPTX file-like object
        file_name: Optional name of the PPTX file

    Returns:
        List of image bytes, one per slide
    """
    if file_name is None:
        file_name = getattr(file, "name", "presentation.pptx")
    if not file_name.endswith((".pptx", ".ppt")):
        file_name = "presentation.pptx"

    pdf_bytes = convert_pptx_to_pdf(file, file_name)
    if not pdf_bytes:
        return []

    return convert_pdf_pages_to_images(io.BytesIO(pdf_bytes))
