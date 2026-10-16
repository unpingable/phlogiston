import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { ActivitySnapshots, FileSeenStore, type SeenStore } from "./activity.js";
import { loadConfig } from "./config.js";
import { ContributionService, deterministicTid, submissionRkey } from "./contributions.js";
import { TrustedModeratorBroker, type AuthorityEnvelope } from "./moderation.js";
import { renderReply } from "./server.js";
import { PostCommitFaultWriter } from "./faults.js";
import {
  DurableWriteJournal,
  canonical,
  type ObservedRecord,
  type PublicRepoWriter,
  type RecordAddress,
} from "./operations.js";

class MemorySeenStore implements SeenStore {
  private readonly versions = new Map<string, number>();

  public async get(memberDid: string, discussionUri: string): Promise<number> {
    return this.versions.get(`${memberDid} ${discussionUri}`) ?? 0;
  }

  public async advance(memberDid: string, discussionUri: string, displayedVersion: number): Promise<void> {
    const item = `${memberDid} ${discussionUri}`;
    const current = this.versions.get(item) ?? 0;
    if (displayedVersion > current) this.versions.set(item, displayedVersion);
  }
}

class FakeWriter implements PublicRepoWriter {
  public readonly records = new Map<string, ObservedRecord>();
  public readonly creates = new Map<string, number>();
  public failAfterCommitCollection?: string | undefined;
  public failBeforeCommitCollection?: string | undefined;

  public async create(address: RecordAddress, record: unknown): Promise<{ cid: string }> {
    const key = addressKey(address);
    this.creates.set(key, (this.creates.get(key) ?? 0) + 1);
    if (this.failBeforeCommitCollection === address.collection) {
      this.failBeforeCommitCollection = undefined;
      throw new Error("request failed before commit");
    }
    const cid = `cid-${canonical(record).length}`;
    this.records.set(key, { cid, record });
    if (this.failAfterCommitCollection === address.collection) {
      this.failAfterCommitCollection = undefined;
      throw new Error("response lost after commit");
    }
    return { cid };
  }

  public async get(address: RecordAddress): Promise<ObservedRecord | null> {
    return this.records.get(addressKey(address)) ?? null;
  }
}

test("lost source response reconciles after process restart without duplicate post", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-live-"));
  const path = join(directory, "operations.json");
  const writer = new FakeWriter();
  writer.failAfterCommitCollection = "app.bsky.feed.post";
  const service = new ContributionService(new DurableWriteJournal(path), writer);
  const plan = await service.prepare({
    operationId: "reply-1",
    authorDid: "did:plc:alice",
    sourceRkey: "3m123",
    text: "A public reply",
    communityDid: "did:web:community.example",
    createdAt: "2026-09-07T12:00:00.000Z",
    reply: {
      root: { uri: "at://did:plc:bob/app.bsky.feed.post/root", cid: "root-cid" },
      parent: { uri: "at://did:plc:bob/app.bsky.feed.post/root", cid: "root-cid" },
      discussion: {
        uri: "at://did:web:community.example/app.phlogiston.community.admission/root",
        cid: "admission-cid",
      },
    },
  });

  assert.equal((await service.advance(plan)).status, "source_outcome_unknown");
  const restarted = new ContributionService(new DurableWriteJournal(path), writer);
  assert.equal((await restarted.advance(plan)).status, "complete");
  assert.equal(writer.creates.get(addressKey(plan.source)), 1);
  assert.equal(writer.creates.get(addressKey(plan.context)), 1);
});

test("confirmed absence retries the same source rkey without terminal help", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-live-"));
  const path = join(directory, "operations.json");
  const writer = new FakeWriter();
  writer.failBeforeCommitCollection = "app.bsky.feed.post";
  const service = new ContributionService(new DurableWriteJournal(path), writer);
  const plan = await service.prepare({
    operationId: "root-absent",
    authorDid: "did:plc:alice",
    sourceRkey: "3m789",
    text: "Recover me",
    communityDid: "did:web:community.example",
    createdAt: "2026-09-07T12:00:00.000Z",
  });

  assert.equal((await service.advance(plan)).status, "source_outcome_unknown");
  const restarted = new ContributionService(new DurableWriteJournal(path), writer);
  assert.equal((await restarted.advance(plan)).status, "complete");
  assert.equal(writer.creates.get(addressKey(plan.source)), 2);
});

