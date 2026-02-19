"use client";

import {
  ConfigurableSources,
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import Sidebar from "../../../../sections/sidebar/CreateConnectorSidebar";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import Button from "@/refresh-components/buttons/Button";
import { isValidSource, getSourceMetadata } from "@/lib/sources";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { Credential } from "@/lib/connectors/credentials";
import { useFederatedConnectors } from "@/lib/hooks";
import Text from "@/refresh-components/texts/Text";
// === ELEVEN EDITION START ===
import { ELEVEN_EDITION_ENABLED } from "@/lib/constants";
import { ELEVEN_CONNECTOR_SOURCES } from "@/app/eleven/connectors";
// === ELEVEN EDITION END ===

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  // Fetch existing credentials for this connector type
  const { data: existingCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector),
    errorHandlingFetcher
  );

  // === ELEVEN EDITION START ===
  // Check if this is an Eleven Edition connector and if Eleven Edition is enabled
  const isElevenConnector = ELEVEN_CONNECTOR_SOURCES.includes(connector as any);
  if (isElevenConnector && !ELEVEN_EDITION_ENABLED) {
    return (
      <FormProvider connector={connector}>
        <div className="flex justify-center w-full h-full">
          <Sidebar />
          <div className="mt-12 w-full max-w-3xl mx-auto">
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>This connector requires Eleven Edition to be enabled.</p>
              </HeaderTitle>
              <Button
                onClick={() => window.open("/admin/add-connector", "_self")}
                className="mr-auto"
              >
                Back to Connectors
              </Button>
            </div>
          </div>
        </div>
      </FormProvider>
    );
  }
  // === ELEVEN EDITION END ===

  // Check if the connector is valid
  if (!isValidSource(connector)) {
    return (
      <FormProvider connector={connector}>
        <div className="flex justify-center w-full h-full">
          <Sidebar />
          <div className="mt-12 w-full max-w-3xl mx-auto">
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>&lsquo;{connector}&rsquo; is not a valid Connector Type!</p>
              </HeaderTitle>
              <Button
                onClick={() => window.open("/admin/indexing/status", "_self")}
                className="mr-auto"
              >
                {" "}
                Go home{" "}
              </Button>
            </div>
          </div>
        </div>
      </FormProvider>
    );
  }

  const sourceMetadata = getSourceMetadata(connector);
  const supportsFederated = sourceMetadata.federated === true;

  // Only show federated form if explicitly requested via URL parameter
  const showFederatedForm = mode === "federated" && supportsFederated;

  // For federated form, use the specialized form without FormProvider
  if (showFederatedForm) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <FederatedConnectorForm connector={connector} />
        </div>
      </div>
    );
  }

  // For regular connectors, use the existing flow
  return (
    <FormProvider connector={connector}>
      <div className="flex justify-center w-full h-full">
        <Sidebar />
        <div className="mt-12 w-full max-w-3xl mx-auto">
          <AddConnector connector={connector} />
        </div>
      </div>
    </FormProvider>
  );
}
