from onyx.configs.constants import DocumentSource
from onyx.connectors.registry import ConnectorMapping

# Eleven custom connectors
ELEVEN_CONNECTOR_CLASS_MAP = {
    DocumentSource.NOTION_SHAREPOINT: ConnectorMapping(
        module_path="eleven.onyx.connectors.notion_sharepoint.connector",
        class_name="NotionSharepointConnector",
    ),
}
