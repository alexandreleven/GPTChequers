/**
 * Eleven Edition - Connector Credentials
 *
 * This file contains credential templates for all Eleven Edition custom
 * connectors. Each template defines the authentication methods and required fields.
 */

import { SharepointCredentialJson } from "@/lib/connectors/credentials";
import { CredentialTemplateWithAuth } from "@/lib/connectors/credentials";

export const ELEVEN_CREDENTIAL_TEMPLATES: Record<string, any> = {
  notion_sharepoint: {
    authentication_method: "client_credentials",
    authMethods: [
      {
        value: "client_secret",
        label: "Client Secret",
        fields: {
          sp_client_id: "",
          sp_client_secret: "",
          sp_directory_id: "",
        },
        description:
          "If you select this mode, the Notion Sharepoint connector will use a client secret to authenticate. You will need to provide the client ID and client secret.",
        disablePermSync: true,
      },
      {
        value: "certificate",
        label: "Certificate Authentication",
        fields: {
          sp_client_id: "",
          sp_directory_id: "",
          sp_certificate_password: "",
          sp_private_key: null,
        },
        description:
          "If you select this mode, the Notion Sharepoint connector will use a certificate to authenticate. You will need to provide the client ID, directory ID, certificate password, and PFX data.",
        disablePermSync: false,
      },
    ],
  } as CredentialTemplateWithAuth<SharepointCredentialJson>,
};
