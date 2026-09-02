/* The wiki, simulated in the browser.
 *
 * There is no MediaWiki, no MariaDB and no server behind this: the tables live in memory and
 * every read and write happens here. What is deliberately preserved is the *shape* of the
 * thing — `request()` takes MediaWiki action-API parameters and resolves to the JSON the real
 * `api.php` would answer with, so every caller is written as though it were talking to a
 * server over the wire. Swapping this for a real endpoint is changing what `request` does,
 * not changing anybody who calls it.
 *
 * State is a JS object seeded from `data/wiki-db.json`, laid out as MediaWiki's own tables —
 * `page`, `revision`, `text`, `redirect`. A write appends a revision and a text row and moves
 * `page_latest`, which is what the real schema does, so the rows stay portable if a database
 * ever comes back.
 *
 * **A refresh resets the wiki.** Nothing is persisted — not to disk, which a browser cannot
 * do, and not to localStorage, which is a deliberate choice: the demo wants to start from the
 * same page every time, and "reload to reset" is a simpler story on camera than a cache
 * somebody has to remember to clear. An edit therefore lives as long as the tab does, which
 * is long enough, because the article and the review gate are two routes in one app and
 * publishing re-renders rather than reloads.
 */
(function (global) {
  "use strict";

  var DB_URL = "data/wiki-db.json";
  var MAIN_NAMESPACE = 0;
  var CONTENT_MODEL = "wikitext";
  var CONTENT_FORMAT = "text/x-wiki";
  var TOKEN_SUFFIX = "+\\";

  /* Mirror of `split_sections` in backend/core/wiki/sections.py — same pattern, same indices,
     because a section number here has to mean what `action=edit&section=N` means there. */
  var HEADING = /^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$/gm;

  var db = null;          // the tables, once loaded
  var pristine = null;    // the seeded copy, kept for reset()
  var loading = null;     // in-flight load, so concurrent callers share one request

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalise(title) {
    return String(title || "").replace(/ /g, "_");
  }

  function displayTitle(stored) {
    return String(stored || "").replace(/_/g, " ");
  }

  function utf8Bytes(text) {
    return unescape(encodeURIComponent(text)).length;
  }

  function stamp(date) {
    return date.toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function splitSections(text) {
    var heads = [];
    var match;
    HEADING.lastIndex = 0;
    while ((match = HEADING.exec(text)) !== null) {
      heads.push({ start: match.index, level: match[1].length, heading: match[2] });
    }
    var out = [{
      index: 0, level: 0, heading: "",
      text: text.slice(0, heads.length ? heads[0].start : text.length)
    }];
    heads.forEach(function (h, i) {
      var end = i + 1 < heads.length ? heads[i + 1].start : text.length;
      out.push({
        index: i + 1, level: h.level, heading: h.heading, text: text.slice(h.start, end)
      });
    });
    return out;
  }

  /* An action-API failure, carrying MediaWiki's own machine-readable code. Callers match on
     the code and never on the message: `editconflict` means re-read and re-draft, while
     `nosuchsection` and `missingtitle` are different answers needing different handling. */
  function apiError(code, info) {
    return { error: { code: code, info: info } };
  }

  // -- storage ----------------------------------------------------------------

  function load() {
    if (db) return Promise.resolve(db);
    if (loading) return loading;
    loading = fetch(DB_URL)
      .then(function (r) {
        if (!r.ok) throw new Error(DB_URL + " -> HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        pristine = data;
        db = clone(data);
        return db;
      });
    return loading;
  }

  function reset() {
    db = pristine ? clone(pristine) : null;
    return db;
  }

  function findPage(title) {
    var wanted = normalise(title);
    var i;
    for (i = 0; i < db.tables.page.length; i++) {
      if (db.tables.page[i].page_title === wanted) {
        return { page: db.tables.page[i], from: null };
      }
    }
    for (i = 0; i < db.tables.redirect.length; i++) {
      var row = db.tables.redirect[i];
      if (row.rd_from_title === wanted) {
        for (var j = 0; j < db.tables.page.length; j++) {
          if (db.tables.page[j].page_title === row.rd_title) {
            return { page: db.tables.page[j], from: displayTitle(wanted) };
          }
        }
      }
    }
    return null;
  }

  function revisionsOf(pageId) {
    return db.tables.revision
      .filter(function (r) { return r.rev_page === pageId; })
      .sort(function (a, b) {
        if (a.rev_timestamp === b.rev_timestamp) return b.rev_id - a.rev_id;
        return a.rev_timestamp < b.rev_timestamp ? 1 : -1;
      });
  }

  function textOf(textId) {
    for (var i = 0; i < db.tables.text.length; i++) {
      if (db.tables.text[i].old_id === textId) return db.tables.text[i].old_text;
    }
    return null;
  }

  // -- action=query&prop=revisions --------------------------------------------

  function queryRevisions(params) {
    var found = findPage(params.titles);
    if (!found) {
      return {
        batchcomplete: true,
        query: {
          pages: [{
            ns: MAIN_NAMESPACE,
            title: displayTitle(normalise(params.titles)),
            missing: true
          }]
        }
      };
    }

    var revisions = revisionsOf(found.page.page_id);
    if (params.rvstart && params.rvdir === "older") {
      revisions = revisions.filter(function (r) { return r.rev_timestamp <= params.rvstart; });
    }

    var wanted = params.rvprop || "";
    var limit = parseInt(params.rvlimit || "1", 10);
    var rows = revisions.slice(0, limit).map(function (rev) {
      var entry = {};
      if (wanted.indexOf("ids") !== -1) {
        entry.revid = rev.rev_id;
        entry.parentid = rev.rev_parent_id;
      }
      if (wanted.indexOf("timestamp") !== -1) entry.timestamp = rev.rev_timestamp;
      if (wanted.indexOf("size") !== -1) entry.size = rev.rev_len;
      if (wanted.indexOf("user") !== -1) entry.user = rev.rev_user_text;
      if (wanted.indexOf("comment") !== -1) entry.comment = rev.rev_comment;
      if (wanted.indexOf("content") !== -1) {
        entry.slots = {
          main: {
            contentmodel: CONTENT_MODEL,
            contentformat: CONTENT_FORMAT,
            content: textOf(rev.rev_text_id)
          }
        };
      }
      return entry;
    });

    var query = {
      pages: [{
        pageid: found.page.page_id,
        ns: found.page.page_namespace,
        title: displayTitle(found.page.page_title),
        revisions: rows
      }]
    };
    if (found.from) {
      query.redirects = [{ from: found.from, to: displayTitle(found.page.page_title) }];
    }
    return { batchcomplete: true, query: query };
  }

  // -- action=edit ------------------------------------------------------------

  function edit(params) {
    var found = findPage(params.title);
    if (!found) return apiError("missingtitle", "The page " + params.title + " does not exist.");

    var revisions = revisionsOf(found.page.page_id);
    if (!revisions.length) return apiError("nosuchrevid", params.title + " has no revisions.");
    var latest = revisions[0];
    var current = textOf(latest.rev_text_id);

    /* The conflict guard. Under the single-editor assumption (`AGENTS.md` §2) this should
       never fire, which is exactly why it stays: a guard that only runs when the assumption
       is wrong is the one worth keeping. */
    if (params.basetimestamp && params.basetimestamp !== latest.rev_timestamp) {
      return apiError("editconflict",
        "Edit conflict: the page has been edited since you last read it.");
    }

    var updated;
    if (params.section === undefined || params.section === null || params.section === "") {
      updated = params.text;
    } else {
      var index = parseInt(params.section, 10);
      if (isNaN(index)) {
        return apiError("invalidsection", params.section + " is not a section number.");
      }
      var sections = splitSections(current);
      if (index < 0 || index >= sections.length) {
        return apiError("nosuchsection",
          "There is no section " + index + " on " + params.title +
          "; it has " + sections.length + ".");
      }
      /* A splice, not a re-render: every byte outside the target section is carried through
         untouched, which is what makes a section edit surgical. */
      updated = sections.map(function (s) {
        return s.index === index ? params.text : s.text;
      }).join("");
    }

    if (updated === current) {
      return {
        edit: {
          result: "Success",
          pageid: found.page.page_id,
          title: displayTitle(found.page.page_title),
          nochange: ""
        }
      };
    }

    var when = new Date();
    var textId = db.next_text_id;
    var revId = db.next_rev_id;
    var size = utf8Bytes(updated);

    db.tables.text.push({ old_id: textId, old_text: updated, old_flags: "utf-8" });
    db.tables.revision.push({
      rev_id: revId,
      rev_page: found.page.page_id,
      rev_parent_id: latest.rev_id,
      rev_timestamp: stamp(when),
      rev_user_text: params.user || "Continuity",
      rev_comment: params.summary || "",
      rev_len: size,
      rev_text_id: textId
    });
    found.page.page_latest = revId;
    found.page.page_len = size;
    found.page.page_touched = stamp(when);
    db.next_text_id = textId + 1;
    db.next_rev_id = revId + 1;

    return {
      edit: {
        result: "Success",
        pageid: found.page.page_id,
        title: displayTitle(found.page.page_title),
        contentmodel: CONTENT_MODEL,
        oldrevid: latest.rev_id,
        newrevid: revId,
        newtimestamp: stamp(when)
      }
    };
  }

  // -- the endpoint -----------------------------------------------------------

  var issued = {};

  function dispatch(params) {
    var action = params.action || "";

    if (action === "query") {
      if (params.meta === "tokens") {
        var kind = params.type || "csrf";
        var token = Math.random().toString(16).slice(2) + TOKEN_SUFFIX;
        if (kind === "csrf") issued[token] = true;
        var tokens = {};
        tokens[kind + "token"] = token;
        return { batchcomplete: true, query: { tokens: tokens } };
      }
      if (params.meta === "siteinfo") {
        return {
          batchcomplete: true,
          query: {
            general: { generator: "MediaWiki 1.43.9", sitename: "Continuity (simulated)" },
            rightsinfo: {
              url: "https://creativecommons.org/licenses/by-sa/3.0/",
              text: "CC BY-SA 3.0 Unported"
            },
            namespaces: { "0": { id: 0, case: "first-letter", subpages: true } }
          }
        };
      }
      if (params.prop === "revisions") return queryRevisions(params);
      return apiError("unknownquery", "Unsupported query.");
    }

    if (action === "login") {
      return { login: { result: "Success", lguserid: 1, lgusername: params.lgname || "Bot" } };
    }

    if (action === "edit") {
      if (!issued[params.token]) return apiError("badtoken", "Invalid CSRF token.");
      return edit(params);
    }

    return apiError("unknownaction", "Unrecognized action: " + action);
  }

  /* The one entry point, shaped like the network call it stands in for: parameters in, a
     promise of the API's JSON out. Errors arrive as an `error` block in a resolved response,
     never as a rejection, because that is what the real API does — a rejection would be
     indistinguishable from the network failing. */
  function request(params) {
    return load().then(function () { return dispatch(params); });
  }

  global.WikiAPI = {
    request: request,
    reset: reset,
    splitSections: splitSections,
    loaded: function () { return db !== null; }
  };
})(window);
