"""
Notion-SharePoint Hybrid Connector

This connector reads a Notion database, extracts SharePoint URLs from a specified column,
and indexes the SharePoint documents with metadata from the Notion database rows.

It handles various SharePoint URL formats:
- Direct file URLs
- Sharing links (/:f:/r/, /:x:/r/, etc.)
- Relative paths
"""

import base64
import io
import os
from collections.abc import Generator
from datetime import datetime
from typing import Any

import msal  # type: ignore[import-untyped]
import requests
from office365.graph_client import GraphClient  # type: ignore[import-untyped]
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore[import-untyped]
from pydantic import BaseModel
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector import (
    _convert_driveitem_to_document_with_permissions,
)
from onyx.connectors.sharepoint.connector import _download_with_cap
from onyx.connectors.sharepoint.connector import SharepointAuthMethod
from onyx.connectors.sharepoint.connector import SizeCapExceeded
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NOTION_CALL_TIMEOUT = 30  # 30 seconds
_NOTION_PAGE_SIZE = 100


class NotionDatabaseRow(BaseModel):
    """Represents a row from a Notion database with extracted data."""

    id: str
    sharepoint_url: str | None
    metadata: dict[str, str]
    last_edited_time: datetime | None
    notion_url: str


class NotionSharepointConnector(LoadConnector, PollConnector):
    """
    Hybrid connector that:
    1. Reads rows from a Notion database
    2. Extracts SharePoint URLs from a specified column
    3. Fetches and indexes SharePoint documents with Notion metadata

    Arguments:
        notion_database_id: The ID of the Notion database to read from
        link_property_name: The name of the column containing SharePoint URLs (default: "Link")
        batch_size: Number of documents to index in a batch
    """

    def __init__(
        self,
        notion_database_id: str,
        link_property_name: str = "Link",
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        """Initialize the connector with parameters."""
        self.notion_database_id = notion_database_id
        self.link_property_name = link_property_name
        self.batch_size = batch_size

        # Notion API headers
        self.notion_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

        # SharePoint Graph client (initialized in load_credentials)
        self._graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None

        # Track processed rows to avoid duplicates
        self.processed_rows: set[str] = set()

    @property
    def graph_client(self) -> GraphClient:
        """Get the Graph client, raising an error if not initialized."""
        if self._graph_client is None:
            raise ConnectorMissingCredentialError("SharePoint")
        return self._graph_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """
        Load both Notion and SharePoint credentials.

        Expected credentials:
        - notion_integration_token: Notion integration token
        - sp_client_id: SharePoint app client ID
        - sp_client_secret: SharePoint app client secret
        - sp_directory_id: Azure AD directory (tenant) ID
        - authentication_method: "client_secret" or "certificate" (optional)
        """
        # Load Notion credentials
        notion_token = credentials.get("notion_integration_token")
        if not notion_token:
            raise ConnectorMissingCredentialError(
                "Notion integration token is required"
            )
        self.notion_headers["Authorization"] = f"Bearer {notion_token}"

        # Load SharePoint credentials
        sp_client_id = credentials.get("sp_client_id")
        sp_client_secret = credentials.get("sp_client_secret")
        sp_directory_id = credentials.get("sp_directory_id")

        if not all([sp_client_id, sp_directory_id]):
            raise ConnectorMissingCredentialError(
                "SharePoint credentials (sp_client_id, sp_directory_id) are required"
            )

        auth_method = credentials.get(
            "authentication_method", SharepointAuthMethod.CLIENT_SECRET.value
        )
        authority_url = f"https://login.microsoftonline.com/{sp_directory_id}"

        if auth_method == SharepointAuthMethod.CLIENT_SECRET.value:
            if not sp_client_secret:
                raise ConnectorMissingCredentialError(
                    "SharePoint client secret is required for client_secret authentication"
                )
            self.msal_app = msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=sp_client_id,
                client_credential=sp_client_secret,
            )
        else:
            raise ConnectorValidationError(
                f"Authentication method '{auth_method}' is not supported for this connector"
            )

        def _acquire_token_for_graph() -> dict[str, Any]:
            """Acquire token via MSAL for Graph API."""
            if self.msal_app is None:
                raise ConnectorValidationError("MSAL app is not initialized")
            token = self.msal_app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            if token is None:
                raise ConnectorValidationError("Failed to acquire token for Graph API")
            return token

        self._graph_client = GraphClient(_acquire_token_for_graph)
        return None

    def validate_connector_settings(self) -> None:
        """Validate that the connector is properly configured."""
        if not self.notion_database_id:
            raise ConnectorValidationError("Notion database ID is required")

        if not self.notion_headers.get("Authorization"):
            raise ConnectorMissingCredentialError("Notion credentials not loaded")

        if self._graph_client is None:
            raise ConnectorMissingCredentialError("SharePoint credentials not loaded")

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_notion_database(self, cursor: str | None = None) -> dict[str, Any]:
        """
        Fetch rows from the Notion database with pagination.

        Args:
            cursor: Pagination cursor for fetching next page

        Returns:
            API response containing results and pagination info
        """
        url = f"https://api.notion.com/v1/databases/{self.notion_database_id}/query"
        body: dict[str, Any] = {"page_size": _NOTION_PAGE_SIZE}
        if cursor:
            body["start_cursor"] = cursor

        response = rl_requests.post(
            url,
            headers=self.notion_headers,
            json=body,
            timeout=_NOTION_CALL_TIMEOUT,
        )

        try:
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch Notion database: {response.text}")
            raise e

        return response.json()

    def _fetch_all_database_rows(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Generator[NotionDatabaseRow, None, None]:
        """
        Fetch all rows from the Notion database with optional time filtering.

        Args:
            start: Start time filter (seconds since epoch)
            end: End time filter (seconds since epoch)

        Yields:
            NotionDatabaseRow objects with extracted data
        """
        cursor = None

        while True:
            data = self._fetch_notion_database(cursor)

            for row in data.get("results", []):
                row_id = row.get("id", "")

                # Parse last edited time
                last_edited_str = row.get("last_edited_time")
                last_edited_time = None
                if last_edited_str:
                    last_edited_time = datetime.fromisoformat(
                        last_edited_str.replace("Z", "+00:00")
                    )

                    # Apply time filtering if specified
                    if start is not None and last_edited_time.timestamp() < start:
                        continue
                    if end is not None and last_edited_time.timestamp() > end:
                        continue

                # Extract SharePoint URL from the specified property
                properties = row.get("properties", {})
                sharepoint_url = self._extract_url_from_property(properties)

                # Extract metadata from other properties
                metadata = self._extract_metadata_from_properties(properties)

                yield NotionDatabaseRow(
                    id=row_id,
                    sharepoint_url=sharepoint_url,
                    metadata=metadata,
                    last_edited_time=last_edited_time,
                    notion_url=row.get("url", ""),
                )

            # Handle pagination
            if not data.get("has_more", False):
                break
            cursor = data.get("next_cursor")

    def _extract_url_from_property(self, properties: dict[str, Any]) -> str | None:
        """
        Extract the SharePoint URL from the link property.

        Handles different Notion property types:
        - url: Direct URL value
        - rich_text: Text containing URL
        - files: External file with URL

        Args:
            properties: The properties dict from a Notion row

        Returns:
            The extracted URL or None if not found
        """
        link_prop = properties.get(self.link_property_name)
        if not link_prop:
            return None

        prop_type = link_prop.get("type")

        # Handle "url" type property
        if prop_type == "url":
            return link_prop.get("url")

        # Handle "rich_text" type property
        if prop_type == "rich_text":
            rich_text_list = link_prop.get("rich_text", [])
            for rt in rich_text_list:
                # Check for hyperlink
                if rt.get("href"):
                    return rt.get("href")
                # Check for plain text URL
                if rt.get("type") == "text":
                    text_content = rt.get("text", {}).get("content", "")
                    if text_content.startswith("http"):
                        return text_content
            return None

        # Handle "files" type property (external files)
        if prop_type == "files":
            files = link_prop.get("files", [])
            for f in files:
                if f.get("type") == "external":
                    return f.get("external", {}).get("url")
                if f.get("type") == "file":
                    return f.get("file", {}).get("url")
            return None

        return None

    def _extract_metadata_from_properties(
        self, properties: dict[str, Any]
    ) -> dict[str, str]:
        """
        Extract metadata from Notion row properties (excluding the link column).

        Args:
            properties: The properties dict from a Notion row

        Returns:
            Dict of property names to string values
        """
        metadata: dict[str, str] = {}

        for prop_name, prop_value in properties.items():
            # Skip the link property
            if prop_name == self.link_property_name:
                continue

            if not prop_value or not isinstance(prop_value, dict):
                continue

            value = self._property_to_string(prop_value)
            if value:
                metadata[prop_name] = value

        return metadata

    def _property_to_string(self, prop: dict[str, Any]) -> str | None:
        """
        Convert a Notion property to a string value.

        Args:
            prop: A Notion property dict

        Returns:
            String representation of the property value or None
        """
        prop_type = prop.get("type")
        if not prop_type:
            return None

        prop_data = prop.get(prop_type)
        if prop_data is None:
            return None

        # Handle different property types
        if prop_type == "title":
            return self._extract_rich_text(prop_data)

        if prop_type == "rich_text":
            return self._extract_rich_text(prop_data)

        if prop_type == "number":
            return str(prop_data) if prop_data is not None else None

        if prop_type == "select":
            return prop_data.get("name") if prop_data else None

        if prop_type == "multi_select":
            if isinstance(prop_data, list):
                names = [item.get("name") for item in prop_data if item.get("name")]
                return ", ".join(names) if names else None
            return None

        if prop_type == "date":
            if prop_data:
                start = prop_data.get("start", "")
                end = prop_data.get("end")
                if end:
                    return f"{start} - {end}"
                return start
            return None

        if prop_type == "checkbox":
            return "Yes" if prop_data else "No"

        if prop_type == "status":
            return prop_data.get("name") if prop_data else None

        if prop_type == "email":
            return prop_data if isinstance(prop_data, str) else None

        if prop_type == "phone_number":
            return prop_data if isinstance(prop_data, str) else None

        if prop_type == "url":
            return prop_data if isinstance(prop_data, str) else None

        if prop_type == "people":
            if isinstance(prop_data, list):
                names = [
                    person.get("name", person.get("id", "")) for person in prop_data
                ]
                return ", ".join(names) if names else None
            return None

        if prop_type == "relation":
            if isinstance(prop_data, list):
                ids = [item.get("id", "") for item in prop_data if item.get("id")]
                return ", ".join(ids) if ids else None
            return None

        if prop_type == "formula":
            formula_type = prop_data.get("type") if prop_data else None
            if formula_type and formula_type in prop_data:
                formula_value = prop_data.get(formula_type)
                if formula_value is not None:
                    return str(formula_value)
            return None

        if prop_type == "rollup":
            rollup_type = prop_data.get("type") if prop_data else None
            if rollup_type and rollup_type in prop_data:
                rollup_value = prop_data.get(rollup_type)
                if rollup_value is not None:
                    return str(rollup_value)
            return None

        return None

    def _extract_rich_text(self, rich_text_list: list[dict[str, Any]]) -> str | None:
        """
        Extract plain text from a rich_text array.

        Args:
            rich_text_list: List of rich text objects from Notion

        Returns:
            Concatenated plain text or None
        """
        if not isinstance(rich_text_list, list):
            return None

        texts = []
        for rt in rich_text_list:
            if rt.get("type") == "text":
                content = rt.get("text", {}).get("content", "")
                if content:
                    texts.append(content)
            elif rt.get("plain_text"):
                texts.append(rt.get("plain_text"))

        return "".join(texts) if texts else None

    @staticmethod
    def _encode_sharing_url(url: str) -> str:
        """
        Encode a SharePoint sharing URL for the Graph API /shares endpoint.

        The encoding process:
        1. Base64 encode the URL
        2. Convert to base64url (remove padding, replace +/- with -/_)
        3. Prefix with "u!"

        Args:
            url: The SharePoint sharing URL

        Returns:
            Encoded share token for the Graph API
        """
        base64_encoded = base64.b64encode(url.encode("utf-8")).decode("utf-8")
        # Convert to base64url format
        base64url = base64_encoded.rstrip("=").replace("+", "-").replace("/", "_")
        return f"u!{base64url}"

    def _resolve_sharepoint_url_to_driveitem(
        self, url: str
    ) -> tuple[DriveItem | None, str | None]:
        """
        Resolve a SharePoint URL to a DriveItem using the Graph API.

        Handles various URL formats:
        - Sharing links (using /shares/{encoded}/driveItem endpoint)
        - Direct file URLs

        Args:
            url: The SharePoint URL to resolve

        Returns:
            Tuple of (DriveItem, drive_name) or (None, None) if resolution fails
        """
        if not url:
            return None, None

        # Try to resolve via the /shares endpoint (works for sharing links)
        try:
            share_token = self._encode_sharing_url(url)
            logger.debug(f"Attempting to resolve URL via /shares endpoint: {url}")

            # Use direct Graph API call since the SDK might not support this well
            token = self._acquire_graph_token()
            if not token:
                logger.warning("Failed to acquire Graph token")
                return None, None

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Get the driveItem from the sharing URL
            shares_url = (
                f"https://graph.microsoft.com/v1.0/shares/{share_token}/driveItem"
            )
            response = requests.get(
                shares_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )

            if response.status_code == 200:
                driveitem_data = response.json()
                logger.info(
                    f"Successfully resolved SharePoint URL: {driveitem_data.get('name')}"
                )

                # Create a DriveItem-like object with the response data
                # We need to fetch the actual DriveItem via the SDK for proper download
                drive_id = driveitem_data.get("parentReference", {}).get("driveId")
                item_id = driveitem_data.get("id")
                drive_name = driveitem_data.get("parentReference", {}).get("name", "")

                if drive_id and item_id:
                    try:
                        driveitem = (
                            self.graph_client.drives[drive_id]
                            .items[item_id]
                            .get()
                            .execute_query()
                        )
                        return driveitem, drive_name
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch DriveItem via SDK, using API response: {e}"
                        )
                        # Return the raw data wrapped in a way we can use
                        return (
                            self._create_driveitem_from_api_response(driveitem_data),
                            drive_name,
                        )

            elif response.status_code == 404:
                logger.warning(f"SharePoint resource not found: {url}")
            elif response.status_code == 403:
                logger.warning(f"Access denied to SharePoint resource: {url}")
            else:
                logger.warning(
                    f"Failed to resolve SharePoint URL (status {response.status_code}): {url}"
                )

        except Exception as e:
            logger.warning(f"Error resolving SharePoint URL via /shares: {url} - {e}")

        return None, None

    def _create_driveitem_from_api_response(
        self, data: dict[str, Any]
    ) -> DriveItem | None:
        """
        Create a DriveItem object from API response data.

        This is a workaround when the SDK cannot fetch the item directly.

        Args:
            data: The API response data

        Returns:
            DriveItem object or None
        """
        try:
            # Create a minimal DriveItem using the SDK
            driveitem = DriveItem(self.graph_client)
            driveitem._properties = data
            driveitem.set_property("id", data.get("id"))
            driveitem.set_property("name", data.get("name"))
            driveitem.set_property("webUrl", data.get("webUrl"))
            driveitem.set_property(
                "lastModifiedDateTime", data.get("lastModifiedDateTime")
            )

            # Handle the download URL
            if "@microsoft.graph.downloadUrl" in data:
                if not hasattr(driveitem, "additional_data"):
                    driveitem.additional_data = {}
                driveitem.additional_data["@microsoft.graph.downloadUrl"] = data[
                    "@microsoft.graph.downloadUrl"
                ]

            return driveitem
        except Exception as e:
            logger.warning(f"Failed to create DriveItem from API response: {e}")
            return None

    def _acquire_graph_token(self) -> str | None:
        """
        Acquire an access token for the Graph API.

        Returns:
            Access token string or None
        """
        if self.msal_app is None:
            return None

        token_response = self.msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        return token_response.get("access_token") if token_response else None

    def _convert_to_document(
        self,
        driveitem: DriveItem,
        drive_name: str,
        notion_row: NotionDatabaseRow,
    ) -> Document | None:
        """
        Convert a SharePoint DriveItem to a Document with Notion metadata.

        Args:
            driveitem: The SharePoint DriveItem
            drive_name: Name of the SharePoint drive
            notion_row: The Notion database row with metadata

        Returns:
            Document object or None if conversion fails
        """
        try:
            # Use the existing conversion function
            doc = _convert_driveitem_to_document_with_permissions(
                driveitem=driveitem,
                drive_name=drive_name or "",
                ctx=None,
                graph_client=self.graph_client,
                include_permissions=False,
            )

            if doc:
                # Enrich with Notion metadata
                doc.metadata.update(notion_row.metadata)
                doc.metadata["notion_row_id"] = notion_row.id
                doc.metadata["notion_url"] = notion_row.notion_url

                # Use Notion row ID as part of the document ID to ensure uniqueness
                doc.id = f"notion_sp_{notion_row.id}"

                return doc

        except Exception as e:
            logger.warning(
                f"Failed to convert DriveItem to Document: {driveitem.name} - {e}"
            )

        return None

    def _download_and_process_file(
        self,
        url: str,
        notion_row: NotionDatabaseRow,
    ) -> Document | None:
        """
        Download and process a SharePoint file directly from URL.

        This is a fallback method when DriveItem resolution fails but we have a direct URL.

        Args:
            url: Direct download URL
            notion_row: The Notion database row with metadata

        Returns:
            Document object or None if processing fails
        """
        try:
            # Get the access token
            token = self._acquire_graph_token()
            if not token:
                logger.warning("Failed to acquire Graph token for direct download")
                return None

            headers = {"Authorization": f"Bearer {token}"}

            # Try to get file info first
            share_token = self._encode_sharing_url(url)
            info_url = (
                f"https://graph.microsoft.com/v1.0/shares/{share_token}/driveItem"
            )

            info_response = requests.get(
                info_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )

            if info_response.status_code != 200:
                logger.warning(f"Cannot get file info for: {url}")
                return None

            file_info = info_response.json()
            file_name = file_info.get("name", "unknown")
            file_size = file_info.get("size", 0)
            download_url = file_info.get("@microsoft.graph.downloadUrl")
            web_url = file_info.get("webUrl", url)

            # Check size threshold
            if file_size > SHAREPOINT_CONNECTOR_SIZE_THRESHOLD:
                logger.warning(
                    f"File '{file_name}' exceeds size threshold ({file_size} bytes)"
                )
                return None

            # Check file extension
            file_ext = get_file_ext(file_name)
            if file_ext not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
                logger.warning(f"Unsupported file type: {file_name}")
                return None

            # Download content
            if not download_url:
                logger.warning(f"No download URL available for: {file_name}")
                return None

            try:
                content_bytes = _download_with_cap(
                    download_url,
                    REQUEST_TIMEOUT_SECONDS,
                    SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
                )
            except SizeCapExceeded:
                logger.warning(f"File '{file_name}' exceeded size cap during download")
                return None
            except Exception as e:
                logger.warning(f"Failed to download file '{file_name}': {e}")
                return None

            # Process content
            sections: list[TextSection | ImageSection] = []

            if file_ext in OnyxFileExtensions.IMAGE_EXTENSIONS:
                image_section, _ = store_image_and_create_section(
                    image_data=content_bytes,
                    file_id=f"notion_sp_{notion_row.id}",
                    display_name=file_name,
                    file_origin=FileOrigin.CONNECTOR,
                )
                image_section.link = web_url
                sections.append(image_section)
            else:
                # Extract text and images
                def _store_embedded_image(img_data: bytes, img_name: str) -> None:
                    try:
                        mime_type = get_image_type_from_bytes(img_data)
                    except ValueError:
                        return

                    if mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
                        return

                    image_section, _ = store_image_and_create_section(
                        image_data=img_data,
                        file_id=f"notion_sp_{notion_row.id}_img_{len(sections)}",
                        display_name=img_name or f"{file_name} - image {len(sections)}",
                        file_origin=FileOrigin.CONNECTOR,
                    )
                    image_section.link = web_url
                    sections.append(image_section)

                extraction_result = extract_text_and_images(
                    file=io.BytesIO(content_bytes),
                    file_name=file_name,
                    image_callback=_store_embedded_image,
                )

                if extraction_result.text_content:
                    sections.append(
                        TextSection(link=web_url, text=extraction_result.text_content)
                    )

            if not sections:
                logger.warning(f"No content extracted from: {file_name}")
                return None

            # Build metadata
            metadata = dict(notion_row.metadata)
            metadata["notion_row_id"] = notion_row.id
            metadata["notion_url"] = notion_row.notion_url
            metadata["sharepoint_url"] = url

            # Parse last modified time
            last_modified = file_info.get("lastModifiedDateTime")
            doc_updated_at = None
            if last_modified:
                doc_updated_at = datetime.fromisoformat(
                    last_modified.replace("Z", "+00:00")
                )

            return Document(
                id=f"notion_sp_{notion_row.id}",
                sections=sections,
                source=DocumentSource.SHAREPOINT,
                semantic_identifier=file_name,
                doc_updated_at=doc_updated_at,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(f"Failed to download and process file from {url}: {e}")
            return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Load all documents from the Notion database.

        Yields:
            Batches of Document objects
        """
        yield from self._generate_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """
        Poll for updated documents within a time range.

        Args:
            start: Start time (seconds since epoch)
            end: End time (seconds since epoch)

        Yields:
            Batches of Document objects
        """
        yield from self._generate_documents(start=start, end=end)

    def _generate_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        """
        Generate documents from Notion database rows.

        Args:
            start: Optional start time filter
            end: Optional end time filter

        Yields:
            Batches of Document objects
        """
        documents: list[Document] = []

        for notion_row in self._fetch_all_database_rows(start=start, end=end):
            # Skip rows without SharePoint URL
            if not notion_row.sharepoint_url:
                logger.debug(f"No SharePoint URL found for Notion row: {notion_row.id}")
                continue

            # Skip already processed rows
            if notion_row.id in self.processed_rows:
                logger.debug(f"Already processed Notion row: {notion_row.id}")
                continue

            logger.info(
                f"Processing Notion row {notion_row.id} with URL: {notion_row.sharepoint_url}"
            )

            # Try to resolve the URL to a DriveItem
            driveitem, drive_name = self._resolve_sharepoint_url_to_driveitem(
                notion_row.sharepoint_url
            )

            doc = None
            if driveitem:
                doc = self._convert_to_document(driveitem, drive_name or "", notion_row)

            # Fallback: try direct download if DriveItem resolution failed
            if doc is None:
                doc = self._download_and_process_file(
                    notion_row.sharepoint_url, notion_row
                )

            if doc:
                documents.append(doc)
                self.processed_rows.add(notion_row.id)

                # Yield batch when full
                if len(documents) >= self.batch_size:
                    yield documents
                    documents = []
            else:
                logger.warning(
                    f"Failed to process SharePoint file for Notion row: {notion_row.id}"
                )

        # Yield remaining documents
        if documents:
            yield documents


if __name__ == "__main__":
    # Test the connector
    connector = NotionSharepointConnector(
        notion_database_id=os.environ.get("NOTION_DATABASE_ID", ""),
        link_property_name=os.environ.get("NOTION_LINK_PROPERTY", "Link"),
    )

    connector.load_credentials(
        {
            "notion_integration_token": os.environ.get("NOTION_INTEGRATION_TOKEN", ""),
            "sp_client_id": os.environ.get("SHAREPOINT_CLIENT_ID", ""),
            "sp_client_secret": os.environ.get("SHAREPOINT_CLIENT_SECRET", ""),
            "sp_directory_id": os.environ.get("SHAREPOINT_CLIENT_DIRECTORY_ID", ""),
        }
    )

    print("Starting document indexing...")
    total_docs = 0

    for doc_batch in connector.load_from_state():
        print(f"Retrieved batch of {len(doc_batch)} documents")
        for doc in doc_batch:
            print(f"  - {doc.semantic_identifier}")
            print(f"    Metadata: {doc.metadata}")
        total_docs += len(doc_batch)

    print(f"\nTotal documents indexed: {total_docs}")
