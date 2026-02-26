/**
 * Eleven Edition - Connectors Entry Point
 *
 * This file serves as the single entry point for all Eleven Edition
 * custom connectors. It exports metadata, configurations, and credentials
 * that will be merged into the main Chequers Capital system.
 */

export { ELEVEN_SOURCE_METADATA } from "./metadata";
export { ELEVEN_CONNECTOR_CONFIGS } from "./configs";
export { ELEVEN_CREDENTIAL_TEMPLATES } from "./credentials";

/**
 * List of all Eleven Edition connector source types.
 * Used to filter connectors when Eleven Edition is not enabled.
 */
export const ELEVEN_CONNECTOR_SOURCES = [
  "notion_sharepoint",
  // Add future Eleven connectors here
] as const;
