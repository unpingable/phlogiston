import {
  buildAtprotoLoopbackClientMetadata,
  NodeOAuthClient,
  TokenRefreshError,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthClientMetadataInput,
  type OAuthServerAgent,
} from "@atproto/oauth-client-node";
import { join } from "node:path";

import { isP0, P0_SCOPE, CURATION_QUIET_INTERACTION_SCOPE, supportedPds, supportedIssuer } from "./p0.js";
import type { AppConfig } from "./config.js";
import { isLoopbackOrigin } from "./config.js";
import { SecretJsonFileStore } from "./storage.js";

const oauthLocks = new Map<string,Promise<void>>();
async function requestLock<T>(name: string, action: () => T | PromiseLike<T>): Promise<T> {
  const previous=oauthLocks.get(name)??Promise.resolve();let release!:()=>void;
  const turn=new Promise<void>(resolve=>{release=resolve;});const tail=previous.then(()=>turn);oauthLocks.set(name,tail);
  await previous;try{return await action();}finally{release();if(oauthLocks.get(name)===tail)oauthLocks.delete(name);}
}

export const OAUTH_SCOPE = [
  "atproto",
  "repo:app.bsky.feed.post?action=create",
  "repo:app.phlogiston.community.submit?action=create",
].join(" ");

export function clientMetadata(config: AppConfig): OAuthClientMetadataInput {
  const scope = isP0(config) ? config.readerEnabled === true ? CURATION_QUIET_INTERACTION_SCOPE : P0_SCOPE : OAUTH_SCOPE;
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
  const sessionStore = new SecretJsonFileStore<NodeSavedSession>(join(directory, "session"));
  const client = new NodeOAuthClient({
    clientMetadata: clientMetadata(config),
    allowHttp: isLoopbackOrigin(config.publicUrl),
    ...(config.plcDirectoryUrl === undefined ? {} : { plcDirectoryUrl: config.plcDirectoryUrl }),
    ...(config.handleResolverUrl === undefined ? {} : { handleResolver: config.handleResolverUrl }),
    stateStore: new SecretJsonFileStore<NodeSavedState>(join(directory, "state")),
    sessionStore,
    requestLock,
  });
  // The pinned SDK's OAuthServerAgent.revoke swallows HTTP/network failures.
  // Keep its DPoP/authentication implementation, but require its public request
  // method to acknowledge revocation before reporting provider confirmation.
  const fromIssuer = client.serverFactory.fromIssuer.bind(client.serverFactory);
  client.serverFactory.fromIssuer = async (...args) => {
    const server = await fromIssuer(...args);
    guardProviderSession(server);
    return server;
  };
  const revoke = client.revoke.bind(client);
  client.revoke = async did => {
    try { await revoke(did); } finally { await sessionStore.del(did); }
  };
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

/** Keep refresh permissions unchanged and preserve revocation failures from the pinned SDK. */
export function guardProviderSession(server: OAuthServerAgent): void {
    server.revoke = async token => { await server.request("revocation", {token}); };
    const refresh = server.refresh.bind(server);
    server.refresh = async previous => {
      const refreshed = await refresh(previous);
      const scope = (value: string) => value.split(/\s+/).filter(Boolean).sort().join(" ");
      if (scope(previous.scope) !== scope(refreshed.scope)) {
        await server.revoke(refreshed.refresh_token ?? refreshed.access_token).catch(() => undefined);
        throw new TokenRefreshError(previous.sub,"Provider changed permissions during refresh; explicit consent is required");
      }
      return refreshed;
    };
}
