import { randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { CreatedSubmission, ExactRecord } from "./records.js";
import { sha256 } from "./storage.js";

export type AuthorItem = Readonly<{
  itemId: string;
  authorDid: string;
  post: ExactRecord;
  currentSource: ExactRecord | null;
  submission: ExactRecord;
  title: string;
  body: string;
  authorDisplayReference: string;
  createdAt: string;
  sourceUpdatedAt: string | null;
  sourceDeletedAt: string | null;
  withdrawal: ExactRecord | null;
}>;

type ActionDocument = Readonly<{
  version: "juniper-author-actions/1";
  items: readonly AuthorItem[];
}>;

export class AuthorActionStore {
  #pending: Promise<void> = Promise.resolve();

  constructor(readonly path: string) {}

  async list(authorDid: string): Promise<readonly AuthorItem[]> {
    await this.#pending;
    return (await this.#read()).items.filter((item) => item.authorDid === authorDid);
  }

  async recordCreation(input: Readonly<{
    authorDid: string;
    result: CreatedSubmission;
    title: string;
    body: string;
    authorDisplayReference: string;
    createdAt: string;
  }>): Promise<AuthorItem> {
    const item: AuthorItem = {
      itemId: sha256(`${input.authorDid}\u0000${input.result.submission.uri}\u0000${input.result.submission.cid}`),
      authorDid: input.authorDid,
      post: input.result.post,
      currentSource: input.result.post,
      submission: input.result.submission,
      title: input.title,
      body: input.body,
      authorDisplayReference: input.authorDisplayReference,
      createdAt: input.createdAt,
      sourceUpdatedAt: null,
      sourceDeletedAt: null,
      withdrawal: null,
    };
    await this.#mutate((document) => {
      if (document.items.some((existing) => existing.itemId === item.itemId)) {
        throw new Error("author action occurrence already exists");
      }
      return { ...document, items: [...document.items, item] };
    });
    return item;
  }

  async recordEdit(input: Readonly<{
    authorDid: string;
    itemId: string;
    source: ExactRecord;
    title: string;
    body: string;
    updatedAt: string;
  }>): Promise<void> {
    await this.#update(input.authorDid, input.itemId, (item) => ({
      ...item,
      currentSource: input.source,
      title: input.title,
      body: input.body,
      sourceUpdatedAt: input.updatedAt,
      sourceDeletedAt: null,
    }));
  }

  async recordDeletion(authorDid: string, itemId: string, deletedAt: string): Promise<void> {
    await this.#update(authorDid, itemId, (item) => ({
      ...item,
      currentSource: null,
      sourceDeletedAt: deletedAt,
    }));
  }

  async recordWithdrawal(
    authorDid: string,
    itemId: string,
    withdrawal: ExactRecord,
  ): Promise<void> {
    await this.#update(authorDid, itemId, (item) => ({ ...item, withdrawal }));
  }

  async #update(
    authorDid: string,
    itemId: string,
    update: (item: AuthorItem) => AuthorItem,
  ): Promise<void> {
    await this.#mutate((document) => {
      let matched = false;
      const items = document.items.map((item) => {
        if (item.itemId !== itemId || item.authorDid !== authorDid) return item;
        matched = true;
        return update(item);
      });
      if (!matched) throw new Error("author action occurrence not found");
      return { ...document, items };
    });
  }

  async #mutate(change: (document: ActionDocument) => ActionDocument): Promise<void> {
    const operation = this.#pending.then(async () => {
      const next = change(await this.#read());
      await this.#write(next);
    });
    this.#pending = operation.catch(() => undefined);
    return operation;
  }

  async #read(): Promise<ActionDocument> {
    try {
      const parsed = JSON.parse(await readFile(this.path, "utf8")) as ActionDocument;
      if (parsed.version !== "juniper-author-actions/1" || !Array.isArray(parsed.items)) {
        throw new Error("unsupported author action store");
      }
      return parsed;
    } catch (error) {
      if (isMissing(error)) return { version: "juniper-author-actions/1", items: [] };
      throw new Error("author action store could not be read", { cause: error });
    }
  }

  async #write(document: ActionDocument): Promise<void> {
    const directory = dirname(this.path);
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await chmod(directory, 0o700);
    const temporary = `${this.path}.write-${randomUUID()}`;
    try {
      await writeFile(temporary, JSON.stringify(document), { mode: 0o600, flag: "wx" });
      await rename(temporary, this.path);
      await chmod(this.path, 0o600);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw new Error("author action store could not be persisted", { cause: error });
    }
  }
}

function isMissing(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
