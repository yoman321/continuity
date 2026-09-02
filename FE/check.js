/* Verification for the frontend. Run from the repo root:
 *
 *     node FE/check.js
 *
 * Node is needed to *check* the FE, never to build or serve it — the container ships these
 * files as-is (`AGENTS.md` §5). This exists because "it looks right" is not a check
 * (`CLAUDE.md` §5): every assertion below is a count or an equality, and each one here was
 * added after it caught something — a `[[File:|caption with [[links]]]]` leak, a section
 * sliced to its heading alone, an infobox-anchored claim that silently highlighted nothing.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const state = JSON.parse(fs.readFileSync(path.join(ROOT, "FE/data/demo-state.json"), "utf8"));
const wikitextSrc = fs.readFileSync(path.join(ROOT, "FE/wikitext.js"), "utf8");
const appSrc = fs.readFileSync(path.join(ROOT, "FE/app.js"), "utf8");
const wikiApiSrc = fs.readFileSync(path.join(ROOT, "FE/wiki-api.js"), "utf8");
/* The wiki the browser loads. Page text is checked against *this* now, not against the
   fixture: the fixture carries a display sample of a few sections, while this is the whole
   article the article view actually renders. */
const wikiDb = JSON.parse(
  fs.readFileSync(path.join(ROOT, "FE/data/wiki-db.json"), "utf8"));

