import { createHash } from "node:crypto";
import {
  chmodSync, closeSync, constants, fstatSync, mkdirSync, openSync, readFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { DatabaseSync } from "node:sqlite";
import type { OAuthSession } from "@atproto/oauth-client-node";
import type { AppConfig } from "./config.js";
import { HttpError } from "./http-error.js";

export const P0_SCOPE = "atproto repo:app.phlogiston.community.submit?action=create";
const APPVIEW_AUDIENCE = "did:web:api.bsky.app%23bsky_appview";
const appviewScope = (name: string): string => `rpc:${name}?aud=${APPVIEW_AUDIENCE}`;
export const READER_SCOPE = [
  P0_SCOPE,
  appviewScope("app.bsky.feed.getTimeline"),
  appviewScope("app.bsky.feed.getPostThread"),
  appviewScope("app.bsky.actor.getPreferences"),
  appviewScope("app.bsky.labeler.getServices"),
].join(" ");
export const QUIET_SCOPE = [
  READER_SCOPE,
  appviewScope("app.bsky.graph.muteThread"),
  appviewScope("app.bsky.graph.unmuteThread"),
].join(" ");
export const FEED_SCOPE = [
  READER_SCOPE,
  appviewScope("app.bsky.feed.getFeed"),
  appviewScope("app.bsky.feed.getFeedGenerators"),
].join(" ");
export const FEED_QUIET_SCOPE = [
  FEED_SCOPE,
  appviewScope("app.bsky.graph.muteThread"),
  appviewScope("app.bsky.graph.unmuteThread"),
].join(" ");
export const CURATION_SCOPE = [FEED_SCOPE, appviewScope("app.bsky.actor.getProfile")].join(" ");
export const CURATION_QUIET_SCOPE = [CURATION_SCOPE, appviewScope("app.bsky.graph.muteThread"), appviewScope("app.bsky.graph.unmuteThread")].join(" ");
export function hasCurationScope(scope: string, config?: AppConfig): boolean {
  return config !== undefined && isP0(config) && config.readerEnabled === true &&
    (exactScope(scope, CURATION_SCOPE) || exactScope(scope, CURATION_QUIET_SCOPE));
}
export const isP0 = (config: AppConfig): boolean => config.profile === "p0";

function exactScope(actual: string, expected: string): boolean {
  const words = actual.split(/\s+/).filter(Boolean);
  const expectedWords = expected.split(" ");
  return words.length === expectedWords.length && new Set(words).size === words.length &&
    expectedWords.every(word => words.includes(word));
}

export function hasReaderScope(scope: string, config?: AppConfig): boolean {
  return config !== undefined && isP0(config) && config.readerEnabled === true &&
    (exactScope(scope, READER_SCOPE) || exactScope(scope, QUIET_SCOPE) ||
      exactScope(scope, FEED_SCOPE) || exactScope(scope, FEED_QUIET_SCOPE) || exactScope(scope, CURATION_SCOPE) || exactScope(scope, CURATION_QUIET_SCOPE));
}

export function hasQuietScope(scope: string, config?: AppConfig): boolean {
  return config !== undefined && isP0(config) && config.readerEnabled === true &&
    (exactScope(scope, QUIET_SCOPE) || exactScope(scope, FEED_QUIET_SCOPE) || exactScope(scope, CURATION_QUIET_SCOPE));
}

export function hasFeedScope(scope: string, config?: AppConfig): boolean {
  return config !== undefined && isP0(config) && config.readerEnabled === true &&
    (exactScope(scope, FEED_SCOPE) || exactScope(scope, FEED_QUIET_SCOPE) || exactScope(scope, CURATION_SCOPE) || exactScope(scope, CURATION_QUIET_SCOPE));
}

/** Inspect the opened control object rather than following a replaced pathname. */
function controlOpen(path: string | undefined): boolean {
  let fd: number | undefined;
  try {
    if (!path) return false;
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.size > 16 || (stat.mode & 0o022) !== 0 ||
        (stat.uid !== 0 && stat.uid !== process.getuid?.())) return false;
    return readFileSync(fd, "utf8") === "open\n";
  } catch {
    return false;
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}

export async function requireSiteWrites(config: AppConfig): Promise<void> {
  if (isP0(config) && !controlOpen(config.sitePausePath)) {
    throw new HttpError(503, "New site submissions are suspended. Reads and outcome checks remain available.");
  }
}

export async function intakeOpen(config: AppConfig): Promise<boolean> {
  return controlOpen(config.admissionPausePath);
}

/** bsky.social is an authorization entryway, never an accepted PDS audience. */
export function blueskyOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port &&
      url.pathname === "/" && !url.search && !url.hash &&
      url.hostname.endsWith(".host.bsky.network") &&
      url.hostname.slice(0, -".host.bsky.network".length).split(".").every(label =>
        /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
  } catch {
    return false;
  }
}

