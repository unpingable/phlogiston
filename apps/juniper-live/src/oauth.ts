import {
  buildAtprotoLoopbackClientMetadata,
  NodeOAuthClient,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthClientMetadataInput,
} from "@atproto/oauth-client-node";
import { join } from "node:path";
import { OAUTH_SCOPE } from "./constants.js";
import { type AppConfig, isLoopbackOrigin } from "./config.js";
import { SecretJsonFileStore } from "./storage.js";

export function clientMetadata(config: AppConfig): OAuthClientMetadataInput {
  const redirect = `${config.publicUrl}/oauth/callback`;
  if (isLoopbackOrigin(config.publicUrl)) {
    return buildAtprotoLoopbackClientMetadata({
      redirect_uris: [redirect],
      scope: OAUTH_SCOPE,
    });
  }
  return {
    client_id: `${config.publicUrl}/oauth-client-metadata.json`,
    client_name: "Juniper Commons",
    client_uri: config.publicUrl,
    redirect_uris: [redirect],
    scope: OAUTH_SCOPE,
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
    token_endpoint_auth_method: "none",
    application_type: "web",
    dpop_bound_access_tokens: true,
  };
}

export function createOAuthClient(config: AppConfig): NodeOAuthClient {
  const authDirectory = join(config.runtimeDirectory, "oauth");
  return new NodeOAuthClient({
    clientMetadata: clientMetadata(config),
    allowHttp: isLoopbackOrigin(config.publicUrl),
    stateStore: new SecretJsonFileStore<NodeSavedState>(join(authDirectory, "state")),
    sessionStore: new SecretJsonFileStore<NodeSavedSession>(
      join(authDirectory, "session"),
    ),
  });
}
