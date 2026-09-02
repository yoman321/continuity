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
 *
 * The *queue* is the exception: it comes from `/api/drafts`, a real store. Every verdict and
 * every hand-edit is written back as it is made, so reloading the popup finds the run where it
 * was left. When no draft is reachable the fixture's queue still renders — the cards are worth
 * showing — but the publish bar says it has nothing to publish rather than offering a button
 * that would post into the void.
 */
(function () {
  "use strict";

  var W = window.Wikitext;
  var Wiki = window.WikiAPI;   // the wiki itself — see FE/wiki-api.js
  var esc = W.escapeHtml;

  var state = null;
  var live = false;
  var profileId = null;
  /* What the reviewer has settled on, per edit: the verdict, the text they edited it to, and
   * the revision each one wrote. Seeded from the stored draft and written back to it, so these
   * are a cache of the store rather than the record — the store is the record. */
  var decisions = {};
  var drafts = {};
  var published = {};
  var publishing = false;
  var publishError = "";

  /* The draft on screen. `null` when none is reachable, which is the fixture path. */
  var draftId = null;
  var draftPublished = false;

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

  /* Display only — the publisher a url belongs to. Tier and domain are the backend's to
     decide (`core/ledger/tiers.py`); this is the same kind of formatting as shortDate, and
     nothing is asserted against it. */
  function host(url) {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return url; }
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
    var intro = '<div class="lede"><h1>Review queue</h1><p>Every edit the agent drafted, ' +
      'with the sources behind it. This is the Verify gate: read the diff, change the text if ' +
      'it needs changing, then accept or reject each one. Nothing is written until the final ' +
      'publish at the bottom.</p></div>';

    return intro + renderGate(state.queue.slice());
  }

  // -- verify: the run, and the gate at the end of it --------------------------

  /* Opened from the article view, which passes the page
     the reader was on. Two things stacked: the run that produced the queue, and the queue
     itself scoped to that page. The cards are the same ones `#/queue` renders — what differs
     is the filter, the rail above them, and the site chrome being gone, because this runs in a
     popup beside the article rather than as a page of this site. */

  function pageTitle(param) {
    return (param || "").replace(/_/g, " ").trim();
  }

  function scopedItems(params) {
    var title = pageTitle(params.page);
    if (!title) return state.queue.slice();
    return state.queue.filter(function (item) {
      return item.page === title || item.page_slug === params.page;
    });
  }

  function scopedClaims(params) {
    var title = pageTitle(params.page);
    if (!title) return state.claims.slice();
    return state.claims.filter(function (claim) {
      return claim.page === title || claim.page_slug === params.page;
    });
  }

  function currentPage() {
    return parseRoute().params.page || "";
  }

  function renderVerify(params) {
    /* `start=1` is the launcher saying "and run it". Fired once — `liveRun` is set
       synchronously by `startRun`, so a re-render while the run is going does not restart it. */
    if (params.start && !liveRun) {
      // `live=1` spends real Parallel searches and model calls, so it is opt-in in the URL
      // rather than the button's default — a corner button that bills on every press is one
      // a page-refresh loop can drain (`AGENTS.md` §2).
      startRun(params.page || "", params.live === "1");
    }
    var title = pageTitle(params.page);
    var items = scopedItems(params);
    var run = runSummary(scopedClaims(params), items);

    return '<div class="verify-head"><p class="eyebrow">Continuity — run on this page</p>' +
      "<h1>" + esc(title || "All pages") + "</h1>" +
      '<p class="verify-sub">' + run.claims + (run.claims === 1 ? " claim" : " claims") +
      " tracked · " + run.edits + (run.edits === 1 ? " edit" : " edits") + " drafted" +
      (params.rev ? " · against revision " + esc(params.rev) : "") + "</p></div>" +
      renderRail(run) +
      renderGate(items);
  }

  // -- the run rail ------------------------------------------------------------

  /* The eight stages of `summary.md` §6. Every count under a stage is derived from the claims
     and the queue being rendered, so the rail describes the run that produced what is on
     screen rather than animating a fiction. The stagger is a CSS delay (`styles.css`), not a
     timer driving a fake state machine — there is no live run to narrate yet, and a rail that
     invented one would be the most convincing lie on the page. */
  var STAGES = ["Audit", "Research", "Classify", "Draft", "Diff", "Verify", "Publish", "Fan-out"];

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function runSummary(claims, items) {
    var sources = 0;
    var conflicting = 0;
    var ripples = 0;
    claims.forEach(function (claim) {
      sources += claim.sources.length;
      if (claim.conflict_note) conflicting += 1;
    });

    var decided = 0;
    var approved = 0;
    var written = 0;
    items.forEach(function (item) {
      if (decisions[item.edit_id]) decided += 1;
      if (decisions[item.edit_id] === "approved") approved += 1;
      if (published[item.edit_id]) written += 1;
    });

    return {
      claims: claims.length, sources: sources, conflicting: conflicting, ripples: ripples,
      edits: items.length, decided: decided, approved: approved, written: written,
      notes: [
        plural(claims.length, "claim"),
        plural(sources, "source"),
        conflicting ? plural(conflicting, "conflict") : "all sorted",
        plural(items.length, "edit"),
        items.length ? plural(items.length, "check") : "nothing to read",
        items.length ? decided + " of " + items.length + " decided" : "nothing to review",
        written ? plural(written, "write") : "not written",
        ripples ? plural(ripples, "claim") + " to queue" : "nothing to ripple",
      ],
    };
  }

  /* Which stage the run is standing on. Everything through Diff has already happened — the
     cards below *are* its output — so the only live question is how far past Verify the
     reviewer has got. */
  /* A run started from the article, and watched while it happens.
   *
   * `liveRun` is null until the reader presses the button. While it is set, the rail reads its
   * `stages_done` instead of inferring state from the queue — which is the difference the
   * rail's own comment used to disclaim: there is a real run to narrate now, so it narrates
   * that one, and falls back to describing the stored draft when there is not. */
  var liveRun = null;
  var runPoll = null;

  function startRun(page, live) {
    if (liveRun && !liveRun.finished) return;
    /* A run is named for its page and its number on that page, so the server refuses one with
       no page. Said here rather than sent and 422'd, because the reader can act on this. */
    if (!page) {
      liveRun = { stages_done: [], finished: true,
                  error: "a run needs a page — open an article and press the button in its corner" };
      route();
      return;
    }
    liveRun = { stages_done: [], current: "audit", finished: false, error: "", starting: true };
    route();
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: page || "", live: !!live })
    })
      .then(function (r) { return r.json().then(function (b) {
        if (!r.ok) throw new Error(b.detail || "HTTP " + r.status);
        return b;
      }); })
      .then(function (payload) { liveRun = payload; watchRun(payload.run_id); route(); })
      .catch(function (error) {
        liveRun = { stages_done: [], finished: true, error: String(error.message || error) };
        route();
      });
  }

  /* Poll rather than stream: a run is six stages over tens of seconds, so a second is finer
     than anything a reader can perceive, and it needs no server-side connection to hold. */
  function watchRun(runId) {
    if (runPoll) clearInterval(runPoll);
    runPoll = setInterval(function () {
      fetch("/api/runs/" + encodeURIComponent(runId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (payload) {
          if (!payload) return;
          liveRun = payload;
          if (payload.finished) {
            clearInterval(runPoll);
            runPoll = null;
            // The run ends by storing a draft; load it so the cards below the rail are the
            // ones this run just produced.
            if (payload.draft_id) {
              loadDraft(payload.draft_id).then(route);
              return;
            }
          }
          route();
        })
        .catch(function () { clearInterval(runPoll); runPoll = null; });
    }, 1000);
  }

  function stageStates(run) {
    var states = ["done", "done", "done", "done", "done", "active", "pending", "pending"];
    if (!run.edits || (run.decided === run.edits && run.edits)) {
      states[5] = "done";
      states[6] = run.edits ? "active" : "done";
    }
    if (run.written) {
      states[6] = "done";
      states[7] = "active";
    }
    return states;
  }

  function renderRail(run) {
    var states = liveRun ? liveStageStates() : stageStates(run);
    var nodes = STAGES.map(function (name, index) {
      return '<li class="stage ' + states[index] + '" style="animation-delay:' +
        (index * 90) + 'ms">' +
        '<span class="dot">' + (states[index] === "done" ? "✓" : "") + "</span>" +
        '<span class="stage-name">' + esc(name) + "</span>" +
        '<span class="stage-note">' + esc(run.notes[index]) + "</span>" +
        "</li>";
    }).join("");

    return '<ol class="rail">' + nodes + "</ol>" + railNote();
  }

  /* The rail from a run that is actually happening. `stages_done` is what the run itself
     recorded as each stage returned, so a tick here means that stage finished — not that a
     timer reached it. */
  function liveStageStates() {
    var done = liveRun.stages_done || [];
    return STAGES.map(function (name) {
      var key = name.toLowerCase().replace("-", "");
      if (done.indexOf(key) !== -1) return "done";
      if (!liveRun.finished && liveRun.current === key) return "active";
      return "pending";
    });
  }

  /* "Run #3" — this run's number on this page, which is also the tail of its id
     (`run-Gambit-0003`). The number comes back with the POST, so it is absent for the moment
     between the button and the server's answer. */
  function runLabel() {
    return liveRun && liveRun.ordinal ? "Run #" + liveRun.ordinal : "The run";
  }

  function railNote() {
    if (liveRun) {
      if (liveRun.error) return '<p class="rail-note err">' + esc(runLabel()) + " stopped: " + esc(liveRun.error) + "</p>";
      if (liveRun.starting) return '<p class="rail-note">Starting…</p>';
      if (!liveRun.finished) {
        return '<p class="rail-note">' + esc(runLabel()) + " is running " +
          esc(liveRun.current || "") + "… " +
          (liveRun.live ? "live — this one bills." : "replayed from recordings.") + "</p>";
      }
      var r = liveRun.report || {};
      return '<p class="rail-note">' + esc(runLabel()) + " finished — " + (r.due || 0) + " claim(s) audited, " +
        (r.researched || 0) + " searched over " + (r.rounds || 0) + " round(s), " +
        (r.drafted || 0) + " edit(s) drafted." +
        ((r.unjudged && r.unjudged.length)
          ? " " + r.unjudged.length + " claim(s) lost their judgement to an unreadable answer."
          : "") + "</p>";
    }
    return '<p class="rail-note">' + (live
      ? "Live run state."
      : "Replay of the run that produced this queue. Every count is read from the state on " +
        "screen — the stages are not simulated.") + "</p>";
  }

  // -- the gate ----------------------------------------------------------------

  function renderGate(items) {
    if (!items.length) {
      return '<p class="empty">Nothing drafted here — the agent holds no open claims that ' +
        "change this page.</p>";
    }
    return items.map(verifyCard).join("") + publishBar(items);
  }

  function queueItem(editId) {
    for (var i = 0; i < state.queue.length; i++) {
      if (state.queue[i].edit_id === editId) return state.queue[i];
    }
    return null;
  }

  function draftText(item) {
    return drafts[item.edit_id] !== undefined ? drafts[item.edit_id] : item.after;
  }

  /* One card: what the agent proposes, what will actually be written, and the two buttons.
     The diff is the agent's own, computed by `core/wiki/diff.py` — the browser never derives
     one, so a hand-edited draft is *marked* as diverging from the proposal rather than
     re-diffed against it. Accepting a card writes nothing; see `publishBar`. */
  function verifyCard(item) {
    var decision = decisions[item.edit_id];
    var text = draftText(item);
    var edited = text !== item.after;

    return '<article class="card' + (decision ? " decided " + decision : "") +
      (edited ? " edited" : "") + '">' +
      '<header class="card-head">' +
        '<div><h2>' + esc(item.page) + "</h2>" +
        '<p class="where">§' + item.section_index + " · " + esc(item.section_heading) +
        ' <span class="claim-id">' + esc(item.claim_id) + "</span></p></div>" +
        confidenceBar(item.confidence) +
      "</header>" +
      '<p class="summary">' + esc(item.summary) + "</p>" +
      verdictRow(item) +
      conflictBlock(item) +
      diffBlock(item) +
      '<label class="draft-label" for="draft-' + esc(item.edit_id) + '">What gets written' +
        (edited
          ? '<span class="edited-flag">edited — the diff above is the agent\u2019s proposal; ' +
            "this text is what publishes</span>"
          : "") +
      "</label>" +
      '<textarea class="draft" id="draft-' + esc(item.edit_id) + '" data-edit="' +
        esc(item.edit_id) + '" rows="4" spellcheck="false"' +
        (published[item.edit_id] ? " readonly" : "") + ">" + esc(text) + "</textarea>" +
      '<p class="rationale">' + esc(item.rationale) + "</p>" +
      sourceList(claimFor(item.claim_id).sources) +
      '<footer class="actions">' +
        (decision
          ? '<span class="decided-note">' +
            (decision === "approved"
              ? (published[item.edit_id] ? "Written to the wiki" : "Accepted — not written yet")
              : "Rejected") + "</span>" +
            (published[item.edit_id]
              ? ""
              : '<button class="btn undo" data-edit="' + esc(item.edit_id) +
                '">Change my mind</button>')
          : '<button class="btn approve" data-edit="' + esc(item.edit_id) + '">' +
            approveLabel(edited) + "</button>" +
            '<button class="btn reject" data-edit="' + esc(item.edit_id) + '">Reject</button>') +
        '<a class="btn ghost" href="#/wiki/' + esc(item.page_slug) + '">View in page</a>' +
      "</footer>" +
    "</article>";
  }

  function approveLabel(edited) {
    return edited ? "Accept my version" : "Accept";
  }

  /* The last check, and the only thing on this page that writes. Per-card accept/reject
     decides *what* goes; this decides whether the batch goes at all — a gate a person can
     still walk away from after reading every card (`summary.md` §6). */
  function publishBar(items) {
    // The draft is the unit of publication, so the counts are over the whole run even when the
    // cards on screen are filtered to one page — publishing an incomplete review is the thing
    // the gate exists to prevent, and a bar counting only what is visible would hide that.
    var scope = draftId ? state.queue : items;
    var pending = 0;
    var approved = 0;
    var written = 0;
    scope.forEach(function (item) {
      if (!decisions[item.edit_id]) pending += 1;
      if (decisions[item.edit_id] === "approved") approved += 1;
      if (published[item.edit_id]) written += 1;
    });
    var rejected = scope.length - approved - pending;
    var elsewhere = scope.length - items.length;
    var rest = elsewhere > 0
      ? ' <a href="#/queue">Review all ' + scope.length + " in this run</a>."
      : "";

    if (!draftId) {
      return '<div class="publish-bar waiting"><span>No stored draft — these cards are the ' +
        "fixture, and there is nothing to publish. Seed one with " +
        "<code>scripts/seed_drafts.py</code>.</span></div>";
    }
    if (draftPublished) {
      return '<div class="publish-bar written"><span><strong>' + plural(written, "edit") +
        " written to the wiki.</strong> This draft is published; fan-out queues the claims " +
        "they implicate next.</span></div>";
    }
    if (pending) {
      return '<div class="publish-bar waiting"><span>' + pending + " of " + scope.length +
        " still to review. Publish opens once every card has a decision." + rest +
        "</span></div>";
    }
    return '<div class="publish-bar"><span><strong>' + approved + " accepted</strong>" +
      (rejected ? " · " + rejected + " rejected" : "") +
      (written ? " · " + written + " already written" : "") +
      ". Nothing has been written yet — " +
      "this is the last point at which nothing happens." + rest + "</span>" +
      '<button class="btn publish"' + (approved > written && !publishing ? "" : " disabled") +
      ">" + (publishing ? "Publishing…" : "Publish " + plural(approved - written, "edit")) +
      "</button>" +
      '<button class="btn discard">Discard the run</button></div>' +
      (publishError ? '<p class="publish-note">' + esc(publishError) + "</p>" : "");
  }

  /* The Diff stage's verdicts, rendered — not recomputed here. `Draft.payload()` carries
     `bucket`, `shape` and `flags`; the fixture predates it and carries none, so this renders
     nothing rather than issuing a clean bill of health nobody checked. */
  function verdictRow(item) {
    var chips = [];
    if (item.bucket) { chips.push('<span class="chip bucket">' + esc(item.bucket) + "</span>"); }
    if (item.shape) { chips.push('<span class="chip shape">' + esc(item.shape) + "</span>"); }
    (item.flags || []).forEach(function (flag) {
      chips.push('<span class="chip flag-chip">' + esc(flag) + "</span>");
    });
    return chips.length ? '<div class="verdicts">' + chips.join("") + "</div>" : "";
  }

  /* A conflicting card shows what the sources fell out over, above the diff it proposes.
     The edit below it makes the disagreement visible rather than settling it, so the reviewer
     is deciding whether to put it on the page — not which side is right. Absent on every other
     card, and on a card whose classification carried no note. */
  function conflictBlock(item) {
    if (!item.conflict && !(item.conflict_sources || []).length) { return ""; }
    var sources = (item.conflict_sources || []).map(function (url) {
      return '<li><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(host(url)) + "</a></li>";
    }).join("");
    return '<div class="disagreement"><p class="disagreement-note">' +
      "<strong>Sources disagree.</strong> " + esc(item.conflict) + "</p>" +
      (sources ? '<ul class="disagreement-sources">' + sources + "</ul>" : "") + "</div>";
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

  /* Page text comes from the wiki itself, not from the fixture.
   *
   * `action=query` is public on this wiki exactly as it is on a real one, so the browser reads
   * it with no credential: the API key gates writing, and a secret never reaches client code
   * (`CLAUDE.md` §3). Cached per slug, so flipping between pages costs one request each and a
   * published edit shows up on the next visit to that page rather than on every keystroke.
   */
  var wikiPages = {};

  function loadWikiPage(slug, title) {
    return Wiki.request({
      action: "query",
      prop: "revisions",
      titles: title,
      rvprop: "ids|timestamp|user|comment|size|content",
      rvslots: "main",
      rvlimit: "1",
      redirects: "1",
      format: "json",
      formatversion: "2"
    })
      .then(function (payload) {
        if (payload.error) throw new Error(payload.error.code);
        var page = payload.query && payload.query.pages && payload.query.pages[0];
        if (!page || page.missing) throw new Error("not on this wiki");
        var rev = page.revisions[0];
        var content = rev.slots.main.content;
        wikiPages[slug] = {
          sections: Wiki.splitSections(content),
          revid: rev.revid,
          timestamp: rev.timestamp,
          bytes: rev.size
        };
      })
      .catch(function (error) {
        /* Cached as a failure on purpose: the router re-runs after every load, so an
           uncached error would retry forever. */
        wikiPages[slug] = { error: String((error && error.message) || error) };
      });
  }

  function renderWiki(slug) {
    var page = state.pages[slug];
    if (!page) return '<p class="empty">Unknown page.</p>';

    var live = wikiPages[slug];
    if (!live) return '<p class="empty">Reading ' + esc(page.title) + ' from the wiki\u2026</p>';
    if (live.error) {
      return '<p class="empty">The wiki did not serve ' + esc(page.title) + ': ' +
        esc(live.error) + '. The tables load from <code>data/wiki-db.json</code>; ' +
        'rebuild them with <code>python3 scripts/build_wiki_db.py</code>.</p>';
    }

    var claims = state.claims.filter(function (c) { return c.page_slug === slug; });
    var base = articleBase();

    var nav = '<nav class="page-switch">' + Object.keys(state.pages).map(function (key) {
      return '<a class="' + (key === slug ? "on" : "") + '" href="#/wiki/' + key + '">' +
        esc(state.pages[key].title) + "</a>";
    }).join("") + "</nav>";

    var lead = live.sections[0];
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

    var body = live.sections.map(function (section) {
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
          // Only when there is something to say: a live claim has no hand-written rationale,
          // and an empty paragraph reads as a missing value rather than an absent one.
          (c.rationale ? '<p class="rail-why">' + esc(c.rationale) + "</p>" : "") +
          "</div>";
      }).join("") : '<p class="muted">None seeded.</p>') + "</aside>";

    return nav +
      '<div class="page-meta">Live from the wiki · revision ' + live.revid + " · " +
        shortDate(live.timestamp) + " · " + live.bytes.toLocaleString() + " bytes · " +
        live.sections.length + " sections" +
        (live.revid === page.revid ? " · unedited since seeding" :
          ' · <strong>edited since seeding</strong> (seed was ' + page.revid + ")") +
        "</div>" +
      '<div class="article-grid"><article class="article"><h1>' + esc(page.title) + "</h1>" +
      infoboxHtml + body +
      '<p class="attrib">Text from the Marvel Cinematic Universe Wiki, seeded at revision ' +
      page.revid + ', licensed <a href="https://creativecommons.org/licenses/by-sa/3.0/" ' +
      'target="_blank" rel="noopener noreferrer">CC BY-SA 3.0</a>. Rendered by a deliberately ' +
      "partial parser; templates are not expanded.</p>" +
      "</article>" + sidebar + "</div>" + launcher(page.title);
  }

  /* The button a reader presses to run the agent on the article they are looking at.
   *
   * It lives in the corner of the page rather than in the site nav because it stands in for
   * the browser extension a real deployment would ship — the affordance that says "something
   * else is watching this page" — and because it survives a layout change. It opens the gate
   * in a popup on this same origin, which is what keeps `/api/*` same-origin with no CORS
   * (`AGENTS.md` §2), and the popup starts the run itself so the whole lifecycle has one
   * owner. */
  function launcher(title) {
    return '<button class="continuity-launch" data-launch="' + esc(title) + '" ' +
      'title="Run Continuity on this page">' +
      '<span class="launch-dot"></span>Continuity</button>';
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

  /* `#/verify?page=X&rev=N` needs a query string, which the original split-on-"/" router would
     have folded into the view name. Parsed here rather than with `URLSearchParams` so the two
     halves of a hash route are read in one place. */
  function parseRoute() {
    // No hash means the wiki: the main window is the encyclopedia, and the tool is
    // what the corner button opens.
    var hash = location.hash || "#/wiki";
    var cut = hash.indexOf("?");
    var path = (cut === -1 ? hash : hash.slice(0, cut)).replace(/^#\//, "");
    var params = {};
    if (cut !== -1) {
      hash.slice(cut + 1).split("&").forEach(function (pair) {
        if (!pair) return;
        var eq = pair.indexOf("=");
        var key = eq === -1 ? pair : pair.slice(0, eq);
        var value = eq === -1 ? "" : pair.slice(eq + 1);
        try {
          params[decodeURIComponent(key)] = decodeURIComponent(value.replace(/\+/g, " "));
        } catch (error) {
          params[key] = value;  // a malformed escape is not worth blanking the gate over
        }
      });
    }
    return { parts: path.split("/"), params: params };
  }

  function route() {
    var parsed = parseRoute();
    var parts = parsed.parts;
    var view = parts[0] || "wiki";
    var popup = view === "verify";

    /* **The article carries no tool chrome; the popup carries all of it.**
       A reader on `#/wiki/…` is looking at a wiki page, and a toolbar belonging to the agent
       sitting on top of it would say this is the agent's site — it is not. The only thing the
       agent puts on an article is the corner button. Everything that is the *tool* — the run
       rail, the review queue, the claim ledger, the wiki picker and the live/fixture pill —
       lives in the window the button opens.
       The footer stays on both: it carries the CC BY-SA attribution the wiki text is
       reproduced under (`snapshots/ATTRIBUTION.md`), which is not ours to drop for layout. */
    var article = view === "wiki";
    el("topbar").hidden = article;
    el("mainnav").hidden = article;

    Array.prototype.forEach.call(document.querySelectorAll("nav.main a"), function (a) {
      a.classList.toggle("on", a.getAttribute("href").indexOf("#/" + view) === 0);
    });

    if (view === "verify") el("view").innerHTML = renderVerify(parsed.params);
    else if (view === "ledger") el("view").innerHTML = renderLedger();
    else if (view === "wiki") {
      var slug = parts[1] || Object.keys(state.pages)[0];
      el("view").innerHTML = renderWiki(slug);
      /* Not yet read: paint the placeholder above, fetch, and re-route once. `loadWikiPage`
         always fills the cache — with an error if it has to — so this cannot loop. */
      if (!wikiPages[slug] && state.pages[slug]) {
        loadWikiPage(slug, state.pages[slug].title).then(route);
      }
    }
    else el("view").innerHTML = renderQueue();

    window.scrollTo(0, 0);
  }

  /* Accepting a card writes nothing *to the wiki*. It is a verdict, and it goes to the draft
     store so it survives the tab — the two levels are unchanged: the cards say *what* would
     go, the bar says whether any of it goes at all. Rejecting is the same act in the other
     direction, a discard that drops the card out of the run; what is left when the reviewer is
     done is the final draft. Only the publish bar posts to `/publish`. */
  var VERDICT = { approve: "accepted", reject: "rejected" };

  function decide(editId, verdict) {
    if (published[editId] || draftPublished) return;
    var stored = verdict === null ? "undecided" : VERDICT[verdict];
    if (verdict === null) delete decisions[editId];
    else decisions[editId] = verdict === "approve" ? "approved" : "rejected";
    publishError = "";
    route();
    save(editId, { decision: stored });
  }

  /* Persist one card's verdict or text. Optimistic: the card is already rendered, and a
     failure re-reads the draft rather than leaving the screen disagreeing with the store. */
  function save(editId, body) {
    if (!draftId) return Promise.resolve();
    return fetch("/api/drafts/" + encodeURIComponent(draftId) +
                 "/changes/" + encodeURIComponent(editId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (response) {
        if (response.ok) return null;
        return response.json().catch(function () { return {}; }).then(function (payload) {
          publishError = "Not saved — " + (payload.detail || "HTTP " + response.status);
          return loadDraft().then(route);
        });
      })
      .catch(function (error) {
        publishError = "Not saved — " + String(error.message || error);
        route();
      });
  }

  function currentItems() {
    var parsed = parseRoute();
    return parsed.parts[0] === "verify" ? scopedItems(parsed.params) : state.queue.slice();
  }

  /* The publish. One call over the whole draft: the store holds which changes are accepted and
     which have already landed, so the server writes exactly what is outstanding and stamps the
     draft published when nothing is left. Sequential and per-change on the server side, because
     MediaWiki has no cross-page transaction — a partial failure is a real outcome and comes
     back as one, per change (`AGENTS.md` §2). */
  /* Publish: write each accepted change to the wiki, then tell the server what happened.
   *
   * The wiki is in this browser (`FE/wiki-api.js`), so the gate performs the writes itself —
   * one `action=edit` per change, in order, exactly as the server used to. What goes to
   * `/api/drafts/{id}/publish` afterwards is the *outcome* of each one, so the draft in Mongo
   * records which revision each change created and gets stamped published. The request names
   * no page, section, anchor or text: it cannot steer a write, only report one.
   *
   * Sequential rather than parallel, and the reason is not politeness — each edit re-reads the
   * page it is patching, so two writes to the same page racing would have the second one
   * resolve its anchor against text the first had already changed.
   */
  function publishAll() {
    if (!draftId || publishing || draftPublished) return;

    // The accepted set that has not landed yet. `published` is keyed by edit_id and is what
    // makes pressing publish twice write nothing the first press already wrote.
    var pending = (state.queue || []).filter(function (c) {
      return decisions[c.edit_id] === "approved" && !published[c.edit_id];
    });
    if (!pending.length) return;

    publishing = true;
    publishError = "";
    route();

    writeSequentially(pending)
      .then(function (results) {
        return fetch("/api/drafts/" + encodeURIComponent(draftId) + "/publish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ results: results })
        }).then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (body) {
            publishing = false;
            if (!response.ok) {
              publishError = body.detail || "HTTP " + response.status;
              route();
              return;
            }
            applyDraft(body.draft);
            var failed = results.filter(function (r) { return r.status !== "written"; });
            publishError = failed.length
              ? failed.length + " of " + results.length + " not written — " +
                (failed[0].error || failed[0].status)
              : "";
            route();
          });
        });
      })
      .catch(function (error) {
        publishing = false;
        publishError = String(error.message || error);
        route();
      });
  }

  /* One edit at a time, collecting an outcome per change rather than failing the batch.
     A partial publish is a real result — the wiki has no cross-page transaction and neither
     does this — so every change reports for itself and the reviewer is told which landed. */
  function writeSequentially(changes) {
    var results = [];

    function step(i) {
      if (i >= changes.length) return Promise.resolve(results);
      var change = changes[i];
      return editOne(change)
        .then(function (outcome) { results.push(outcome); })
        .then(function () { return step(i + 1); });
    }
    return step(0);
  }

  /* One change -> one `action=edit`, substituting the approved text for the drafted anchor in
     whatever the section says now. A missing or ambiguous anchor is refused rather than
     guessed at, and an edit already on the page is a no-op rather than a second append. */
  function editOne(change) {
    var text = change.after;
    return Wiki.request({
      action: "query", prop: "revisions", titles: change.page,
      rvprop: "ids|timestamp|content", rvslots: "main", rvlimit: "1",
      redirects: "1", format: "json", formatversion: "2"
    }).then(function (payload) {
      if (payload.error) throw new Error(payload.error.code);
      var page = payload.query && payload.query.pages && payload.query.pages[0];
      if (!page || page.missing) throw new Error("missingtitle");
      var rev = page.revisions[0];
      var sections = Wiki.splitSections(rev.slots.main.content);
      var section = sections[change.section_index];
      if (!section) throw new Error("nosuchsection");

      var occurrences = section.text.split(change.before).length - 1;
      if (occurrences === 0) {
        // Either somebody else changed the line, or this edit is already on the page.
        return section.text.indexOf(text) !== -1
          ? { edit_id: change.edit_id, status: "nochange" }
          : { edit_id: change.edit_id, status: "missing",
              error: "the drafted text is no longer on the page" };
      }
      if (occurrences > 1) {
        return { edit_id: change.edit_id, status: "missing",
                 error: "the drafted text appears " + occurrences + " times; refusing to guess" };
      }

      return Wiki.request({
        action: "query", meta: "tokens", type: "csrf", format: "json"
      }).then(function (t) {
        return Wiki.request({
          action: "edit",
          title: change.page,
          section: String(change.section_index),
          text: section.text.replace(change.before, text),
          summary: change.summary,
          basetimestamp: rev.timestamp,
          token: t.query.tokens.csrftoken,
          format: "json"
        });
      }).then(function (result) {
        if (result.error) {
          return { edit_id: change.edit_id, status:
            result.error.code === "editconflict" ? "conflict" : "error",
            error: result.error.info };
        }
        return "nochange" in result.edit
          ? { edit_id: change.edit_id, status: "nochange" }
          : { edit_id: change.edit_id, status: "written", revid: result.edit.newrevid };
      });
    }).catch(function (error) {
      return { edit_id: change.edit_id, status: "error", error: String(error.message || error) };
    });
  }

  /* Walk away. Puts every unwritten card back to undecided and leaves the hand-edits alone, so
     "discard" means "I am not publishing this run", not "throw away my edits". */
  function discardRun() {
    if (draftPublished) return;
    currentItems().forEach(function (item) {
      if (published[item.edit_id]) return;
      delete decisions[item.edit_id];
      save(item.edit_id, { decision: "undecided" });
    });
    publishError = "";
    route();
  }

  function bind() {
    el("view").addEventListener("click", function (event) {
      var button = event.target.closest("button");
      if (!button) return;
      if (button.classList.contains("publish")) return publishAll();
      if (button.classList.contains("discard")) return discardRun();
      /* The article's corner button. It opens the gate in a popup on this origin and passes
         the page; the popup starts the run, so the run and the review it produces have one
         owner and one window. */
      if (button.dataset.launch) {
        var url = "#/verify?page=" + encodeURIComponent(button.dataset.launch) + "&start=1";
        var popup = window.open(url, "continuity-gate", "width=960,height=980");
        if (!popup) window.location.hash = url.slice(1);  // popups blocked: run here instead
        return;
      }
      if (button.classList.contains("runagain")) return startRun(currentPage(), false);
      if (!button.dataset.edit) return;
      if (button.classList.contains("undo")) return decide(button.dataset.edit, null);
      decide(button.dataset.edit, button.classList.contains("approve") ? "approve" : "reject");
    });

    /* Typing in a draft must not re-render the card — that would throw the caret to the top
       on every keystroke. So the edited state is applied to the DOM in place instead. */
    el("view").addEventListener("input", function (event) {
      var box = event.target;
      if (box.tagName !== "TEXTAREA" || !box.dataset || !box.dataset.edit) return;
      var item = queueItem(box.dataset.edit);
      if (!item) return;
      drafts[item.edit_id] = box.value;
      var edited = box.value !== item.after;
      var card = box.closest(".card");
      if (card) {
        card.classList.toggle("edited", edited);
        var approve = card.querySelector("button.approve");
        if (approve) approve.innerHTML = approveLabel(edited);
      }
    });

    /* Saved on blur rather than on every keystroke: the text is what publishes, so it has to
       reach the store, but a POST per character would be a write amplifier for no gain. */
    el("view").addEventListener("change", function (event) {
      var box = event.target;
      if (box.tagName !== "TEXTAREA" || !box.dataset || !box.dataset.edit) return;
      if (published[box.dataset.edit] || draftPublished) return;
      save(box.dataset.edit, { text: box.value });
    });

    el("profile").addEventListener("change", function (event) {
      profileId = event.target.value;
      renderHeader();
      route();
    });

    window.addEventListener("hashchange", route);
  }

  /* The stored draft, folded into the shape the views already render. `state.queue` becomes
     the draft's changes, and the three maps are seeded from it — so a reload lands on the same
     screen the reviewer left rather than an empty one. */
  function applyDraft(payload) {
    if (!payload || !payload.changes) return;
    draftId = payload.draft_id;
    draftPublished = !!payload.published;
    state.queue = payload.changes;
    decisions = {};
    drafts = {};
    published = {};
    payload.changes.forEach(function (change) {
      if (change.decision === "accepted") decisions[change.edit_id] = "approved";
      if (change.decision === "rejected") decisions[change.edit_id] = "rejected";
      if (change.written_revid !== null && change.written_revid !== undefined) {
        published[change.edit_id] = true;
      }
    });
  }

  /* Pick the run to review: the one named in the URL, else the oldest still open, else the
     newest. A published draft is still readable — that is how the reviewer sees what landed. */
  function loadDraft(wantedId) {
    // An explicit id wins: a run that just finished knows exactly which draft it wrote, and
    // "newest unpublished" would be a guess that is right until two runs overlap.
    var wanted = wantedId || parseRoute().params.draft;
    return fetch("/api/drafts")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        var list = (payload && payload.drafts) || [];
        if (!list.length) return null;
        var open = list.filter(function (d) { return !d.published; });
        var chosen = wanted
          ? list.filter(function (d) { return d.draft_id === wanted; })[0]
          : (open.length ? open[open.length - 1] : list[0]);
        if (!chosen) return null;
        return fetch("/api/drafts/" + encodeURIComponent(chosen.draft_id))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(applyDraft);
      })
      .catch(function () { return null; });  // no store reachable: the fixture queue stands
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
    loadDraft().then(route);
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
