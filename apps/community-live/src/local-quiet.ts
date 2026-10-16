import { closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { HttpError } from "./http-error.js";

const MAX_ROOTS_PER_DID = 100;
const DID = /^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$/;
const RECORD = /^at:\/\/(did:[a-z0-9]+:[A-Za-z0-9._:%-]+)\/(app\.bsky\.feed\.(?:post|generator))\/([A-Za-z0-9._~:-]+)$/;

function validateDid(did: string): void {
  if (typeof did !== "string" || did.length > 2048 || !DID.test(did)) {
    throw new HttpError(400, "A valid account DID is required.");
  }
}

function validateRecord(uri: string, collection: "post" | "generator"): void {
  const match = typeof uri === "string" && uri.length <= 4096 ? RECORD.exec(uri) : null;
  if (!match || match[2] !== `app.bsky.feed.${collection}` || match[3] === "." || match[3] === "..") {
    throw new HttpError(400, collection === "post" ? "A post URI with a DID authority is required." : "A feed URI with a DID authority is required.");
  }
  validateDid(match[1]!);
}

function validateFeed(feedKey: string): void {
  if (feedKey === "following" || /^personal:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(feedKey)) return;
  if (typeof feedKey !== "string" || feedKey.length > 1024 ||
      !/^at:\/\/did:(?:plc|web):[A-Za-z0-9._:%-]+\/app\.bsky\.feed\.generator\/[A-Za-z0-9._~-]{1,512}$/.test(feedKey)) {
    throw new HttpError(400, "A feed URI with a DID authority is required.");
  }
  validateRecord(feedKey, "generator");
}

/** Browser-app local hide state; it never mutes a provider thread or changes community authority. */
export class LocalQuietStore {
  private readonly db: DatabaseSync;

  /** Delete everything this store holds for one account (account erasure); returns the rows removed. */
  public eraseAccount(did: string): number {
    return Number(this.db.prepare("DELETE FROM local_quiet WHERE did=?").run(did).changes);
  }
  public constructor(path: string) {
    const filePath = resolve(path);
    const directory = dirname(filePath);
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const dir = lstatSync(directory);
    if (!dir.isDirectory() || (dir.mode & 0o077) !== 0 || dir.uid !== process.getuid?.()) {
      throw new Error("Local hide store directory must be private and owned by the runtime user");
    }
    const fd = openSync(filePath, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
    try {
      const file = fstatSync(fd);
      if (!file.isFile() || (file.mode & 0o077) !== 0 || file.uid !== process.getuid?.()) {
        throw new Error("Local hide store file must be private and owned by the runtime user");
      }
    } finally {
      closeSync(fd);
    }
    const db = new DatabaseSync(filePath);
    try {
      if (db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='local_quiet' LIMIT 1").get()) {
        throw new Error("Local hide state requires its own database file; existing stores are not migrated");
      }
      db.exec(`PRAGMA busy_timeout = 5000;
        CREATE TABLE IF NOT EXISTS local_quiet (
          did TEXT NOT NULL, feed_key TEXT NOT NULL, root TEXT NOT NULL,
          PRIMARY KEY(did,feed_key,root));`);
      this.db = db;
    } catch (error) {
      db.close();
      throw error;
    }
  }

  public close(): void { this.db.close(); }

  /** A root hidden in two feeds occupies two of the account's 100 bounded slots. */
  public set(did: string, feedKey: string, root: string): void {
    validateDid(did); validateFeed(feedKey); validateRecord(root, "post");
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const existing = this.db.prepare("SELECT 1 FROM local_quiet WHERE did=? AND feed_key=? AND root=?").get(did, feedKey, root);
      if (!existing) {
        const count = this.db.prepare("SELECT count(*) AS n FROM local_quiet WHERE did=?").get(did) as { n: number };
        if (count.n >= MAX_ROOTS_PER_DID) throw new HttpError(409, "Your local hide list is full. Restore a conversation before hiding another.");
        this.db.prepare("INSERT INTO local_quiet(did,feed_key,root) VALUES(?,?,?)").run(did, feedKey, root);
      }
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  public remove(did: string, feedKey: string, root: string): void {
    validateDid(did); validateFeed(feedKey); validateRecord(root, "post");
    this.db.prepare("DELETE FROM local_quiet WHERE did=? AND feed_key=? AND root=?").run(did, feedKey, root);
  }

  public clearFeed(did: string, feedKey: string): void {
    validateDid(did); validateFeed(feedKey);
    this.db.prepare("DELETE FROM local_quiet WHERE did=? AND feed_key=?").run(did,feedKey);
  }

  public list(did: string, feedKey: string): string[] {
    validateDid(did); validateFeed(feedKey);
    return (this.db.prepare("SELECT root FROM local_quiet WHERE did=? AND feed_key=? ORDER BY root LIMIT 100")
      .all(did, feedKey) as { root: string }[]).map(row => row.root);
  }
}
