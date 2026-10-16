import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

/** A minimal secret-bearing JSON store for the OAuth library's opaque values. */
export class SecretJsonFileStore<T> {
  constructor(readonly directory: string) {}

  async get(key: string): Promise<T | undefined> {
    try {
      const bytes = await readFile(this.#path(key));
      return JSON.parse(bytes.toString("utf8")) as T;
    } catch (error) {
      if (isMissing(error)) return undefined;
      throw new Error("secret session state could not be read", { cause: error });
    }
  }

  async set(key: string, value: T): Promise<void> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    await chmod(this.directory, 0o700);
    const target = this.#path(key);
    const temporary = join(this.directory, `.write-${randomUUID()}`);
    try {
      await writeFile(temporary, JSON.stringify(value), {
        encoding: "utf8",
        mode: 0o600,
        flag: "wx",
      });
      await rename(temporary, target);
      await chmod(target, 0o600);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw new Error("secret session state could not be persisted", {
        cause: error,
      });
    }
  }

  async del(key: string): Promise<void> {
    await rm(this.#path(key), { force: true });
  }

  #path(key: string): string {
    return join(this.directory, sha256(key));
  }
}

type WebSession = Readonly<{ did: string; expiresAt: string }>;

export class WebSessionStore {
  readonly #store: SecretJsonFileStore<WebSession>;

  constructor(directory: string) {
    this.#store = new SecretJsonFileStore(directory);
  }

  async issue(did: string, now = new Date()): Promise<string> {
    const token = randomBytes(32).toString("base64url");
    const expiresAt = new Date(now.valueOf() + 8 * 60 * 60 * 1000).toISOString();
    await this.#store.set(sha256(token), { did, expiresAt });
    return token;
  }

  async resolve(token: string | undefined, now = new Date()): Promise<string | null> {
    if (!token || token.length > 256) return null;
    const key = sha256(token);
    const value = await this.#store.get(key);
    if (!value) return null;
    if (new Date(value.expiresAt).valueOf() <= now.valueOf()) {
      await this.#store.del(key);
      return null;
    }
    return value.did;
  }

  async revoke(token: string | undefined): Promise<void> {
    if (token && token.length <= 256) await this.#store.del(sha256(token));
  }
}

export function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}
