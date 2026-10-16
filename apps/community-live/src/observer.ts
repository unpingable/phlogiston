import { HttpError } from "./http-error.js";

export class ProjectionTooLargeError extends Error {
  public constructor(public readonly exceeded: "bytes" | "items", message: string) {
    super(message);
    this.name = "ProjectionTooLargeError";
  }
}

export interface CommunityProjection {
  get(path: string): Promise<Record<string, unknown>>;
  getCapped(path: string, field: string, maxItems: number): Promise<Record<string, unknown>>;
}

export class ObserverClient implements CommunityProjection {
  public constructor(
    private readonly origin: string,
    private readonly maxResponseBytes: number,
    private readonly fetchFn: typeof fetch = fetch,
  ) {}

  public async get(path: string): Promise<Record<string, unknown>> {
    const response = await this.fetchFn(new URL(path, this.origin));
    if (response.status === 404) {
      throw new HttpError(404, "The community projection does not have that record.");
    }
    if (!response.ok || response.body === null) {
      throw new Error("Community projection is temporarily unavailable.");
    }
    const declared = Number(response.headers.get("content-length") ?? 0);
    if (declared > this.maxResponseBytes) {
      await response.body.cancel().catch(() => undefined);
      throw new ProjectionTooLargeError("bytes", "projection response exceeds the response-byte ceiling");
    }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > this.maxResponseBytes) {
        await reader.cancel().catch(() => undefined);
        throw new ProjectionTooLargeError("bytes", "projection response exceeds the response-byte ceiling");
      }
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
  }

  public async getCapped(path: string, field: string, maxItems: number): Promise<Record<string, unknown>> {
    const document = await this.get(path);
    const items = document[field];
    if (Array.isArray(items) && items.length > maxItems) {
      throw new ProjectionTooLargeError("items", "projection response exceeds the item-count ceiling");
    }
    return document;
  }
}
