export type DisplayPreference = "system" | "light" | "dark";

export const DISPLAY_COOKIE = "phlogiston_display";
const YEAR_SECONDS = 365 * 24 * 60 * 60;

/** A browser-local presentation choice, independent of OAuth and account state. */
export function displayPreference(value: unknown): DisplayPreference {
  return value === "light" || value === "dark" ? value : "system";
}

export function parseDisplayPreference(header: string | undefined): DisplayPreference {
  if (!header) return "system";
  let found: string | undefined;
  for (const part of header.split(";")) {
    const index = part.indexOf("=");
    if (index < 0 || part.slice(0, index).trim() !== DISPLAY_COOKIE) continue;
    // Multiple definitions can carry conflicting path scope. Do not choose one.
    if (found !== undefined) return "system";
    found = part.slice(index + 1).trim();
  }
  return displayPreference(found);
}

export function displayPreferenceCookie(preference: DisplayPreference, publicUrl: string): string {
  if (preference !== "system" && preference !== "light" && preference !== "dark") {
    throw new TypeError("Invalid display preference");
  }
  const url = new URL(publicUrl);
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new TypeError("Invalid public origin");
  return `${DISPLAY_COOKIE}=${preference}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${YEAR_SECONDS}${url.protocol === "https:" ? "; Secure" : ""}`;
}
