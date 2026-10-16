import {
  buildAtprotoLoopbackClientMetadata,
  NodeOAuthClient,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthClientMetadataInput,
} from "@atproto/oauth-client-node";
import { join } from "node:path";

import { isP0, P0_SCOPE, CURATION_QUIET_SCOPE, supportedPds, supportedIssuer } from "./p0.js";
import type { AppConfig } from "./config.js";
import { isLoopbackOrigin } from "./config.js";
import { SecretJsonFileStore } from "./storage.js";

export const OAUTH_SCOPE = [
  "atproto",
  "repo:app.bsky.feed.post?action=create",
  "repo:app.phlogiston.community.submit?action=create",
].join(" ");

export function clientMetadata(config: AppConfig): OAuthClientMetadataInput {
  const scope = isP0(config) ? config.readerEnabled === true ? CURATION_QUIET_SCOPE : P0_SCOPE : OAUTH_SCOPE;
  const redirect = `${config.publicUrl}/oauth/callback`;
  if (isLoopbackOrigin(config.publicUrl)) {
    const metadata = buildAtprotoLoopbackClientMetadata({ redirect_uris: [redirect], scope });
    return config.readerEnabled === true ? { ...metadata, client_name: "Phlogiston" } : metadata;
  }
  return {
    client_id: `${config.publicUrl}/oauth-client-metadata.json`,
    client_name: config.readerEnabled === true ? "Phlogiston" : config.communityName,
    client_uri: config.publicUrl,
    redirect_uris: [redirect],
    scope,
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
    token_endpoint_auth_method: "none",
    application_type: "web",
    dpop_bound_access_tokens: true,
  };
}

export function createOAuthClient(config: AppConfig): NodeOAuthClient {
  const directory = join(config.runtimeDirectory, "oauth");
  const client = new NodeOAuthClient({
    clientMetadata: clientMetadata(config),
    allowHttp: isLoopbackOrigin(config.publicUrl),
    ...(config.plcDirectoryUrl === undefined ? {} : { plcDirectoryUrl: config.plcDirectoryUrl }),
    ...(config.handleResolverUrl === undefined ? {} : { handleResolver: config.handleResolverUrl }),
    stateStore: new SecretJsonFileStore<NodeSavedState>(join(directory, "state")),
    sessionStore: new SecretJsonFileStore<NodeSavedSession>(join(directory, "session")),
  });
  if (isP0(config)) {
    const resource = client.oauthResolver.getResourceServerMetadata.bind(client.oauthResolver);
    client.oauthResolver.getResourceServerMetadata = (url, options) => {
      if (!supportedPds(config,String(url))) throw new Error("unsupported PDS: no fallback");
      return resource(url, options);
    };
    const metadata = client.oauthResolver.getAuthorizationServerMetadata.bind(client.oauthResolver);
    client.oauthResolver.getAuthorizationServerMetadata = (issuer, options) => {
      if (!supportedIssuer(config, String(issuer))) throw new Error("unsupported authorization provider");
      return metadata(issuer, options);
    };
    const authorize = client.authorize.bind(client);
    client.authorize = async (input, options) => {
      const identity = await client.oauthResolver.resolveIdentity(input, {noCache:true});
      const service = identity.didDoc.service?.find(s => s.id === "#atproto_pds" || s.id === `${identity.did}#atproto_pds`);
      if (!identity.did.startsWith("did:plc:") || !service || service.type !== "AtprotoPersonalDataServer" || typeof service.serviceEndpoint !== "string" || !supportedPds(config,service.serviceEndpoint)) throw new Error("unsupported identity custody; no fallback");
      return authorize(identity.did, options);
    };
  }
  return client;
}