test("lost context response remains pending then reconciles without duplicate reply", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-live-"));
  const path = join(directory, "operations.json");
  const writer = new FakeWriter();
  writer.failAfterCommitCollection = "app.phlogiston.community.submit";
  const service = new ContributionService(new DurableWriteJournal(path), writer);
  const plan = await service.prepare({
    operationId: "root-1",
    authorDid: "did:plc:alice",
    sourceRkey: "3m456",
    text: "A root post",
    communityDid: "did:web:community.example",
    createdAt: "2026-09-07T12:00:00.000Z",
  });

  assert.equal((await service.advance(plan)).status, "community_submission_outcome_unknown");
  const restarted = new ContributionService(new DurableWriteJournal(path), writer);
  assert.equal((await restarted.advance(plan)).status, "complete");
  assert.equal(writer.creates.get(addressKey(plan.source)), 1);
  assert.equal(writer.creates.get(addressKey(plan.context)), 1);
});

test("activity arriving after render remains unread after snapshot acknowledgement", async () => {
  const seen = new MemorySeenStore();
  const snapshots = new ActivitySnapshots(Buffer.alloc(32, 7), seen);
  const shown = await snapshots.issue("did:plc:alice", [
    { discussionUri: "at://discussion/1", version: 4, newReplies: 1, moderationChanges: 0 },
  ]);

  await snapshots.acknowledge("did:plc:alice", shown.token);
  const next = await snapshots.issue("did:plc:alice", [
    { discussionUri: "at://discussion/1", version: 5, newReplies: 2, moderationChanges: 0 },
  ]);
  assert.equal(next.discussions[0]?.unread, true);
});

test("private last-seen markers survive a browser backend restart", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-seen-"));
  const path = join(directory, "last-seen.json");
  const first = new ActivitySnapshots(Buffer.alloc(32, 9), new FileSeenStore(path));
  const shown = await first.issue("did:plc:alice", [
    { discussionUri: "at://discussion/2", version: 8, newReplies: 1, moderationChanges: 1 },
  ]);
  await first.acknowledge("did:plc:alice", shown.token);

  const restarted = new ActivitySnapshots(Buffer.alloc(32, 9), new FileSeenStore(path));
  const unchanged = await restarted.issue("did:plc:alice", [
    { discussionUri: "at://discussion/2", version: 8, newReplies: 1, moderationChanges: 1 },
  ]);
  assert.equal(unchanged.discussions[0]?.unread, false);
});

test("moderator broker binds restored human DID to the exact authority request", async () => {
  let received: AuthorityEnvelope | undefined;
  const broker = new TrustedModeratorBroker(
    { restore: async () => ({ did: "did:plc:mod", sessionRef: "oauth-session-4" }) },
    {
      request: async (envelope) => {
        received = envelope;
        return { ok: true, status: "committed" };
      },
    },
    new Set(["did:plc:mod"]),
  );

  const request = {
    cookieHeader: "session=opaque",
    sameOrigin: true,
    csrfValid: true,
    command: {
      kind: "remove-reply" as const,
      admissionUri: "at://did:web:community/app.phlogiston.community.replyAdmission/x",
      admissionCid: "bafy-admission",
      reason: "Off topic",
    },
  };
  await broker.moderate(request);
  assert.equal(received?.authenticatedDid, "did:plc:mod");
  assert.equal(received?.action, "reply_remove");
  const operationId = received?.operationId;
  await broker.moderate(request);
  assert.equal(received?.operationId, operationId);

  await assert.rejects(
    broker.moderate({
      cookieHeader: "session=opaque",
      sameOrigin: false,
      csrfValid: true,
      command: {
        kind: "admit-root",
        submissionUri: "at://did:plc:alice/app.phlogiston.community.submit/x",
        submissionCid: "bafy-submit",
      },
    }),
    /invalid browser request/,
  );
});

