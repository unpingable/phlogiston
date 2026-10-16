import { rename } from "node:fs/promises";
import { join } from "node:path";

import type { PublicRepoWriter, RecordAddress } from "./operations.js";

const ALLOWED_COLLECTIONS = new Map([
  ["app.bsky.feed.post", "post"],
  ["app.phlogiston.community.submit", "submit"],
]);

/** Integration-only one-shot crash point after a real create has returned. */
export class PostCommitFaultWriter implements PublicRepoWriter {
  public constructor(
    private readonly delegate: PublicRepoWriter,
    private readonly directory: string,
    private readonly terminate: () => never = () => {
      process.kill(process.pid, "SIGKILL");
      throw new Error("process termination failed");
    },
  ) {}

  public async create(address: RecordAddress, record: unknown): Promise<{ cid: string }> {
    const result = await this.delegate.create(address, record);
    const trigger = ALLOWED_COLLECTIONS.get(address.collection);
    if (trigger !== undefined && await consume(this.directory, trigger)) this.terminate();
    return result;
  }

  public get(address: RecordAddress) {
    return this.delegate.get(address);
  }
}

async function consume(directory: string, name: string): Promise<boolean> {
  try {
    await rename(join(directory, `${name}.once`), join(directory, `${name}.consumed`));
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}