export function supportedPds(config: AppConfig, value: string): boolean {
  if (config.p0HostedPdsOrigin) return exactOrigin(value, config.p0HostedPdsOrigin) || (config.p0AllowBluesky === true && blueskyOrigin(value));
  if (blueskyOrigin(value)) return true;
  if (!config.p0TestPdsOrigin) return false;
  return exactOrigin(value, config.p0TestPdsOrigin);
}

function exactOrigin(value: string, expected: string): boolean {
  try {
    const url = new URL(value);
    return url.origin === expected && url.protocol === "https:" &&
      !url.username && !url.password && !url.port && url.pathname === "/" &&
      !url.search && !url.hash;
  } catch {
    return false;
  }
}

export async function requireBlueskySession(
  session: OAuthSession, did: string, config?: AppConfig,
): Promise<string> {
  const info = await session.getTokenInfo();
  if (!did.startsWith("did:plc:") || session.did !== did || info.sub !== did ||
      !supportedSessionProvider(config, info.iss, info.aud)) {
    throw new HttpError(403, config?.p0AllowBluesky
      ? "This account's identity and hosting do not match a supported Bluesky or Phlogiston provider. No alternate provider is used."
      : config?.p0HostedPdsOrigin
      ? "This playground accepts only accounts on the configured Phlogiston PDS. No alternate provider is used."
      : "This playground supports ordinary Bluesky-hosted accounts only. No alternate provider is used.");
  }
  if (!exactScope(info.scope, P0_SCOPE) && !hasReaderScope(info.scope, config)) {
    throw new HttpError(403, config?.readerEnabled
      ? "Reconnect with one of the exact Phlogiston submission, reader, or conversation grants required here."
      : "Reconnect with the submission-only grant required here.");
  }
  return info.scope;
}

export function supportedIssuer(config: AppConfig, issuer: string): boolean {
  if (config.p0HostedPdsOrigin) return issuer === config.p0HostedPdsOrigin || (config.p0AllowBluesky === true && issuer === "https://bsky.social");
  return issuer === "https://bsky.social" || issuer === config.p0TestPdsOrigin;
}

function supportedSessionProvider(config: AppConfig | undefined, issuer: string, audience: string): boolean {
  if (issuer === "https://bsky.social" && blueskyOrigin(audience)) return !config?.p0HostedPdsOrigin || config.p0AllowBluesky === true;
  const exact = config?.p0HostedPdsOrigin ?? config?.p0TestPdsOrigin;
  return exact !== undefined && issuer === exact && exactOrigin(audience, exact);
}

export interface Reservation {
  key: string;
  did: string;
  subject: { uri: string; cid: string };
  operationId: string;
  createdAt: number;
  active: boolean;
  siteIntent: boolean;
  submission?: { uri: string; cid: string };
  decision?: string;
}
interface Row {
  key: string; did: string; subject_uri: string; subject_cid: string;
  operation_id: string; created_at: number; active: number; site_intent: number;
  submission_uri: string | null; submission_cid: string | null; decision: string | null;
}

function processIdentity(pid: number): string | null {
  try {
    const fields = readFileSync(`/proc/${pid}/stat`, "utf8").split(") ").at(-1)!.split(" ");
    return `${pid}:${fields[19]}`;
  } catch {
    return null;
  }
}

