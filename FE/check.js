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
    fetch: (url) =>
      url === "/api/state"
        ? Promise.resolve({ ok: false })  // exercise the offline fallback path
        : Promise.resolve({ ok: true, json: () => Promise.resolve(state) }),
  });

  new Function(wikitextSrc).call(global);
  new Function(appSrc).call(global);

  return new Promise((resolve) =>
    setTimeout(() => resolve({ html: nodes.view.innerHTML, pill: nodes["source-pill"] }), 40));
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
  checkDiffs();
  checkWiring();
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nall FE checks passed");
  process.exit(failures ? 1 : 0);
})();
