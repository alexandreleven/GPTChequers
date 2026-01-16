/**
 * Eleven Edition - Connector Configurations
 *
 * This file contains form configurations for all Eleven Edition custom
 * connectors. Each configuration defines form fields and their validations.
 */

import { ConnectionConfiguration } from "@/lib/connectors/connectors";

export const ELEVEN_CONNECTOR_CONFIGS: Record<string, ConnectionConfiguration> =
  {
    notion_sharepoint: {
      description: "Configure Notion Sharepoint connector",
      subtext:
        "Index SharePoint documents referenced in a Notion database. The connector reads URLs from a specified column and enriches documents with Notion metadata.",
      values: [
        {
          type: "text",
          query: "Enter Notion Database ID:",
          label: "Notion Database ID",
          name: "notion_database_id",
          optional: false,
          description: `The ID of the Notion database containing SharePoint links.
• You can find this in the database URL: notion.so/<workspace>/<database_id>
• Format: 32-character hexadecimal string (e.g., 8aea83e7d9884021846a80e550319a09)`,
        },
        {
          type: "text",
          query: "Enter Link Column Name:",
          label: "Link Property Name",
          name: "link_property_name",
          optional: true,
          default: "Link",
          description: `The name of the Notion database column containing SharePoint URLs.
• Default: "Link"
• Supports URL, Rich Text, and Files property types
• SharePoint sharing links and direct URLs are both supported`,
        },
      ],
      advanced_values: [],
    },
  };