/** SQLite releases transaction locks on process loss. Execution claims identify
 * the actual local producer; a dead producer's write is reconciled using its
 * original durable journal before any new mutation attempt.
 */
export class P0Reservations {
  private static readonly inFlight = new Set<string>();
  private readonly path: string;
  public constructor(
    directory: string,
    private readonly now = () => Date.now(),
    private readonly binding = "legacy-local-fixture",
  ) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    this.path = resolve(directory, "intake.sqlite3");
  }

  private database(): DatabaseSync {
    const db = new DatabaseSync(this.path);
    try {
      chmodSync(this.path, 0o600);
      db.exec("PRAGMA busy_timeout=100; PRAGMA synchronous=FULL;");
      db.exec(`
        CREATE TABLE IF NOT EXISTS mode_binding(value TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS reservations(
          key TEXT PRIMARY KEY, did TEXT NOT NULL, subject_uri TEXT NOT NULL,
          subject_cid TEXT NOT NULL, operation_id TEXT UNIQUE NOT NULL,
          created_at INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
          site_intent INTEGER NOT NULL CHECK(site_intent IN (0,1)), submission_uri TEXT, submission_cid TEXT,
          decision TEXT
        );
        CREATE INDEX IF NOT EXISTS active_did ON reservations(active,did);
        CREATE INDEX IF NOT EXISTS daily_did ON reservations(did,site_intent,created_at);
        CREATE INDEX IF NOT EXISTS recent_did ON reservations(did,active DESC,created_at DESC,key);
        CREATE TABLE IF NOT EXISTS execution(did TEXT PRIMARY KEY,owner TEXT NOT NULL);
      `);
      return db;
    } catch (error) {
      db.close();
      throw error;
    }
  }

  /** Callbacks are synchronous: no provider operation occurs under this lock. */
  private transaction<T>(fn: (db: DatabaseSync) => T): T {
    const db = this.database();
    try {
      db.exec("BEGIN IMMEDIATE");
      const existing = db.prepare("SELECT value FROM mode_binding LIMIT 1").get() as
        { value: string } | undefined;
      if (existing && existing.value !== this.binding) {
        throw new HttpError(503, "Intake custody belongs to another community or qualification mode.");
      }
      if (!existing) db.prepare("INSERT INTO mode_binding VALUES(?)").run(this.binding);
      const result = fn(db);
      db.exec("COMMIT");
      return result;
    } catch (error) {
      try { db.exec("ROLLBACK"); } catch { /* transaction may not have begun */ }
      throw error;
    } finally {
      db.close();
    }
  }

  public async reserve(
    did: string, community: string, subject: Reservation["subject"],
    operationId: string, siteIntent = true,
  ): Promise<Reservation> {
    return this.transaction(db => {
      const key = createHash("sha256")
        .update(JSON.stringify([community, did, subject.uri, subject.cid])).digest("hex");
      const existing = db.prepare("SELECT * FROM reservations WHERE key=?").get(key) as Row | undefined;
      if (existing) return this.decode(existing);
      const count = (sql: string, ...args: (string | number)[]): number =>
        Number((db.prepare(sql).get(...args) as { n: number }).n);
      if (count("SELECT count(*) n FROM reservations WHERE active=1") >= 100 ||
          count("SELECT count(*) n FROM reservations WHERE active=1 AND did=?", did) >= 3 ||
          (siteIntent && count(
            "SELECT count(*) n FROM reservations WHERE did=? AND site_intent=1 AND created_at>?",
            did, this.now() - 86400000,
          ) >= 10)) {
        throw new HttpError(429, "Submission capacity is full for now. Nothing was written; try later.");
      }
      const createdAt = this.now();
      db.prepare(`INSERT INTO reservations(
        key,did,subject_uri,subject_cid,operation_id,created_at,active,site_intent
      ) VALUES(?,?,?,?,?,?,1,?)`).run(
        key, did, subject.uri, subject.cid, operationId, createdAt, siteIntent ? 1 : 0,
      );
      return { key, did, subject, operationId, createdAt, active: true, siteIntent };
    });
  }

  public async find(community: string, did: string, subject: Reservation["subject"]): Promise<Reservation | null> {
    return this.transaction(db => {
      const key = createHash("sha256").update(JSON.stringify([community, did, subject.uri, subject.cid])).digest("hex");
      const row = db.prepare("SELECT * FROM reservations WHERE key=?").get(key) as Row | undefined;
      return row ? this.decode(row) : null;
    });
  }

  public async update(
    id: string, change: Partial<Pick<Reservation, "submission" | "active" | "decision">>,
  ): Promise<void> {
    this.transaction(db => {
      const row = db.prepare("SELECT * FROM reservations WHERE operation_id=?").get(id) as Row | undefined;
      if (!row) throw new Error("missing reservation");
      if (change.submission && row.submission_uri &&
          (row.submission_uri !== change.submission.uri || row.submission_cid !== change.submission.cid)) {
        throw new HttpError(409, "This exact intent is bound to its first qualified submission reference; an alias cannot replace it.");
      }
      db.prepare(`UPDATE reservations SET active=?,submission_uri=?,submission_cid=?,decision=?
        WHERE operation_id=?`).run(
        change.active === undefined ? row.active : change.active ? 1 : 0,
        change.submission?.uri ?? row.submission_uri,
        change.submission?.cid ?? row.submission_cid,
        change.decision ?? row.decision, id,
      );
    });
  }

  public async byAuthor(did: string): Promise<Reservation[]> {
    return this.transaction(db => (db.prepare(`SELECT * FROM reservations
      WHERE did=? ORDER BY active DESC,created_at DESC,key LIMIT 25`).all(did) as unknown as Row[])
      .map(row => this.decode(row)));
  }

  public async active(): Promise<Reservation[]> {
    return this.transaction(db => (db.prepare(`SELECT * FROM reservations
      WHERE active=1 ORDER BY created_at,key LIMIT 100`).all() as unknown as Row[])
      .map(row => this.decode(row)));
  }

  public async execute<T>(did: string, fn: () => Promise<T>): Promise<T> {
    const owner = processIdentity(process.pid);
    if (!owner) throw new HttpError(503, "Execution identity unavailable; no write attempted.");
    const claim = `${this.path}\n${did}`;
    this.transaction(db => {
      const previous = db.prepare("SELECT owner FROM execution WHERE did=?").get(did) as
        { owner: string } | undefined;
      if (previous && (previous.owner === owner ? P0Reservations.inFlight.has(claim) :
          processIdentity(Number(previous.owner.split(":")[0])) === previous.owner)) {
        throw new HttpError(503, "An action for this account is already running; no new attempt was made.");
      }
      db.prepare(`INSERT INTO execution(did,owner) VALUES(?,?)
        ON CONFLICT(did) DO UPDATE SET owner=excluded.owner`).run(did, owner);
    });
    P0Reservations.inFlight.add(claim);
    try {
      return await fn();
    } finally {
      try {
        for (let attempt = 0; ; attempt++) {
          try {
            this.transaction(db => {
              db.prepare("DELETE FROM execution WHERE did=? AND owner=?").run(did, owner);
            });
            break;
          } catch (error) {
            const busy = error instanceof Error && /(?:locked|busy)/i.test(error.message);
            if (!busy || attempt >= 9) throw error;
            await delay(25 * (attempt + 1));
          }
        }
      } finally {
        // A completed same-process action is reclaimable even if release failed.
        // Other live processes and genuinely in-flight work remain fenced.
        P0Reservations.inFlight.delete(claim);
      }
    }
  }

  private decode(row: Row): Reservation {
    return {
      key: row.key, did: row.did,
      subject: { uri: row.subject_uri, cid: row.subject_cid },
      operationId: row.operation_id, createdAt: row.created_at,
      active: row.active === 1, siteIntent: row.site_intent === 1,
      ...(row.submission_uri && row.submission_cid ? {
        submission: { uri: row.submission_uri, cid: row.submission_cid },
      } : {}),
      ...(row.decision ? { decision: row.decision } : {}),
    };
  }
}