test("moderator broker binds a restore to the exact controlling removal", async () => {
  let received: AuthorityEnvelope | undefined;
  const broker = new TrustedModeratorBroker(
    { restore: async () => ({ did: "did:plc:mod", sessionRef: "oauth-session-restore" }) },
    {
      request: async (envelope) => {
        received = envelope;
        return { ok: true, status: "committed" };
      },
    },
    new Set(["did:plc:mod"]),
  );

  await broker.moderate({
    cookieHeader: "session=opaque",
    sameOrigin: true,
    csrfValid: true,
    command: {
      kind: "restore-reply",
      admissionUri: "at://did:web:community/app.phlogiston.community.replyAdmission/x",
      admissionCid: "bafy-admission",
      controllingActionUri: "at://did:web:community/app.phlogiston.community.replyAction/remove-x",
      controllingActionCid: "bafy-removal",
      reason: "Reviewed and restored",
    },
  });

  assert.equal(received?.action, "reply_restore");
  assert.deepEqual(received?.controllingAction, {
    uri: "at://did:web:community/app.phlogiston.community.replyAction/remove-x",
    cid: "bafy-removal",
  });
});

test("only the configured moderator sees an exact restore affordance", () => {
  const reply = {
    status: "removed",
    reason: "Off topic",
    post: {},
    admission: {
      uri: "at://did:web:community/app.phlogiston.community.replyAdmission/x",
      cid: "bafy-admission",
    },
    controllingAction: {
      uri: "at://did:web:community/app.phlogiston.community.replyAction/remove-x",
      cid: "bafy-removal",
    },
  };
  const moderator = renderReply(
    reply,
    { did: "did:plc:mod", csrf: "csrf-token", expiresAt: "2026-09-08T12:00:00Z" },
    { moderatorDid: "did:plc:mod", profiles: new Map(), avatars: false },
  );
  assert.match(moderator, /Restore to community/);
  assert.match(moderator, /bafy-removal/);

  const participant = renderReply(
    reply,
    { did: "did:plc:participant", csrf: "csrf-token", expiresAt: "2026-09-08T12:00:00Z" },
    { moderatorDid: "did:plc:mod", profiles: new Map(), avatars: false },
  );
  assert.doesNotMatch(participant, /Restore to community/);
  assert.doesNotMatch(participant, /bafy-removal/);
});

test("canonical hashing ignores object insertion order", () => {
  assert.equal(canonical({ b: 2, a: 1 }), canonical({ a: 1, b: 2 }));
});

test("integration fault is one-shot and occurs only after commit", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-fault-"));
  const writer = new FakeWriter();
  await writeFile(join(directory, "post.once"), "armed\n");
  const faulted = new PostCommitFaultWriter(writer, directory, () => { throw new Error("terminated"); });
  const address = { repo: "did:plc:alice", collection: "app.bsky.feed.post", rkey: "3m123" };
  await assert.rejects(faulted.create(address, { text: "committed" }), /terminated/);
  assert.equal(writer.records.size, 1);
  await faulted.create(address, { text: "committed" });
  assert.equal(writer.creates.get(addressKey(address)), 2);
});

test("integration faults require explicit paired configuration", () => {
  const base = {
    COMMUNITY_PUBLIC_URL: "https://community.phlogiston.app",
    COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "PCV0",
    COMMUNITY_PURPOSE: "Integration",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
  };
  assert.equal(loadConfig(base).integrationFaultDirectory, undefined);
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_INTEGRATION_FAULTS: "enabled" }),
    /explicit enablement/,
  );
  assert.equal(
    loadConfig({
      ...base,
      COMMUNITY_INTEGRATION_FAULTS: "enabled",
      COMMUNITY_INTEGRATION_FAULT_DIR: "/run/pcv0-faults/community-web",
    }).integrationFaultDirectory,
    "/run/pcv0-faults/community-web",
  );
});

test("observer acquisition ceilings default and override from configuration", () => {
  const base = {
    COMMUNITY_PUBLIC_URL: "https://community.phlogiston.app",
    COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "PCV0",
    COMMUNITY_PURPOSE: "Integration",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
  };
  const defaults = loadConfig(base);
  assert.equal(defaults.observerMaxResponseBytes, 1024 * 1024);
  assert.equal(defaults.discussionsMaxItems, 500);
  const tuned = loadConfig({
    ...base,
    COMMUNITY_OBSERVER_MAX_BYTES: "262144",
    COMMUNITY_DISCUSSIONS_MAX_ITEMS: "50",
  });
  assert.equal(tuned.observerMaxResponseBytes, 262144);
  assert.equal(tuned.discussionsMaxItems, 50);
  assert.throws(() => loadConfig({ ...base, COMMUNITY_OBSERVER_MAX_BYTES: "12" }), /COMMUNITY_OBSERVER_MAX_BYTES is invalid/);
  assert.throws(() => loadConfig({ ...base, COMMUNITY_DISCUSSIONS_MAX_ITEMS: "0" }), /COMMUNITY_DISCUSSIONS_MAX_ITEMS is invalid/);
});

