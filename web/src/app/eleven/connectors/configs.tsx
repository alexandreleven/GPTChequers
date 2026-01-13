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
        "Connect to your Notion-integrated Sharepoint instance to index documents and pages.",
      values: [
        {
          type: "list",
          query: "Enter Notion Sharepoint sites:",
          label: "Sites",
          name: "sites",
          optional: true,
          description: `• If no sites are specified, all sites in your organization will be indexed (Sites.Read.All permission required).
• Specifying 'https://yourcompany.sharepoint.com/sites/support' for example only indexes this site.
• Specifying 'https://yourcompany.sharepoint.com/sites/support/subfolder' for example only indexes this folder.
• This connector integrates Notion metadata with Sharepoint documents.`,
        },
      ],
      advanced_values: [
        {
          type: "checkbox",
          query: "Index Documents:",
          label: "Index Documents",
          name: "include_site_documents",
          optional: true,
          default: true,
          description:
            "Index documents of all Sharepoint libraries or folders defined above.",
        },
        {
          type: "checkbox",
          query: "Index ASPX Sites:",
          label: "Index ASPX Sites",
          name: "include_site_pages",
          optional: true,
          default: true,
          description:
            "Index aspx-pages of all Sharepoint sites defined above, even if a library or folder is specified.",
        },
      ],
    },
  };
