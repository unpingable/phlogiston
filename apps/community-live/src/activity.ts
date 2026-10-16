import { createHmac, timingSafeEqual } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { HttpError } from "./http-error.js";

export interface DiscussionActivity {
  discussionUri: string;
  version: number;
  newReplies: number;
  moderationChanges: number;
}

export interface SeenStore {
  get(memberDid: string, discussionUri: string): Promise<number>;
  advance(memberDid: string, discussionUri: string, displayedVersion: number): Promise<void>;
  eraseMember?(memberDid: string): Promise<number>;
}

interface SnapshotPayload {
  memberDid: string;
  versions: Record<string, number>;
}

export interface ActivitySnapshot {
  token: string;
  discussions: Array<DiscussionActivity & { unread: boolean }>;
}

export class ActivitySnapshots {
  public constructor(
    private readonly secret: Buffer,
    private readonly seen: SeenStore,
  ) {
    if (secret.byteLength < 32) throw new Error("snapshot secret must be at least 32 bytes");
  }

  /** Forget one member's read positions (account erasure). */
  public async eraseMember(memberDid: string): Promise<number> {
    return (await this.seen.eraseMember?.(memberDid)) ?? 0;
  }

  public async issue(
    memberDid: string,
    displayed: readonly DiscussionActivity[],
  ): Promise<ActivitySnapshot> {
    const versions: Record<string, number> = {};
    const discussions = await Promise.all(
      displayed.map(async (activity) => {
        versions[activity.discussionUri] = activity.version;
        const lastSeen = await this.seen.get(memberDid, activity.discussionUri);
        return { ...activity, unread: activity.version > lastSeen };
      }),
    );
    return { token: this.sign({ memberDid, versions }), discussions };
  }

  public async acknowledge(memberDid: string, token: string): Promise<void> {
    const payload = this.verify(token);
    if (payload.memberDid !== memberDid) throw new HttpError(403, "That snapshot belongs to another member.");
    await Promise.all(
      Object.entries(payload.versions).map(([uri, version]) =>
        this.seen.advance(memberDid, uri, version),
      ),
    );
  }

  private sign(payload: SnapshotPayload): string {
    const encoded = Buffer.from(JSON.stringify(payload)).toString("base64url");
    const signature = createHmac("sha256", this.secret).update(encoded).digest("base64url");
    return `${encoded}.${signature}`;
  }

  private verify(token: string): SnapshotPayload {
    const [encoded, presented] = token.split(".");
    if (encoded === undefined || presented === undefined) throw new HttpError(400, "That snapshot token is invalid.");
    const expected = createHmac("sha256", this.secret).update(encoded).digest();
    const actual = Buffer.from(presented, "base64url");
    if (actual.byteLength !== expected.byteLength || !timingSafeEqual(actual, expected)) {
      throw new HttpError(400, "That snapshot token is invalid.");
    }
    const payload = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as SnapshotPayload;
    if (typeof payload.memberDid !== "string" || typeof payload.versions !== "object") {
      throw new HttpError(400, "That snapshot token is invalid.");
    }
    return payload;
  }
}

export class FileSeenStore implements SeenStore {
  private loaded = false;
  private values: Record<string, number> = {};
  public constructor(private readonly path: string) {}

  public async get(memberDid: string, discussionUri: string): Promise<number> {
    await this.load();
    return this.values[key(memberDid, discussionUri)] ?? 0;
  }

  public async advance(memberDid: string, discussionUri: string, displayedVersion: number): Promise<void> {
    await this.load();
    const item = key(memberDid, discussionUri);
    if (displayedVersion <= (this.values[item] ?? 0)) return;
    this.values[item] = displayedVersion;
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(this.values)}\n`, { mode: 0o600 });
    await rename(temporary, this.path);
  }

  /** Forget everything seen by one member (account erasure); returns the entries removed. */
  public async eraseMember(memberDid: string): Promise<number> {
    await this.load();
    const prefix = `${memberDid}\u0000`;
    const doomed = Object.keys(this.values).filter((item) => item.startsWith(prefix));
    if (doomed.length === 0) return 0;
    for (const item of doomed) delete this.values[item];
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(this.values)}\n`, { mode: 0o600 });
    await rename(temporary, this.path);
    return doomed.length;
  }

  private async load(): Promise<void> {
    if (this.loaded) return;
    try {
      this.values = JSON.parse(await readFile(this.path, "utf8")) as Record<string, number>;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    this.loaded = true;
  }
}

function key(memberDid: string, discussionUri: string): string {
  return `${memberDid}\u0000${discussionUri}`;
}