test("profile hydration pins an explicit AppView origin and defaults avatars off", () => {
  const base = {
    COMMUNITY_PUBLIC_URL: "https://community.phlogiston.app",
    COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "PCV0",
    COMMUNITY_PURPOSE: "Integration",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
  };
  const defaults = loadConfig(base);
  assert.equal(defaults.appViewOrigin, "https://public.api.bsky.app");
  assert.equal(defaults.avatarsEnabled, false);
  assert.equal(
    loadConfig({ ...base, COMMUNITY_APPVIEW_ORIGIN: "https://api.example.test" }).appViewOrigin,
    "https://api.example.test",
  );
  assert.throws(() => loadConfig({ ...base, COMMUNITY_APPVIEW_ORIGIN: "http://public.api.bsky.app" }), /HTTPS/);
  assert.throws(() => loadConfig({ ...base, COMMUNITY_APPVIEW_ORIGIN: "https://user:pass@api.example.test" }), /HTTPS/);
  assert.throws(() => loadConfig({ ...base, COMMUNITY_APPVIEW_ORIGIN: "https://api.example.test/xrpc" }), /path/);
  assert.equal(loadConfig({ ...base, COMMUNITY_AVATARS: "enabled" }).avatarsEnabled, true);
  assert.throws(() => loadConfig({ ...base, COMMUNITY_AVATARS: "sometimes" }), /COMMUNITY_AVATARS is invalid/);
});

test("identity directory seams are optional and accepted only for a loopback app", () => {
  const base = {
    COMMUNITY_PUBLIC_URL: "https://community.phlogiston.app",
    COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "PCV0",
    COMMUNITY_PURPOSE: "Integration",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
  };
  const defaults = loadConfig(base);
  assert.equal(defaults.plcDirectoryUrl, undefined);
  assert.equal(defaults.handleResolverUrl, undefined);
  assert.equal(loadConfig({ ...base, COMMUNITY_PLC_DIRECTORY_URL: " " }).plcDirectoryUrl, undefined);
  assert.equal(loadConfig({ ...base, COMMUNITY_HANDLE_RESOLVER_URL: " " }).handleResolverUrl, undefined);
  // A non-loopback app refuses every value, HTTPS or not: the seams are only for isolated runs.
  for (const name of ["COMMUNITY_PLC_DIRECTORY_URL", "COMMUNITY_HANDLE_RESOLVER_URL"]) {
    for (const value of ["https://plc.example.test/", "https://plc.directory", "http://127.0.0.1:2582", "http://plc.example.test"]) {
      assert.throws(
        () => loadConfig({ ...base, [name]: value }),
        /refused unless COMMUNITY_PUBLIC_URL is a loopback origin/,
        `${name}=${value}`,
      );
    }
  }
  const loopbackApp = { ...base, COMMUNITY_PUBLIC_URL: "http://127.0.0.1:3210" };
  assert.throws(() => loadConfig({ ...loopbackApp, COMMUNITY_PLC_DIRECTORY_URL: "http://plc.example.test" }), /HTTPS/);
  assert.throws(() => loadConfig({ ...loopbackApp, COMMUNITY_HANDLE_RESOLVER_URL: "https://plc.example.test/v1" }), /HTTPS/);
  const loopback = loadConfig({
    ...loopbackApp,
    COMMUNITY_PLC_DIRECTORY_URL: "http://127.0.0.1:2582",
    COMMUNITY_HANDLE_RESOLVER_URL: "http://localhost:2582",
  });
  assert.equal(loopback.plcDirectoryUrl, "http://127.0.0.1:2582");
  assert.equal(loopback.handleResolverUrl, "http://localhost:2582");
});

