// Public About, Privacy and Terms pages: readable signed out, and a statement of what the deployed code does.
// Retention figures come from retention.ts; change the code and these pages together.

import { escapeHtml } from "./html.js";

export const PUBLIC_PAGE_PATHS = new Set(["/about", "/privacy", "/terms"]);
export const SOURCE_URL = "https://github.com/unpingable/phlogiston";
export const OPERATOR_URL = "https://github.com/unpingable";
export const ISSUES_URL = `${SOURCE_URL}/issues`;
export const SECURITY_URL = `${SOURCE_URL}/security/advisories/new`;
/** Changing the Privacy or Terms text means changing this date. */
export const POLICY_EFFECTIVE = "2026-10-16";

/** The git revision of the running release, read from the release directory production deploys into. */
export function sourceRevision(moduleUrl: string = import.meta.url): string | undefined {
  return /\/web-releases\/([0-9a-f]{40})\//.exec(decodeURIComponent(moduleUrl))?.[1];
}

export function publicFooter(): string {
  return `<footer class="site-footer"><nav aria-label="About Phlogiston"><a href="/about">About and security</a><a href="/privacy">Privacy</a><a href="/terms">Terms and rules</a><a href="${SOURCE_URL}">Source</a></nav></footer>`;
}

function sourceLine(revision: string | undefined): string {
  return revision
    ? `The running release is commit <a href="${SOURCE_URL}/tree/${revision}"><code>${revision.slice(0, 12)}</code></a>.`
    : "The running release's exact commit is not shown on this instance.";
}

export function publicPage(path: string, revision = sourceRevision()): { title: string; body: string } {
  if (path === "/about") return { title: "About Phlogiston", body: about(revision) };
  if (path === "/privacy") return { title: "Privacy", body: privacy() };
  return { title: "Terms and community rules", body: terms() };
}

function about(revision: string | undefined): string {
  return `<div class="prose">
<p><strong>Phlogiston is an experimental reader for Bluesky.</strong> It is not a replacement for the Bluesky app. Expect missing features, rough edges and outages.</p>
<p>It is run by one person, <a href="${OPERATOR_URL}">unpingable</a>, as a hobby project. There is no company, no advertising and no paid tier. The source code is public at <a href="${SOURCE_URL}">${escapeHtml(SOURCE_URL.replace("https://", ""))}</a>. ${sourceLine(revision)} The only address for this app is <code>https://phlogiston.app</code>; if someone sends you a different link, don’t sign in there.</p>
<p>Nobody has independently audited this code. Automated tests and AI-assisted review are not an audit.</p>

<h2>What works</h2>
<ul>
<li><strong>Signed out:</strong> read the Cabinet, a community collection of public posts chosen by its moderator, and its public conversations.</li>
<li><strong>Signed in:</strong> your Following timeline, conversations, saved custom feeds, side-by-side and pinned reading panes, private personal feeds, and hiding conversations from your view here.</li>
<li><strong>Optional:</strong> muting or unmuting a conversation’s notifications in Bluesky, and submitting one of your own posts to the Cabinet for the moderator to admit or decline.</li>
<li><strong>Context:</strong> labels on accounts, from <a href="https://labelwatch.neutral.zone">Labelwatch</a> (run by the same operator). When it can’t be reached, coverage is shown as unknown, not as clean.</li>
</ul>
<h2>What doesn’t</h2>
<ul>
<li>No posting, replying, liking, reposting, following or notifications. Use Bluesky for those.</li>
<li>Only accounts hosted by Bluesky can sign in. Accounts on self-hosted or other providers are refused, not downgraded.</li>
<li>There is no Phlogiston account signup. Signing in uses your existing Bluesky account, and nothing is created for you elsewhere. <code>phlogiston.social</code> is the operator’s test server and does not offer accounts.</li>
<li>You can’t create your own community. The Cabinet is the only one, and the operator moderates it.</li>
</ul>

<h2>What signing in allows</h2>
<p>Signing in uses Bluesky’s own authorization screen (OAuth). Phlogiston never sees your password and never asks for an app password. Don’t send your password to anyone, including in a DM that claims to be from this app.</p>
<p>The first sign-in asks Bluesky to let Phlogiston:</p>
<ul>
<li>read your Following timeline, conversations, your viewing preferences and the label services you subscribe to;</li>
<li>create a <em>community submission record</em> in your account, and only when you press submit.</li>
</ul>
<p>Later features ask again, each on a separate authorization screen you can decline:</p>
<ul>
<li><strong>Saved feeds:</strong> read the custom feeds you have saved.</li>
<li><strong>Personal feeds:</strong> read the profile and public block list of the account a personal feed is built from.</li>
<li><strong>Conversation controls:</strong> mute and unmute a conversation’s notifications in Bluesky. This changes your Bluesky account.</li>
</ul>
<p>Phlogiston cannot post, reply, like, follow, delete or edit anything in your account, change your profile, read your DMs or see your email.</p>

<h2>Leaving</h2>
<ul>
<li><strong>Sign out</strong> (Settings) ends Phlogiston’s sessions in every browser and asks Bluesky to revoke its access.</li>
<li><strong>Delete my Phlogiston data</strong> (Settings) also erases everything Phlogiston keeps for your account. See <a href="/privacy">Privacy</a>.</li>
<li>You can also revoke access from Bluesky’s side at any time, in Bluesky’s settings under app authorizations.</li>
</ul>

<h2>Reporting a problem</h2>
<p>Report bugs, confusing behaviour and feature requests as <a href="${ISSUES_URL}">issues on the source repository</a>; issues are public. Report security problems privately through <a href="${SECURITY_URL}">GitHub’s private vulnerability reporting</a>. Data requests and moderation appeals: see <a href="/privacy">Privacy</a> and <a href="/terms">Terms</a>. There is no support SLA; replies come when the operator can.</p>
</div>`;
}

