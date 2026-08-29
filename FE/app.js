/* Review queue, ledger and page views.
 *
 * No framework and no build step by design (`AGENTS.md` §5): this is three views over one
 * JSON document, and the deploy is `StaticFiles` on this directory from the same container
 * that runs the agent.
 *
 * State comes from `/api/state` when the backend is up and from `data/demo-state.json` when
 * it is not — the deterministic fallback `CLAUDE.md` §3 requires, so the page never breaks
 * because a key expired. The two payloads are the same shape on purpose; the pill in the
 * header says which one is live, and the FE never guesses.
 */
(function () {
  "use strict";

  var W = window.Wikitext;
  var esc = W.escapeHtml;

  var state = null;
  var live = false;
  var profileId = null;
  /* Approve/reject is in-memory only until the publish stage exists. STUB — labelled here
   * and in the UI, per `CLAUDE.md` §3. */
  var decisions = {};

  var TIER_LABEL = {
    1: "primary", 2: "trade press", 3: "database",
    4: "general press", 5: "social", 6: "fan wiki",
  };

  var WAVE_LABEL = {
    settled: "settled",
    in_universe_slow: "in-universe",
    release_driven: "release-driven",
    announcement_driven: "announcement-driven",
  };

  // -- helpers -----------------------------------------------------------------

  function el(id) { return document.getElementById(id); }

  function articleBase() {
    var profile = currentProfile();
    return profile ? profile.article_base : "";
  }

  function currentProfile() {
    if (!state) return null;
    for (var i = 0; i < state.profiles.length; i++) {
      if (state.profiles[i].id === profileId) return state.profiles[i];
    }
    return state.profiles[0];
  }

  function shortDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function interval(hours) {
    if (!hours) return "—";
    if (hours < 48) return hours + "h";
    var days = Math.round(hours / 24);
    return days < 60 ? days + "d" : Math.round(days / 30) + "mo";
  }

  function confidenceBar(value) {
    var pct = Math.round(value * 100);
    var band = value >= 0.75 ? "high" : value >= 0.5 ? "mid" : "low";
    return '<div class="conf"><div class="conf-track"><div class="conf-fill ' + band +
      '" style="width:' + pct + '%"></div></div><span class="conf-num">' + pct + "%</span></div>";
  }

  function statusPill(status) {
    return '<span class="pill status-' + esc(status) + '">' + esc(status) + "</span>";
  }

  function sourceList(sources) {
    if (!sources.length) return '<p class="muted">No sources yet.</p>';
    return '<ul class="sources">' + sources.map(function (s) {
      return "<li>" +
        '<span class="tier tier-' + s.tier + '" title="' + esc(TIER_LABEL[s.tier] || "") + '">T' +
        s.tier + "</span>" +
        '<a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(s.domain) + "</a>" +
        '<span class="src-note">' + esc(s.excerpt) + "</span>" +
        (s.as_of ? '<span class="src-date">' + shortDate(s.as_of) + "</span>" : "") +
        (s.placeholder ? '<span class="flag">fixture</span>' : "") +
        "</li>";
    }).join("") + "</ul>";
  }

  // -- views -------------------------------------------------------------------

  function renderQueue() {
    if (!state.queue.length) {
      return '<p class="empty">Nothing awaiting review.</p>';
    }
    var intro = '<div class="lede"><h1>Review queue</h1><p>Every edit the agent drafted, ' +
      'with the sources behind it. Nothing reaches the wiki without a decision here — this ' +
      'is the publish gate, not a preview of one.</p></div>';

    return intro + state.queue.map(function (item) {
      var decision = decisions[item.edit_id];
      return '<article class="card' + (decision ? " decided " + decision : "") + '">' +
        '<header class="card-head">' +
          '<div><h2>' + esc(item.page) + "</h2>" +
          '<p class="where">§' + item.section_index + " · " + esc(item.section_heading) +
          ' <span class="claim-id">' + esc(item.claim_id) + "</span></p></div>" +
          confidenceBar(item.confidence) +
        "</header>" +
        '<p class="summary">' + esc(item.summary) + "</p>" +
        diffBlock(item) +
        '<p class="rationale">' + esc(item.rationale) + "</p>" +
        sourceList(claimFor(item.claim_id).sources) +
        '<footer class="actions">' +
          (decision
            ? '<span class="decided-note">' + (decision === "approved" ? "Approved" : "Rejected") +
              ' — not written; the publish stage is not built yet</span>'
            : '<button class="btn approve" data-edit="' + esc(item.edit_id) + '">Approve</button>' +
              '<button class="btn reject" data-edit="' + esc(item.edit_id) + '">Reject</button>') +
          '<a class="btn ghost" href="#/wiki/' + esc(item.page_slug) + '">View in page</a>' +
        "</footer>" +
      "</article>";
    }).join("");
  }

  // The rows come from the backend, computed by core/wiki/diff.py — the browser renders them
  // and never derives them, so what is on screen is what the tests assert on.
  var GUTTER = { context: "\u00a0", removed: "\u2212", added: "+" };
  var ROW_CLASS = { context: "ctx", removed: "del", added: "ins" };

  function diffBlock(item) {
    var rows = item.diff || [];
    return '<div class="diff">' + rows.map(function (row) {
      var body = row.segments.map(function (seg) {
        return seg.changed ? '<mark>' + esc(seg.text) + "</mark>" : esc(seg.text);
      }).join("");
      return '<div class="diff-row ' + ROW_CLASS[row.kind] + '"><span class="gutter">' +
        GUTTER[row.kind] + "</span><code>" + body + "</code></div>";
    }).join("") + "</div>";
  }

  function claimFor(claimId) {
    for (var i = 0; i < state.claims.length; i++) {
      if (state.claims[i].claim_id === claimId) return state.claims[i];
    }
    return { sources: [] };
  }

  function renderLedger() {
    var intro = '<div class="lede"><h1>Claim ledger</h1><p>The agent\'s memory. Each claim ' +
      'carries its own recheck interval, which doubles when nothing changed and halves when ' +
      'something did — so the schedule is something the agent decides, not a cron table. ' +
      "The ledger holds what runs have written to it — " + state.counts.claims +
      " claims right now.</p></div>";

    var rows = state.claims.map(function (c) {
      return "<tr>" +
        '<td class="mono">' + esc(c.claim_id) + "</td>" +
        "<td>" + esc(c.page) +
          (c.entity_ref.variant ? '<span class="variant">variant</span>' : "") + "</td>" +
        '<td class="claim-text">' + esc(c.text) +
          (c.conflict_note ? '<span class="conflict">' + esc(c.conflict_note) + "</span>" : "") +
        "</td>" +
        "<td>" + esc(c.kind) + "</td>" +
        '<td class="nowrap">' + esc(WAVE_LABEL[c.wave] || c.wave) + "</td>" +
        "<td>" + statusPill(c.status) + "</td>" +
        '<td class="nowrap">' + confidenceBar(c.confidence) + "</td>" +
        '<td class="nowrap">' + interval(c.check_interval_hours) + "</td>" +
        '<td class="nowrap">' + shortDate(c.next_check_at) + "</td>" +
        "</tr>";
    }).join("");

    return intro +
      '<div class="table-wrap"><table class="ledger"><thead><tr>' +
      "<th>Claim</th><th>Page</th><th>Assertion</th><th>Kind</th><th>Wave</th>" +
      "<th>Status</th><th>Confidence</th><th>Interval</th><th>Next check</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function renderWiki(slug) {
    var page = state.pages[slug];
    if (!page) return '<p class="empty">Unknown page.</p>';

    var claims = state.claims.filter(function (c) { return c.page_slug === slug; });
    var base = articleBase();

    var nav = '<nav class="page-switch">' + Object.keys(state.pages).map(function (key) {
      return '<a class="' + (key === slug ? "on" : "") + '" href="#/wiki/' + key + '">' +
        esc(state.pages[key].title) + "</a>";
    }).join("") + "</nav>";

    var lead = page.sections[0];
    var box = W.infobox(lead.text);
    var boxKeys = {};
    claims.forEach(function (c) {
      var key = W.infoboxKey(c.wikitext_anchor);
      if (key) boxKeys[key] = c;
    });

    var infoboxHtml = "";
    if (box) {
      infoboxHtml = '<aside class="infobox"><h3>' + esc(box.name) + "</h3><dl>" +
        box.fields.map(function (f) {
          var hit = boxKeys[f.key];
          return '<div class="' + (hit ? "ib-hit" : "") + '">' +
            "<dt>" + esc(f.key) + "</dt><dd>" + W.inline(f.value, { articleBase: base }) +
            (hit ? '<span class="ib-claim">' + esc(hit.claim_id) + "</span>" : "") +
            "</dd></div>";
        }).join("") + "</dl></aside>";
    }

    var body = page.sections.map(function (section) {
      var text = section.text;
      claims.forEach(function (c) {
        if (c.section_index === section.index && !W.infoboxKey(c.wikitext_anchor)) {
          text = W.markAnchor(text, c.wikitext_anchor);
        }
      });
      return W.render(text, { articleBase: base });
    }).join("\n");

    var sidebar = '<aside class="claim-rail"><h3>Claims on this page</h3>' +
      (claims.length ? claims.map(function (c) {
        return '<div class="rail-claim">' + statusPill(c.status) +
          "<p>" + esc(c.text) + "</p>" +
          '<p class="rail-meta">' + esc(c.claim_id) + " · §" + c.section_index + " " +
          esc(c.section_heading) + "</p>" +
          '<p class="rail-why">' + esc(c.rationale) + "</p></div>";
      }).join("") : '<p class="muted">None seeded.</p>') + "</aside>";

    return nav +
      '<div class="page-meta">Seeded from revision ' + page.revid + " · " +
        shortDate(page.timestamp) + " · " + page.seed_size.toLocaleString() + " bytes · " +
        page.section_count + " sections · live copy has drifted " +
        (page.drift_pct >= 0 ? "+" : "") + page.drift_pct + "%</div>" +
      '<div class="article-grid"><article class="article"><h1>' + esc(page.title) + "</h1>" +
      infoboxHtml + body +
      '<p class="attrib">Text from the Marvel Cinematic Universe Wiki, frozen at revision ' +
      page.revid + ', licensed <a href="https://creativecommons.org/licenses/by-sa/3.0/" ' +
      'target="_blank" rel="noopener noreferrer">CC BY-SA 3.0</a>. Rendered by a deliberately ' +
      "partial parser; templates are not expanded.</p>" +
      "</article>" + sidebar + "</div>";
  }

  // -- chrome ------------------------------------------------------------------

  function renderHeader() {
    var profile = currentProfile();
    el("profile").innerHTML = state.profiles.map(function (p) {
      return '<option value="' + esc(p.id) + '"' + (p.id === profile.id ? " selected" : "") +
        ">" + esc(p.label) + (p.seeded ? "" : " (read-only)") + "</option>";
    }).join("");

    el("profile-meta").textContent = profile.api + " · " + profile.licence +
      (profile.subpages ? " · subpage titles" : " · flat titles");

    var pill = el("source-pill");
    pill.textContent = live ? "live" : "fixture";
    pill.className = "pill " + (live ? "ok" : "warn");
    pill.title = live ? "Served from /api/state" : state.stub_note;
  }

  function route() {
    var hash = location.hash || "#/queue";
    var parts = hash.replace(/^#\//, "").split("/");
    var view = parts[0] || "queue";

    Array.prototype.forEach.call(document.querySelectorAll("nav.main a"), function (a) {
      a.classList.toggle("on", a.getAttribute("href").indexOf("#/" + view) === 0);
    });

    if (view === "ledger") el("view").innerHTML = renderLedger();
    else if (view === "wiki") el("view").innerHTML = renderWiki(parts[1] || Object.keys(state.pages)[0]);
    else el("view").innerHTML = renderQueue();

    window.scrollTo(0, 0);
  }

  function bind() {
    el("view").addEventListener("click", function (event) {
      var button = event.target.closest("button[data-edit]");
      if (!button) return;
      decisions[button.dataset.edit] = button.classList.contains("approve")
        ? "approved" : "rejected";
      route();
    });

    el("profile").addEventListener("change", function (event) {
      profileId = event.target.value;
      renderHeader();
      route();
    });

    window.addEventListener("hashchange", route);
  }

  function boot(payload, isLive) {
    state = payload;
    live = isLive;
    profileId = state.profiles[0].id;
    el("stub-note").textContent = state.stub ? state.stub_note : "";
    el("stub-banner").hidden = !state.stub;
    renderHeader();
    bind();
    route();
  }

  fetch("/api/state")
    .then(function (r) { if (!r.ok) throw new Error("no backend"); return r.json(); })
    .then(function (payload) { boot(payload, true); })
    .catch(function () {
      return fetch("data/demo-state.json")
        .then(function (r) { return r.json(); })
        .then(function (payload) { boot(payload, false); });
    })
    .catch(function (error) {
      el("view").innerHTML = '<p class="empty">Could not load state: ' +
        esc(String(error)) + "</p>";
    });
})();