test("the observer public permalink base is optional and strictly validated", () => {
  const base = {
    COMMUNITY_PUBLIC_URL: "https://community.phlogiston.app",
    COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "PCV0",
    COMMUNITY_PURPOSE: "Integration",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
  };
  assert.equal(loadConfig(base).observerPublicUrl, undefined);
  assert.equal(loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "" }).observerPublicUrl, undefined);
  assert.equal(
    loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://observer.example.test/c/internal-dogfood" }).observerPublicUrl,
    "https://observer.example.test/c/internal-dogfood",
  );
  assert.equal(
    loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "http://127.0.0.1:8080/c/internal-dogfood" }).observerPublicUrl,
    "http://127.0.0.1:8080/c/internal-dogfood",
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "http://observer.example.test/c/internal-dogfood" }),
    /HTTPS/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://user:pass@observer.example.test/c/internal-dogfood" }),
    /HTTPS/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://observer.example.test" }),
    /\/c\/\{slug\}/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://observer.example.test/c/internal-dogfood/" }),
    /\/c\/\{slug\}/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://observer.example.test/c/internal-dogfood?x=1" }),
    /\/c\/\{slug\}/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "https://observer.example.test/c/internal-dogfood#frag" }),
    /\/c\/\{slug\}/,
  );
  assert.throws(
    () => loadConfig({ ...base, COMMUNITY_OBSERVER_PUBLIC_URL: "not a url" }),
    /COMMUNITY_OBSERVER_PUBLIC_URL is invalid/,
  );
});

test("an existing post is submitted once, at its exact CID, across a lost response and restart", async () => {
  const directory = await mkdtemp(join(tmpdir(), "community-live-"));
  const path = join(directory, "operations.json");
  const writer = new FakeWriter();
  const postAddress = { repo: "did:plc:alice", collection: "app.bsky.feed.post", rkey: "3kpost" };
  writer.records.set(addressKey(postAddress), { cid: "bafy-post", record: { text: "already posted" } });
  writer.failAfterCommitCollection = "app.phlogiston.community.submit";
  const service = new ContributionService(new DurableWriteJournal(path), writer);
  const subject = await service.readOwnPost("did:plc:alice", "3kpost");
  assert.deepEqual(subject, { uri: "at://did:plc:alice/app.bsky.feed.post/3kpost", cid: "bafy-post" });
  assert.equal(await service.readOwnPost("did:plc:alice", "missing"), null);
  const plan = service.planExisting({
    authorDid: "did:plc:alice",
    subject: subject!,
    communityDid: "did:web:community.example",
    createdAt: "2026-09-24T12:00:00.000Z",
  });
  assert.equal(plan.context.rkey, submissionRkey("did:web:community.example", subject!));

  assert.equal((await service.advance(plan)).status, "community_submission_outcome_unknown");
  const restarted = new ContributionService(new DurableWriteJournal(path), writer);
  assert.equal((await restarted.advance(plan)).status, "complete");
  assert.equal((await restarted.advance(plan)).status, "complete");
  assert.equal(writer.creates.get(addressKey(postAddress)), undefined);
  assert.equal(writer.creates.get(addressKey(plan.context)), 1);
  const written = writer.records.get(addressKey(plan.context))?.record as Record<string, unknown>;
  assert.deepEqual(written.subject, subject);
  assert.equal("discussion" in written, false);

  // The same exact subject always plans the same operation and record key.
  const again = service.planExisting({
    authorDid: "did:plc:alice",
    subject: subject!,
    communityDid: "did:web:community.example",
    createdAt: "2026-09-24T13:00:00.000Z",
  });
  assert.equal(again.operationId, plan.operationId);
  assert.equal(again.context.rkey, plan.context.rkey);
  assert.throws(() => service.planExisting({
    authorDid: "did:plc:alice",
    subject: { uri: "at://did:plc:bob/app.bsky.feed.post/3kpost", cid: "bafy-post" },
    communityDid: "did:web:community.example",
    createdAt: "2026-09-24T12:00:00.000Z",
  }), /author's own post/);
});

test("the existing-post submission key matches community-submit's derivation", () => {
  // Value computed by community_submit.submit.submission_rkey for the same inputs.
  assert.equal(
    submissionRkey("did:plc:community", {
      uri: "at://did:plc:alice/app.bsky.feed.post/3kabc",
      cid: "bafyreigh2akiscaildcqabsyg3dfr6chu3fgpregiymsck7e7aqa4s52zy",
    }),
    "4oefmx46the7n",
  );
});

function addressKey(address: RecordAddress): string {
  return `${address.repo}/${address.collection}/${address.rkey}`;
}

test("deterministic TIDs are valid record keys for every seed", () => {
  for (let index = 0; index < 2000; index += 1) {
    const tid = deterministicTid(`seed-${index}`);
    assert.match(tid, /^[234567abcdefghij][234567a-z]{12}$/, tid);
  }
});
