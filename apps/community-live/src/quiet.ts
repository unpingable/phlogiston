import { closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { HttpError } from "./http-error.js";

export interface QuietRecord {
  root: string;
  status: "unknown" | "muted" | "unmuted";
  updatedAt: string;
}

function validateDid(did: string): void {
  if (!/^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$/.test(did) || did.length > 2048) {
    throw new HttpError(400, "A valid account DID is required.");
  }
}

function validateRoot(root: string): void {
  const match = /^at:\/\/(did:[a-z0-9]+:[A-Za-z0-9._:%-]+)\/app\.bsky\.feed\.post\/([A-Za-z0-9._~:-]+)$/.exec(root);
  if (!match || root.length > 4096 || match[2] === "." || match[2] === "..") {
    throw new HttpError(400, "A post URI with a DID authority is required.");
  }
  validateDid(match[1]!);
}

/** App-local observations of normal user API effects, not an ACL or policy authority. */
export class QuietStore {
  private static readonly inFlight = new Set<string>();
  private readonly db: DatabaseSync;
  private readonly path: string;

  /** Delete everything this store holds for one account (account erasure); returns the rows removed. */
  public eraseAccount(did: string): number {
    return Number(this.db.prepare("DELETE FROM quiet WHERE did=?").run(did).changes);
  }
  public constructor(path: string) {
    this.path = resolve(path);
    const directory = dirname(this.path);
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const dir = lstatSync(directory);
    if (!dir.isDirectory() || (dir.mode & 0o077) !== 0 || dir.uid !== process.getuid?.()) {
      throw new Error("Quiet store directory must be private and owned by the runtime user");
    }
    const fd = openSync(this.path, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
    try {
      const file = fstatSync(fd);
      if (!file.isFile() || (file.mode & 0o077) !== 0 || file.uid !== process.getuid?.()) {
        throw new Error("Quiet store file must be private and owned by the runtime user");
      }
    } finally {
      closeSync(fd);
    }
    this.db = new DatabaseSync(this.path);
    this.db.exec(`PRAGMA busy_timeout = 5000;
      CREATE TABLE IF NOT EXISTS quiet (
        did TEXT NOT NULL, root TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('unknown','muted','unmuted')),
        updatedAt TEXT NOT NULL, PRIMARY KEY(did,root));`);
  }

  public close(): void { this.db.close(); }

  private key(did: string): string { return `${this.path}\n${did}`; }

  public list(did: string): QuietRecord[] {
    validateDid(did);
    return this.db.prepare("SELECT root,status,updatedAt FROM quiet WHERE did=? ORDER BY updatedAt DESC,root LIMIT 100")
      .all(did) as unknown as QuietRecord[];
  }

  private save(did: string, root: string, status: QuietRecord["status"], reserve = false): void {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const existing = this.db.prepare("SELECT status FROM quiet WHERE did=? AND root=?").get(did, root) as
        {status: QuietRecord["status"]} | undefined;
      if (reserve && existing?.status === "unknown") {
        throw new HttpError(409, "The previous quiet action is still unknown. Check its state before taking another action.");
      }
      const count = this.db.prepare("SELECT count(*) AS n FROM quiet WHERE did=?").get(did) as { n: number };
      if (!existing && count.n >= 100) throw new HttpError(409, "Your quiet-action history is full. No new action was sent.");
      this.db.prepare(`INSERT INTO quiet(did,root,status,updatedAt) VALUES(?,?,?,?)
        ON CONFLICT(did,root) DO UPDATE SET status=excluded.status,updatedAt=excluded.updatedAt`)
        .run(did, root, status, new Date().toISOString());
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  public reconcile(did: string, root: string, observed: boolean): void {
    validateDid(did); validateRoot(root);
    if (typeof observed !== "boolean") throw new HttpError(400, "A known quiet observation is required.");
    if (QuietStore.inFlight.has(this.key(did))) throw new HttpError(409, "A quiet action is still in progress for this account.");
    // The condition is evaluated by SQLite at the update, so a concurrent
    // reservation cannot be replaced by an older readback.
    this.db.prepare("UPDATE quiet SET status=?,updatedAt=? WHERE did=? AND root=? AND status!='unknown'")
      .run(observed ? "muted" : "unmuted", new Date().toISOString(), did, root);
  }

  public async apply(
    did: string, root: string, desired: boolean,
    effect: () => Promise<void>, readback: () => Promise<boolean>,
  ): Promise<boolean> {
    validateDid(did); validateRoot(root);
    if (typeof desired !== "boolean") throw new HttpError(400, "A quiet action is required.");
    const key = this.key(did);
    if (QuietStore.inFlight.has(key)) throw new HttpError(409, "A quiet action is still in progress for this account.");
    QuietStore.inFlight.add(key);
    try {
      this.save(did, root, "unknown", true);
      let effectError = false;
      try { await effect(); } catch { effectError = true; }
      let observed: boolean;
      try {
        observed = await readback();
        if (typeof observed !== "boolean") throw new Error("Unknown observation");
      } catch {
        throw new HttpError(503, "The quiet action outcome is unknown. Check again before taking another action.");
      }
      if (effectError) {
        throw new HttpError(503, `The quiet request completion could not be confirmed. Last observed setting: ${observed ? "quieted" : "not quieted"}. The action remains unknown; no retry was sent.`);
      }
      this.save(did, root, observed ? "muted" : "unmuted");
      return observed === desired;
    } finally {
      QuietStore.inFlight.delete(key);
    }
  }
}
