import { createHash, randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

export class SecretStore<T> {
  constructor(readonly directory: string) {}

  async get(key: string): Promise<T | undefined> {
    try {
      return JSON.parse(await readFile(this.#path(key), "utf8")) as T;
    } catch (error) {
      if (isMissing(error)) return undefined;
      throw new Error("observer OAuth state unavailable", { cause: error });
    }
  }

  async set(key: string, value: T): Promise<void> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    await chmod(this.directory, 0o700);
    const temporary = join(this.directory, `.write-${randomUUID()}`);
    try {
      await writeFile(temporary, JSON.stringify(value), { mode: 0o600, flag: "wx" });
      await rename(temporary, this.#path(key));
      await chmod(this.#path(key), 0o600);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw new Error("observer OAuth state unavailable", { cause: error });
    }
  }

  async del(key: string): Promise<void> {
    await rm(this.#path(key), { force: true });
  }

  #path(key: string): string {
    return join(this.directory, createHash("sha256").update(key).digest("hex"));
  }
}

function isMissing(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