function privacy(): string {
  return `<div class="prose">
<p>Effective ${POLICY_EFFECTIVE}. This page describes what the running code does. It is written by the operator and has not been reviewed by a lawyer.</p>

<h2>Who</h2>
<p>Phlogiston is run by one individual in the United States (<a href="${OPERATOR_URL}">unpingable</a>) who decides what it stores, why and for how long. Your Bluesky account, posts and identity stay with Bluesky; Phlogiston does not host them.</p>

<h2>What Phlogiston keeps, and for how long</h2>
<table>
<thead><tr><th>What</th><th>Why</th><th>How long</th></tr></thead>
<tbody>
<tr><td>Your sign-in session (your account identifier, a form-protection token and the permissions you granted)</td><td>Keep you signed in</td><td>8 hours, then swept within the hour</td></tr>
<tr><td>Bluesky sign-in tokens</td><td>Read your timeline and act when you ask</td><td>Until you sign out, or 8 hours after your last session ends. Then Phlogiston asks Bluesky to revoke them and deletes them</td></tr>
<tr><td>Unfinished sign-ins</td><td>Complete the sign-in</td><td>1 hour</td></tr>
<tr><td>Personal feeds, conversations you hid here, your conversation-control history, which community conversations you have read</td><td>Features you use</td><td>Until you delete them or use Delete my Phlogiston data</td></tr>
<tr><td>Submission drafts and write journals (the record being written for you, so an interrupted write can resume safely)</td><td>Submitting to the Cabinet</td><td>30 days, or until you use Delete my Phlogiston data</td></tr>
<tr><td>Cabinet submissions and the moderator’s decisions, including any private reason for a decline or removal</td><td>Running the community and accounting for moderation</td><td>As long as the Cabinet runs. Ask to have a private reason deleted</td></tr>
<tr><td>A mirror of public Bluesky records relevant to the Cabinet</td><td>Showing the collection and conversations</td><td>As long as the Cabinet runs; it is public data and can be rebuilt</td></tr>
<tr><td>Your display theme</td><td>Light or dark mode</td><td>A cookie in your browser, 1 year</td></tr>
<tr><td>Your pane layout</td><td>Side-by-side reading</td><td>Your browser’s local storage only, until you clear it or use Delete my Phlogiston data</td></tr>
</tbody></table>
<p>Phlogiston does not log your requests or keep an access log, and it has no analytics, trackers, ads or third-party scripts. System logs on the server last a few days and contain errors, not browsing. Phlogiston makes <strong>no backups</strong> of the data above, so deleted data is not restored later.</p>
<p>Cookies: <code>community_session</code> (sign-in, 8 hours), <code>community_login</code> (during sign-in, 10 minutes) and <code>phlogiston_display</code> (theme, 1 year). All three are strictly necessary for what you asked for, so there is no cookie banner.</p>

<h2>Who else sees what</h2>
<ul>
<li><strong>Bluesky</strong> (your account provider and its app view): your sign-in, the reads you ask for, mutes you set, and submission records Phlogiston writes for you.</li>
<li><strong>Bluesky’s image and video servers:</strong> your browser loads post images and videos directly from them, so they see your IP address. Phlogiston sends no referrer.</li>
<li><strong>Bluesky’s public API and the PLC directory:</strong> Phlogiston’s server looks up public profiles, posts and account identities. These lookups don’t carry your identity.</li>
<li><strong>Labelwatch</strong> (same operator): Phlogiston’s server asks it for labels on account identifiers, including yours when you view your labels. Labelwatch does not log these lookups.</li>
</ul>
<p>Nothing is sold or shared for advertising. Nothing is decided about you automatically, apart from the fixed limits described in the Terms.</p>

<h2>Public by nature</h2>
<p>Posts and submission records live in public Bluesky repositories, and the Cabinet shows public posts. Removing a post from the Cabinet doesn’t delete it from Bluesky, and deleting your Phlogiston data doesn’t delete your posts or submission records. Delete those in Bluesky. Copies of public records may remain with other services on the network.</p>

<h2>Your choices and requests</h2>
<ul>
<li><strong>Delete:</strong> Settings → Delete my Phlogiston data. It works immediately, for everything listed above except the Cabinet’s moderation records.</li>
<li><strong>See, correct or delete moderation records, or anything else:</strong> open an issue at <a href="${ISSUES_URL}">${escapeHtml(ISSUES_URL.replace("https://", ""))}</a> saying what you want, without personal details. You’ll be asked to prove the account is yours by posting a short code from it.</li>
</ul>
<p>Phlogiston isn’t aimed at any particular country. The operator honours these requests from anyone, whether or not a particular privacy law applies. Where the EU or UK GDPR does apply, the basis for processing is providing the service you asked for, plus a legitimate interest in moderating the community and keeping the service secure. You can complain to your data protection authority.</p>
<p>Phlogiston is for adults: you must be 18 or older to sign in.</p>

<h2>Changes and incidents</h2>
<p>Changes to this page change its effective date and are recorded in the public source history. If a security incident exposes your data, the operator will say so on the About page.</p>
</div>`;
}

