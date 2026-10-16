import { createHash } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export class SecretStore<T> {
  constructor(readonly directory: string) {}
  private path(key: string): string {
    if (!key) throw new Error("empty store key");
    const digest = createHash("sha256").update(key, "utf8").digest("hex");
    return join(this.directory, `${digest}.json`);
  }
  async get(key: string): Promise<T | undefined> {
    try { return JSON.parse(await readFile(this.path(key), "utf8")) as T; }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined; throw error; }
  }
  async set(key: string, value: T): Promise<void> {
    const path = this.path(key);
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    const temporary = `${path}.${process.pid}.tmp`;
    await writeFile(temporary, JSON.stringify(value), { mode: 0o600, flag: "wx" });
    await rename(temporary, path);
  }
  async del(key: string): Promise<void> {
    await unlink(this.path(key)).catch((error: NodeJS.ErrnoException) => { if (error.code !== "ENOENT") throw error; });
  }
}
