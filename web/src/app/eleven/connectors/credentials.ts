/**
 * Eleven Edition - Connector Credentials
 *
 * This file contains credential templates for all Eleven Edition custom
 * connectors. Each template defines the authentication methods and required fields.
 */

import {
  NotionSharepointCredentialJson,
  CredentialTemplateWithAuth,
} from "@/lib/connectors/credentials";

export const ELEVEN_CREDENTIAL_TEMPLATES: Record<string, any> = {
  notion_sharepoint: {
    notion_integration_token: "",
    sp_client_id: "",
    sp_client_secret: "",
    sp_directory_id: "",
  } as NotionSharepointCredentialJson,
};
