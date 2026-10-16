import { createHash } from "node:crypto";
import { createConnection } from "node:net";

export interface AuthenticatedSession {
  did: string;
  sessionRef: string;
}

export interface SessionVerifier {
  restore(cookieHeader: string): Promise<AuthenticatedSession>;
}

export interface AuthorityEnvelope {
  operationId: string;
  action: "root_admit" | "root_remove" | "reply_remove" | "reply_restore" | "root_decline" | "root_status";
  authenticatedDid: string;
  target: { uri: string; cid: string };
  reason?: string;
  controllingAction?: { uri: string; cid: string };
}

export interface AuthorityResponse {
  ok: boolean;
  result?: Record<string, unknown>;
  error?: string;
}

export type ModeratorCommand =
  | { kind: "decline-root"; submissionUri: string; submissionCid: string; reason: string }
  | { kind: "admit-root"; submissionUri: string; submissionCid: string }
  | { kind: "remove-root"; admissionUri: string; admissionCid: string; reason: string }
  | { kind: "remove-reply"; admissionUri: string; admissionCid: string; reason: string }
  | { kind: "restore-reply"; admissionUri: string; admissionCid: string; controllingActionUri: string; controllingActionCid: string; reason: string };

export interface AuthorityRequester {
  request(envelope: AuthorityEnvelope): Promise<AuthorityResponse>;
}

export interface BrowserModerationRequest {
  cookieHeader: string;
  sameOrigin: boolean;
  csrfValid: boolean;
  command: ModeratorCommand;
}

export class TrustedModeratorBroker {
  public constructor(
    private readonly sessions: SessionVerifier,
    private readonly authority: AuthorityRequester,
    private readonly moderatorDids: ReadonlySet<string>,
  ) {}

  public async moderate(request: BrowserModerationRequest): Promise<AuthorityResponse> {
    if (!request.sameOrigin || !request.csrfValid) throw new Error("invalid browser request");
    validateCommand(request.command);
    const session = await this.sessions.restore(request.cookieHeader);
    if (!this.moderatorDids.has(session.did)) throw new Error("moderator permission required");
    return this.authority.request(toEnvelope(request.command, session.did));
  }
}

export class UnixAuthorityRequester implements AuthorityRequester {
  public constructor(private readonly socketPath: string) {}

  public async request(envelope: AuthorityEnvelope): Promise<AuthorityResponse> {
    return new Promise((resolve, reject) => {
      const socket = createConnection(this.socketPath);
      let response = "";
      let settled = false;
      socket.setEncoding("utf8");
      socket.setTimeout(10_000);
      socket.on("connect", () => socket.write(`${JSON.stringify(envelope)}\n`));
      socket.on("data", (chunk: string) => {
        response += chunk;
        if (Buffer.byteLength(response) > 64 * 1024) { socket.destroy(new Error("authority response exceeds bounded size")); return; }
        if (!response.includes("\n")) return;
        settled = true;
        socket.end();
        try {
          resolve(JSON.parse(response.slice(0, response.indexOf("\n"))) as AuthorityResponse);
        } catch (error) {
          reject(error);
        }
      });
      socket.on("timeout", () => socket.destroy(new Error("communityd request timed out")));
      socket.on("error", reject);
      socket.on("close", () => {
        if (!settled) reject(new Error("communityd closed without a response"));
      });
    });
  }
}

function toEnvelope(command: ModeratorCommand, did: string): AuthorityEnvelope {
  const target = "admissionUri" in command
    ? { uri: command.admissionUri, cid: command.admissionCid }
    : { uri: command.submissionUri, cid: command.submissionCid };
  const action = command.kind === "decline-root" ? "root_decline" : command.kind === "admit-root"
    ? "root_admit"
    : command.kind === "remove-root"
      ? "root_remove"
      : command.kind === "remove-reply"
        ? "reply_remove"
        : "reply_restore";
  return {
    operationId: `web:${createHash("sha256").update(JSON.stringify({ did, command })).digest("hex")}`,
    action,
    authenticatedDid: did,
    target,
    ...("reason" in command ? { reason: command.reason } : {}),
    ...(command.kind === "restore-reply" ? { controllingAction: { uri: command.controllingActionUri, cid: command.controllingActionCid } } : {}),
  };
}

function validateCommand(command: ModeratorCommand): void {
  const exact = "admissionUri" in command
    ? [command.admissionUri, command.admissionCid]
    : [command.submissionUri, command.submissionCid];
  if (exact.some((value) => value.trim().length === 0)) {
    throw new Error("moderation target must be an exact URI and CID");
  }
  if ("reason" in command && (command.reason.trim().length === 0 || command.reason.length > 2000)) {
    throw new Error("a decision reason is required");
  }
  if (command.kind === "restore-reply" && (
    command.controllingActionUri.trim().length === 0 ||
    command.controllingActionCid.trim().length === 0
  )) {
    throw new Error("restoration requires the exact controlling action");
  }
}
