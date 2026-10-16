// Runs only on the page confirming "Delete my Phlogiston data": forget this browser's saved layout.
try {
  for (let index = localStorage.length - 1; index >= 0; index -= 1) {
    const key = localStorage.key(index);
    if (key !== null && key.startsWith("phlogiston.")) localStorage.removeItem(key);
  }
} catch {
  // Storage may be unavailable; nothing was saved then.
}
