import { isValidPostUri } from "./html.js";

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function postUri(value: unknown): value is string {
  if (typeof value !== "string" || !isValidPostUri(value)) return false;
  const key = value.slice(value.lastIndexOf("/") + 1);
  return key !== "." && key !== "..";
}

/** A declared root for local presentation only; this does not establish ancestry or existence. */
export function localQuietRoot(item: unknown): string | undefined {
  const feed = object(item), post = object(feed?.post), record = object(post?.record);
  if (!post || !record || !postUri(post.uri)) return undefined;
  const raw = record.reply, hydrated = feed?.reply;
  if (raw === undefined) {
    return hydrated === undefined ? post.uri : undefined;
  }
  const reply = object(raw);
  const root = object(reply?.root)?.uri;
  if (!reply || !postUri(root) || root === post.uri) return undefined;
  const parent = object(reply.parent)?.uri;
  if (reply.parent !== undefined && !postUri(parent)) return undefined;
  if (hydrated !== undefined) {
    const view = object(hydrated);
    const viewRoot = object(view?.root)?.uri;
    if (!view || !postUri(viewRoot) || viewRoot !== root) return undefined;
    const viewParent = object(view.parent)?.uri;
    if (view.parent !== undefined && !postUri(viewParent)) return undefined;
    if (parent !== undefined && viewParent !== undefined && parent !== viewParent) return undefined;
  }
  return root;
}

/** Unknown or contradictory lineage cannot silently suppress a received feed item. */
export function isLocallyQuiet(item: unknown, roots: ReadonlySet<string>): boolean {
  const root = localQuietRoot(item);
  return root !== undefined && roots.has(root);
}
