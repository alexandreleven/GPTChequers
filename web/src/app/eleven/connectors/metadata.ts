/**
 * Eleven Edition - Connector Metadata
 *
 * This file contains metadata (icons, display names, categories)
 * for all Eleven Edition custom connectors.
 */

import { NotionSharepointIcon } from "./NotionSharepointIcon";
import { SourceCategory } from "@/lib/search/interfaces";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

export const ELEVEN_SOURCE_METADATA = {
  notion_sharepoint: {
    icon: NotionSharepointIcon,
    displayName: "Notion Sharepoint",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/eleven/notion_sharepoint`,
    isPopular: true,
  },
};
