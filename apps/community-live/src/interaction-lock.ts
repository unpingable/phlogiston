const interactionLocks = new Map<string,Promise<void>>();

/** Serialize interaction-journal work for one account inside this process. */
export async function withInteractionLock<T>(did: string, action: () => Promise<T>): Promise<T> {
  const previous = interactionLocks.get(did) ?? Promise.resolve();
  let release!: () => void;
  const turn = new Promise<void>(resolve => { release = resolve; });
  const tail = previous.then(() => turn);
  interactionLocks.set(did,tail);
  await previous;
  try { return await action(); }
  finally { release(); if (interactionLocks.get(did) === tail) interactionLocks.delete(did); }
}
