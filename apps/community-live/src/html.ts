const DID_PATTERN = /^did:[a-z]+:[a-zA-Z0-9._:%-]{1,512}$/;
const POST_URI_PATTERN = /^at:\/\/(did:[a-z]+:[a-zA-Z0-9._:%-]{1,512})\/app\.bsky\.feed\.post\/([a-zA-Z0-9._:-]{1,512})$/;
export const HANDLE_PATTERN = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;
const MAX_HANDLE_LENGTH = 253;
const MAX_POST_REFERENCE_LENGTH = 1024;
const RECORD_KEY_PATTERN = /^[a-zA-Z0-9._:-]{1,512}$/;
const BSKY_POST_URL_PATTERN = /^https:\/\/bsky\.app\/profile\/([^/?#]+)\/post\/([^/?#]+)$/;
const AT_URI_PATTERN = /^at:\/\/([^/?#]+)\/([^/?#]+)\/([^/?#]+)$/;

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function isValidPostUri(value: string): boolean {
  return POST_URI_PATTERN.test(value);
}

export function isValidDid(value: string): boolean {
  return DID_PATTERN.test(value);
}

export function bskyProfileUrl(did: string): string {
  if (!isValidDid(did)) throw new TypeError("a Bluesky profile URL requires a valid DID");
  return `https://bsky.app/profile/${did}`;
}

export function bskyPostUrl(uri: string): string {
  const match = POST_URI_PATTERN.exec(uri);
  if (match === null) throw new TypeError("a Bluesky post URL requires a valid post AT URI");
  return `${bskyProfileUrl(match[1] as string)}/post/${match[2] as string}`;
}

export function externalHttpsUrl(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new TypeError("not an absolute URL");
  }
  if (parsed.protocol !== "https:" || parsed.username !== "" || parsed.password !== "") {
    throw new TypeError("only credential-free https: URLs may be linked");
  }
  return parsed.toString();
}

/** A post named by the participant: its repository (DID or handle) and record key. */
export type PostReference =
  | { kind: "did"; did: string; rkey: string }
  | { kind: "handle"; handle: string; rkey: string };

export class PostReferenceError extends Error {}

/**
 * Accept exactly a `https://bsky.app/profile/<did-or-handle>/post/<rkey>` URL or an
 * `at://<did>/app.bsky.feed.post/<rkey>` URI. Anything else is refused with a
 * message that is safe to show the participant.
 */
export function parsePostReference(value: string): PostReference {
  const text = value.trim();
  if (text.length === 0 || text.length > MAX_POST_REFERENCE_LENGTH || /[\u0000-\u001f\u007f-\u009f\s]/.test(text)) {
    throw new PostReferenceError("That does not look like a Bluesky post link.");
  }
  const url = BSKY_POST_URL_PATTERN.exec(text);
  if (url !== null) return reference(url[1] as string, url[2] as string, true);
  const uri = AT_URI_PATTERN.exec(text);
  if (uri !== null) {
    if (uri[2] !== "app.bsky.feed.post") {
      throw new PostReferenceError("That link points at something other than a Bluesky post.");
    }
    return reference(uri[1] as string, uri[3] as string, false);
  }
  if (/^https:\/\/bsky\.app\/profile\/[^/?#]+\/(?!post\/)/.test(text)) {
    throw new PostReferenceError("That link points at something other than a Bluesky post.");
  }
  throw new PostReferenceError("That does not look like a Bluesky post link.");
}

function reference(authority: string, rkey: string, handleAllowed: boolean): PostReference {
  if (!RECORD_KEY_PATTERN.test(rkey) || rkey === "." || rkey === "..") {
    throw new PostReferenceError("That does not look like a Bluesky post link.");
  }
  if (authority.startsWith("did:")) {
    if (!isValidDid(authority)) throw new PostReferenceError("That does not look like a Bluesky post link.");
    return { kind: "did", did: authority, rkey };
  }
  if (handleAllowed && authority.length <= MAX_HANDLE_LENGTH && HANDLE_PATTERN.test(authority)) {
    return { kind: "handle", handle: authority.toLowerCase(), rkey };
  }
  throw new PostReferenceError("That does not look like a Bluesky post link.");
}