const CTRL = new RegExp("[\\u0001-\\u0004]", "g");
const WIKITEXT = /\{\{|\}\}|\[\[|\]\]|'''/;

let failures = 0;
const count = (text, re) => (text.match(re) || []).length;

function check(label, ok, detail) {
  if (ok) {
    console.log(`ok   ${label}${detail ? " — " + detail : ""}`);
  } else {
    failures++;
    console.log(`FAIL ${label}${detail ? ": " + detail : ""}`);
  }
}

// -- renderer ----------------------------------------------------------------

function loadWikitext() {
  const sandbox = { window: {} };
  Object.assign(global, sandbox);
  new Function(wikitextSrc).call(global);
  return global.window.Wikitext;
}

function checkRenderer(W) {
  console.log("\n# renderer");
  for (const [slug, page] of Object.entries(state.pages)) {
    for (const section of page.sections) {
      const html = W.render(section.text, { articleBase: "https://example.org/wiki/" });
      const label = `${slug}#${section.heading || "(lead)"}`;
      const open = count(html, /<(ul|ol|li|p|blockquote)>/g);
      const close = count(html, /<\/(ul|ol|li|p|blockquote)>/g);
      check(`${label}: balanced blocks`, open === close, `${open} open, ${close} close`);
      check(`${label}: no leaked wikitext`, !WIKITEXT.test(html));
      check(`${label}: no sentinels survive`, count(html, CTRL) === 0);
    }
    check(`${slug}: infobox parsed`, W.infobox(page.sections[0].text) !== null);
  }
}

function checkAnchors(W) {
  console.log("\n# claim anchors");
  for (const claim of state.claims) {
    const page = state.pages[claim.page_slug];
    const section = page.sections.find((s) => s.index === claim.section_index);
    check(`${claim.claim_id}: section carried`, Boolean(section));
    if (!section) continue;

    const key = W.infoboxKey(claim.wikitext_anchor);
    if (key) {
      const box = W.infobox(section.text);
      const row = box && box.fields.some((f) => f.key === key);
      check(`${claim.claim_id}: infobox row "${key}" exists`, Boolean(row));
      continue;
    }
    const html = W.render(W.markAnchor(section.text, claim.wikitext_anchor),
      { articleBase: "https://example.org/wiki/" });
    check(`${claim.claim_id}: anchor highlighted exactly once`,
      count(html, /<mark class="claim-hit">/g) === 1);
  }
}

// -- app views ---------------------------------------------------------------

function makeNode(id) {
  return {
    id, innerHTML: "", textContent: "", className: "", title: "", hidden: false,
    value: "", dataset: {},
    addEventListener() {},
    classList: { toggle() {}, contains: () => false },
    getAttribute: () => "",
  };
}

const DRAFT_ID = "draft-check-0001";

/* The draft the stub store hands back: the fixture's queue, undecided and unwritten, in the
   shape `/api/drafts/{id}` returns. Built from `state.queue` so the card checks below stay
   assertions about the fixture rather than about a second copy of it. */
function storedDraft() {
  return {
    draft_id: DRAFT_ID,
    wiki: "check",
    created_at: "2026-08-30T12:00:00+00:00",
    published: false,
    published_at: null,
    is_decided: false,
    changes: state.queue.map((item) =>
      Object.assign({}, item, { decision: "undecided", written_revid: null })),
    counts: { changes: state.queue.length, accepted: 0, undecided: state.queue.length,
              written: 0 },
  };
}

/* Boot app.js at one route against a stub DOM and return what it wrote into #view.
   Not a browser — it proves the render path does not throw and the output is right, which
   is otherwise invisible until someone opens the page. */
function renderAt(hash) {
  const nodes = {};
  ["view", "profile", "profile-meta", "source-pill", "stub-note", "stub-banner"]
    .forEach((id) => { nodes[id] = makeNode(id); });

  Object.assign(global, {
    document: {
      getElementById: (id) => nodes[id] || (nodes[id] = makeNode(id)),
      querySelectorAll: () => [],
    },
    location: { hash },
    window: { addEventListener() {}, scrollTo() {} },
    fetch: (url) => {
      // `/api/state` is down on purpose: the ledger and page views must fall back to the
      // fixture. The draft routes are up, because the queue comes from the store now and the
      // render path under test is the one a reviewer actually gets.
      if (url === "/api/state") return Promise.resolve({ ok: false });
      if (url === "/api/drafts") return Promise.resolve({ ok: true, json: () =>
        Promise.resolve({ drafts: [{ draft_id: DRAFT_ID, published: false }] }) });
      if (url.indexOf("/api/drafts/") === 0) return Promise.resolve({ ok: true, json: () =>
        Promise.resolve(storedDraft()) });
      // The wiki: a static file in the browser, so this is the one fetch that is real.
      if (url === "data/wiki-db.json") return Promise.resolve({ ok: true, json: () =>
        Promise.resolve(JSON.parse(JSON.stringify(wikiDb))) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(state) });
    },
  });

  new Function(wikitextSrc).call(global);
  new Function(wikiApiSrc).call(global);
  new Function(appSrc).call(global);

  return new Promise((resolve) =>
    setTimeout(() => resolve({ html: nodes.view.innerHTML, pill: nodes["source-pill"] }), 120));
}

async function checkViews() {
  console.log("\n# queue");
  const queue = await renderAt("#/queue");
  check("one card per drafted edit",
    count(queue.html, /<article class="card/g) === state.queue.length,
    `${count(queue.html, /<article class="card/g)} of ${state.queue.length}`);
  check("every card shows an addition",
    count(queue.html, /diff-row ins/g) === state.queue.length);
  check("citations carry tier badges", count(queue.html, /class="tier tier-\d"/g) > 0,
    `${count(queue.html, /class="tier tier-\d"/g)} badges`);
  check("offline fallback reports itself", queue.pill.textContent === "fixture");
  // Diffs deliberately show wikitext — it is what the write path patches — so the
  // requirement is that it is escaped, not that it is absent.
  check("diffs escape their wikitext", !/<script/i.test(queue.html) && /\[\[/.test(queue.html));

  console.log("\n# ledger");
  const ledger = await renderAt("#/ledger");
  check("one row per claim",
    count(ledger.html, /<tr>/g) === state.claims.length + 1,
    `${count(ledger.html, /<tr>/g) - 1} rows`);
  check("contradicted claim surfaces its conflict",
    ledger.html.indexOf("do not agree") !== -1);
  check("settled claim reaches the 6-month ceiling", /6mo/.test(ledger.html));

  console.log("\n# wiki pages");
  for (const slug of Object.keys(state.pages)) {
    const view = await renderAt("#/wiki/" + slug);
    const expected = state.claims.filter((c) => c.page_slug === slug).length;
    const marks = count(view.html, /<mark class="claim-hit">/g) +
      count(view.html, /class="ib-hit"/g);
    check(`${slug}: renders`, view.html.length > 300, `${view.html.length} chars`);
    check(`${slug}: infobox present`, view.html.indexOf('class="infobox"') !== -1);
    check(`${slug}: highlights every claim`, marks === expected,
      `${marks} of ${expected}`);

    // Only the article must be free of wikitext; the claim rail prints anchors verbatim.
    const article = view.html.slice(
      view.html.indexOf('<article class="article"'),
      view.html.indexOf('<aside class="claim-rail"'));
    check(`${slug}: article has no leaked wikitext`, !WIKITEXT.test(article),
      `${article.length} chars`);
  }
}

// -- diffs -------------------------------------------------------------------

function checkDiffs() {
  console.log("\n# diffs");
  for (const item of state.queue) {
    const rows = item.diff || [];
    check(`${item.edit_id}: has diff rows`, rows.length > 0, `${rows.length}`);

    // The invariant the whole gate rests on: the rows *are* the two texts. If they are not,
    // the reviewer approved something other than what would be written to the wiki.
    const side = (kinds) => rows.filter((r) => kinds.includes(r.kind))
      .map((r) => r.segments.map((s) => s.text).join("")).join("\n");
    check(`${item.edit_id}: rows rebuild before`, side(["context", "removed"]) === item.before);
    check(`${item.edit_id}: rows rebuild after`, side(["context", "added"]) === item.after);

    const changed = rows.some((r) => r.segments.some((s) => s.changed));
    const added = rows.filter((r) => r.kind === "added").length;
    check(`${item.edit_id}: something is marked`, changed || added > 0);

    const kinds = new Set(rows.map((r) => r.kind));
    const known = [...kinds].every((k) => ["context", "removed", "added"].includes(k));
    check(`${item.edit_id}: only known row kinds`, known, [...kinds].join(", "));
  }
}

// -- the verify gate ----------------------------------------------------------

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/* `#/verify?page=X` is the gate, opened from the article view (or a bookmarklet).
   The assertions are the two things that make it a gate rather than a view: it shows exactly
   the cards for the page it was opened from, and the text is editable before it is written. */
async function checkVerify(W) {
  console.log("\n# verify gate");

  const item = state.queue.find((q) => q.page_slug === "Deadpool_Wolverine");
  const wgPageName = item.page.replace(/ /g, "_");   // what MediaWiki hands the launcher
  const expected = state.queue.filter((q) => q.page === item.page).length;

  const one = await renderAt(`#/verify?page=${encodeURIComponent(wgPageName)}&rev=2019481`);
  const cards = count(one.html, /<article class="card/g);
  check("scopes to the page the launcher opened it from", cards === expected,
    `${cards} of ${expected}`);
  check("names that page", one.html.indexOf(W.escapeHtml(item.page)) !== -1);
  check("carries the revision it was opened at", /against revision 2019481/.test(one.html));

  const box = new RegExp(`<textarea class="draft" id="draft-${escapeRe(item.edit_id)}"[^>]*>` +
    escapeRe(W.escapeHtml(item.after)) + "</textarea>");
  check("the draft is editable and seeded with what the agent wrote", box.test(one.html));

  const none = await renderAt("#/verify?page=Not_A_Seeded_Page");
  check("an unqueued page says so instead of showing every card",
    count(none.html, /<article class="card/g) === 0 && /Nothing drafted/.test(none.html));

  const all = await renderAt("#/queue");
  check("the queue is the same gate, unfiltered",
    count(all.html, /<textarea class="draft"/g) === state.queue.length,
    `${count(all.html, /<textarea class="draft"/g)} of ${state.queue.length}`);

  // -- the run rail. Counts are asserted against the state they claim to describe, not
  //    against a screenshot (`CLAUDE.md` §5).
  const claims = state.claims.filter((c) => c.page === item.page);
  const sources = claims.reduce((n, c) => n + c.sources.length, 0);
  const conflicts = claims.filter((c) => c.conflict_note).length;

  check("the rail shows all eight stages", count(one.html, /<li class="stage /g) === 8,
    `${count(one.html, /<li class="stage /g)}`);
  check("everything through Diff is ticked", count(one.html, /✓/g) === 5,
    `${count(one.html, /✓/g)} ticks`);
  check("Verify is where the run is standing", /class="stage active"/.test(one.html));
  check("the rail counts this page's claims", one.html.indexOf(`${claims.length} claims`) !== -1,
    `${claims.length}`);
  check("the rail counts the sources behind them",
    one.html.indexOf(`${sources} sources`) !== -1, `${sources}`);
  check("the rail counts the conflicts",
    one.html.indexOf(conflicts ? `${conflicts} conflict` : "all sorted") !== -1);

  // -- two levels: the cards decide what goes, the bar decides whether anything goes.
  check("publish is shut until every card has a decision", /still to review/.test(one.html));
  // Accepting persists a verdict now, so "writes nothing" is about the wiki: the card path
  // may reach `/changes/`, and only the bar may reach `/publish`.
  check("accepting a card writes nothing to the wiki",
    /function decide\(([\s\S]*?)\n  \}/.exec(appSrc)[1].indexOf("/publish") === -1);
  check("the publish button is the only thing that publishes",
    (appSrc.match(/\/publish"/g) || []).length === 1 &&
    /function publishAll\(\)[\s\S]*?\/publish"/.test(appSrc));
  check("a verdict is written back to the store",
    /function decide\(([\s\S]*?)\n  \}/.exec(appSrc)[1].indexOf("save(") !== -1);
}

/* The wiki-side half. It is not loaded by the browser here — it is installed onto MediaWiki —
   so what is checkable is its contract with the popup, and each of these has a failure mode
   that is silent in a demo. */
function checkGate() {
  console.log("\n# the gate");

  /* The wiki lives in this tab (`FE/wiki-api.js`), so a full page load discards every edit
     that was just published. The gate must therefore NOT reload anything after publishing —
     it re-renders instead. This check is inverted from what it used to assert, and the
     inversion is the point: reloading was right while the wiki was a separate MediaWiki page
     and is now the fastest way to throw the demo's best moment away. */
  check("publishing does not reload anything away",
    !/location\.reload\(\)/.test(appSrc));

  // A conflicting claim reaches the gate as a card like any other; what makes it readable is
  // that the disagreement is on screen above the diff, with both sides linked. Rendering the
  // card without it would ask the reviewer to take an edit on trust.
  check("a conflicting card shows what the sources fell out over",
    /conflictBlock\(item\)/.test(appSrc) &&
    /item\.conflict_sources/.test(appSrc) &&
    appSrc.indexOf("conflictBlock(item) +\n      diffBlock(item)") !== -1);

  check("a hand-edited draft is saved as the text that publishes",
    /save\(box\.dataset\.edit, \{ text: box\.value \}\)/.test(appSrc));

  /* `AGENTS.md` §2: the publish request reports outcomes and steers nothing. The wiki write
     happens in the browser now, so the body carries what each edit *did* — an id, a status, a
     revision — and must never carry where to write. A page, section, anchor or text on the
     wire would turn a public route back into a write primitive. */
  const publishBody = /\/publish"[\s\S]{0,320}?JSON\.stringify\(([\s\S]{0,120}?)\)/.exec(appSrc);
  check("the publish request sends a body of outcomes", publishBody !== null);
  if (publishBody) {
    check("the publish body steers nothing",
      !/\b(page|section|anchor|before|after|title|summary)\b/.test(publishBody[1]),
      publishBody[1].trim());
  }

  // One writer, and it is the wiki's own endpoint — never a direct poke at the tables.
  check("the gate writes through the wiki API, not around it",
    /Wiki\.request\(\{[\s\S]{0,80}action: "edit"/.test(appSrc));
}

// -- wiring ------------------------------------------------------------------

function checkWiring() {
  console.log("\n# wiring");
  const html = fs.readFileSync(path.join(ROOT, "FE/index.html"), "utf8");
  const css = fs.readFileSync(path.join(ROOT, "FE/styles.css"), "utf8");

  const idsInHtml = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
  const idsUsed = new Set([...appSrc.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]));
  const missing = [...idsUsed].filter((id) => !idsInHtml.has(id));
  check("every element app.js looks up exists in index.html", missing.length === 0,
    missing.join(", "));

  const classes = new Set();
  for (const source of [appSrc, html]) {
    for (const m of source.matchAll(/class="([a-z][a-z0-9 _-]*)"/g)) {
      m[1].split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    }
  }
  const styled = new Set([...css.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]));
  const unstyled = [...classes].filter((c) => !styled.has(c));
  check("every class used is styled", unstyled.length === 0, unstyled.join(", "));

  check("no external requests", !/https?:\/\/(?!creativecommons|marvelcinematic|en\.wiki|memory-alpha)/
    .test(css) && !/<link[^>]+href="http/.test(html) && !/<script[^>]+src="http/.test(html));
}

(async () => {
  const W = loadWikitext();
  checkRenderer(W);
  checkAnchors(W);
  await checkViews();
  await checkVerify(W);
  checkDiffs();
  checkWiring();
  checkGate();
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nall FE checks passed");
  process.exit(failures ? 1 : 0);
})();