function terms(): string {
  return `<div class="prose">
<p>Effective ${POLICY_EFFECTIVE}. Plain-language terms for an experimental hobby service, written by the operator without legal review. Using Phlogiston means accepting them.</p>

<h2>The service</h2>
<ul>
<li>You must be 18 or older to sign in. Reading the public Cabinet signed out needs no account.</li>
<li>Phlogiston is provided as is, free, by one person (<a href="${OPERATOR_URL}">unpingable</a>). It may break, change, pause or shut down at any time without notice. No uptime, support or data-durability promise is made, and no warranty of any kind is given.</li>
<li>It is a client for Bluesky. Bluesky’s terms and community guidelines still apply to your account and posts.</li>
<li>To the extent the law allows, the operator is not liable for losses arising from using Phlogiston.</li>
</ul>

<h2>Acceptable use</h2>
<p>Don’t use Phlogiston to:</p>
<ul>
<li>harass, threaten, impersonate or spam people;</li>
<li>attempt to access accounts or data that aren’t yours, or probe for weaknesses beyond what responsible disclosure needs (report security problems privately; see <a href="/about">About</a>);</li>
<li>automate or scrape it at a rate that disrupts it for others;</li>
<li>break the law.</li>
</ul>
<p>The service enforces some limits itself, such as caps on hidden conversations, personal feeds and pending submissions. When these terms are broken the operator may end your sessions and decline or remove your submissions, and will say why where it’s safe to.</p>

<h2>The Cabinet: community rules</h2>
<ul>
<li>The Cabinet is a curated collection of public Bluesky posts. Anyone signed in can submit one of their own posts. The operator, as sole moderator, reads every submission and decides by hand whether to admit or decline it.</li>
<li>Admission is at the moderator’s discretion. Submissions are more likely to be admitted when they are on topic and in good faith. Hate, harassment, sexual content, spam and content that breaks Bluesky’s rules are declined or removed.</li>
<li>An admitted post can be removed later. Removal takes it out of the Cabinet; it doesn’t delete the post from Bluesky.</li>
<li>No automated moderation is used. Labels shown as context are observations from labelers, not Phlogiston’s verdicts.</li>
<li>To ask for a decision to be reconsidered, open an issue at <a href="${ISSUES_URL}">${escapeHtml(ISSUES_URL.replace("https://", ""))}</a> naming the post. Each decision is reconsidered once.</li>
</ul>

<h2>Changes</h2>
<p>These terms may change. The effective date above changes with them, and the history is public in the source repository. Material changes are noted on the About page when they take effect.</p>
</div>`;
}
