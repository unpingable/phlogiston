import assert from "node:assert/strict";
import test from "node:test";
import { displayPreference, displayPreferenceCookie, parseDisplayPreference } from "./display.js";

test("display cookie accepts only one exact app preference and defaults invalid state to system", () => {
  assert.equal(parseDisplayPreference(undefined), "system");
  assert.equal(parseDisplayPreference("community_session=x; phlogiston_display=dark"), "dark");
  assert.equal(parseDisplayPreference("phlogiston_display=light; other=dark"), "light");
  for (const header of [
    "phlogiston_display=sepia", "phlogiston_display=%64ark", "phlogiston_display=dark=extra",
    "phlogiston_display=dark; phlogiston_display=light", "not_phlogiston_display=dark",
  ]) assert.equal(parseDisplayPreference(header), "system");
  assert.equal(displayPreference("dark"), "dark");
  assert.equal(displayPreference("sepia"), "system");
});

test("display cookie has browser-local lifetime and HTTPS-only Secure attribute", () => {
  assert.equal(displayPreferenceCookie("system", "https://phlogiston.app"),
    "phlogiston_display=system; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000; Secure");
  assert.equal(displayPreferenceCookie("light", "http://127.0.0.1:3210"),
    "phlogiston_display=light; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000");
  assert.throws(() => displayPreferenceCookie("dark; Path=/other" as never, "https://phlogiston.app"));
});
