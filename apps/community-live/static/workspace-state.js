// A bounded presentation state: context never replaces the remembered base view.
export function initialState() { return {primary: '/home', secondary: null, mode: 'pinned', pairs: {}, context: null}; }
export function transition(state, event) {
  const next = {...state, pairs: {...state.pairs}};
  if (event.type === 'primary') {
    next.primary = event.source;
    if (next.mode === 'paired' && Object.hasOwn(next.pairs, event.source)) next.secondary = next.pairs[event.source];
    next.context = null;
  } else if (event.type === 'secondary') {
    next.secondary = event.source; next.context = null;
    if (next.mode === 'paired') {
      next.pairs[next.primary] = event.source;
      const keys = Object.keys(next.pairs); if (keys.length > 24) delete next.pairs[keys[0]];
    }
  } else if (event.type === 'mode') {
    next.mode = event.mode;
  } else if (event.type === 'inspect') next.context = event.source;
  else if (event.type === 'dismiss') next.context = null;
  return next;
}

/** Counts rendered by the server stop being true once a conversation is quieted or restored in the page. */
export function markAttentionStale(surface) {
  let summary = surface.querySelector(':scope > .attention-summary');
  if (!summary) {
    summary = surface.ownerDocument.createElement('div');
    summary.className = 'attention-summary';
    surface.insertBefore(summary, surface.querySelector(':scope > .following-feed'));
  }
  const note = surface.ownerDocument.createElement('p');
  note.textContent = 'You quieted or restored a conversation here, so the earlier counts for this page no longer match. Refresh to recount.';
  summary.dataset.stale = 'true';
  summary.replaceChildren(note);
}
