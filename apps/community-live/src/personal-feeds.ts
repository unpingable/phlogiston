import { randomUUID } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { HttpError } from "./http-error.js";

export interface PersonalFeedInput {
  name: string;
  sources: [{ kind: "following" }];
  policies: { publicBlocks: { curatorDid: string; curatorHandle: string } };
  transformations: { includeReplies: boolean; includeReposts: boolean };
  ordering: "upstream";
  publishing: null;
}
export interface PersonalFeedDefinition extends PersonalFeedInput { id: string; version: 1 }

function refuse(): never { throw new HttpError(400, "A supported personal feed definition is required."); }
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) refuse();
  const actual = Object.keys(value);
  if (actual.length !== keys.length || actual.some(key => !keys.includes(key))) refuse();
  return value as Record<string, unknown>;
}
function did(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length > 2048 || !/^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$/.test(value)) refuse();
}
function id(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)) refuse();
}
/** Syntax only: a stored handle is presentation metadata, never identity resolution. */
function input(value: unknown): PersonalFeedInput {
  const v = object(value, ["name", "sources", "policies", "transformations", "ordering", "publishing"]);
  if (typeof v.name !== "string" || !v.name.trim() || [...v.name].length > 80 || /[\u0000-\u001f\u007f]/.test(v.name)) refuse();
  if (!Array.isArray(v.sources) || v.sources.length !== 1) refuse();
  const source = object(v.sources[0], ["kind"]);
  if (source.kind !== "following") refuse();
  const policies = object(v.policies, ["publicBlocks"]);
  const blocks = object(policies.publicBlocks, ["curatorDid", "curatorHandle"]); did(blocks.curatorDid);
  if (typeof blocks.curatorHandle !== "string" || blocks.curatorHandle.length > 253 ||
      !/^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/.test(blocks.curatorHandle)) refuse();
  const transformations = object(v.transformations, ["includeReplies", "includeReposts"]);
  if (typeof transformations.includeReplies !== "boolean" || typeof transformations.includeReposts !== "boolean" || v.ordering !== "upstream" || v.publishing !== null) refuse();
  return { name: v.name.trim(), sources: [{kind:"following"}], policies:{publicBlocks:{curatorDid:blocks.curatorDid,curatorHandle:blocks.curatorHandle}}, transformations:{includeReplies:transformations.includeReplies,includeReposts:transformations.includeReposts},ordering:"upstream",publishing:null };
}

/** Account-local declarative definitions; no publication, policy or protocol effects. */
export class PersonalFeedStore {
  private readonly db: DatabaseSync;
  /** Delete everything this store holds for one account (account erasure); returns the rows removed. */
  public eraseAccount(did: string): number {
    return Number(this.db.prepare("DELETE FROM personal_feeds WHERE owner_did=?").run(did).changes);
  }
  public constructor(path: string) {
    const filePath=resolve(path), directory=dirname(filePath);
    mkdirSync(directory,{recursive:true,mode:0o700});
    const dir=lstatSync(directory);
    if (!dir.isDirectory() || (dir.mode & 0o077) || dir.uid!==process.getuid?.()) throw new Error("Personal feed directory must be private and runtime-owned");
    const fd=openSync(filePath,constants.O_CREAT|constants.O_RDWR|constants.O_NOFOLLOW,0o600);
    try { const file=fstatSync(fd); if (!file.isFile() || (file.mode & 0o077) || file.uid!==process.getuid?.()) throw new Error("Personal feed file must be private and runtime-owned"); }
    finally { closeSync(fd); }
    const db=new DatabaseSync(filePath);
    try {
      db.exec("PRAGMA busy_timeout=5000");
      if (db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='personal_feeds' LIMIT 1").get()) throw new Error("Personal feeds require a separate database; no store migration");
      db.exec(`PRAGMA busy_timeout=5000; CREATE TABLE IF NOT EXISTS personal_feeds(owner_did TEXT NOT NULL,id TEXT NOT NULL,definition TEXT NOT NULL,PRIMARY KEY(owner_did,id));`);
      this.db=db;
    } catch(error) { db.close(); throw error; }
  }
  public close(): void { this.db.close(); }
  private decode(row: {id:string;definition:string}): PersonalFeedDefinition {
    const value=JSON.parse(row.definition) as unknown;
    const v=object(value,["id","version","name","sources","policies","transformations","ordering","publishing"]);
    id(v.id); if(v.id!==row.id || v.version!==1) refuse();
    const {id: recordId,version,...definition}=v;
    return {...input(definition),id:recordId as string,version:1};
  }
  public list(ownerDid:string): PersonalFeedDefinition[] {
    did(ownerDid);
    return (this.db.prepare("SELECT id,definition FROM personal_feeds WHERE owner_did=? ORDER BY id LIMIT 20").all(ownerDid) as {id:string;definition:string}[]).map(row=>this.decode(row));
  }
  public get(ownerDid:string,feedId:string): PersonalFeedDefinition|undefined {
    did(ownerDid);id(feedId);
    const row=this.db.prepare("SELECT id,definition FROM personal_feeds WHERE owner_did=? AND id=?").get(ownerDid,feedId) as {id:string;definition:string}|undefined;
    return row?this.decode(row):undefined;
  }
  public create(ownerDid:string,value:unknown): PersonalFeedDefinition {
    did(ownerDid);const definition:PersonalFeedDefinition={...input(value),id:randomUUID(),version:1};
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const count=this.db.prepare("SELECT count(*) AS n FROM personal_feeds WHERE owner_did=?").get(ownerDid) as {n:number};
      if(count.n>=20) throw new HttpError(409,"Your personal feed list is full. Remove a feed before creating another.");
      this.db.prepare("INSERT INTO personal_feeds(owner_did,id,definition) VALUES(?,?,?)").run(ownerDid,definition.id,JSON.stringify(definition));
      this.db.exec("COMMIT");return definition;
    } catch(error) { this.db.exec("ROLLBACK");throw error; }
  }
  public update(ownerDid:string,feedId:string,value:unknown): PersonalFeedDefinition|undefined {
    did(ownerDid);id(feedId);const definition:PersonalFeedDefinition={...input(value),id:feedId,version:1};
    const changed=this.db.prepare("UPDATE personal_feeds SET definition=? WHERE owner_did=? AND id=?").run(JSON.stringify(definition),ownerDid,feedId);
    return changed.changes?definition:undefined;
  }
  public remove(ownerDid:string,feedId:string):boolean {
    did(ownerDid);id(feedId);return Boolean(this.db.prepare("DELETE FROM personal_feeds WHERE owner_did=? AND id=?").run(ownerDid,feedId).changes);
  }
}
