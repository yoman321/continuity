/* Minimal wikitext -> HTML renderer.
 *
 * Deliberately a subset. MediaWiki's real parser is enormous and we do not need it: the
 * seeded instance renders its own pages, and this exists only so the demo page can show the
 * wikitext a claim is anchored in without a round-trip. Templates are stripped rather than
 * expanded — we have no template store, and a half-expanded template reads worse than none.
 *
 * The fixture carries wikitext verbatim from snapshots/ so the CC BY-SA attribution holds
 * (see FE/README.md). Rendering is display only; nothing here is written back.
 */
(function (global) {
  "use strict";

  var MARK_OPEN = "\u0001";
  var MARK_CLOSE = "\u0002";

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Top-level {{...}} spans, brace-matched. Templates nest ({{Alias}} inside {{Character}}),
   * so a regex cannot do this correctly. */
  function findTemplates(text) {
    var spans = [];
    var depth = 0;
    var start = -1;
    for (var i = 0; i < text.length - 1; i++) {
      if (text[i] === "{" && text[i + 1] === "{") {
        if (depth === 0) start = i;
        depth++;
        i++;
      } else if (text[i] === "}" && text[i + 1] === "}") {
        depth--;
        if (depth === 0 && start >= 0) {
          spans.push({ start: start, end: i + 2, raw: text.slice(start, i + 2) });
          start = -1;
        }
        if (depth < 0) depth = 0;
        i++;
      }
    }
    return spans;
  }

  /* Split a template body on pipes that sit at nesting depth zero, so nested templates and
   * [[links|with pipes]] stay in one piece. */
  function splitParams(body) {
    var parts = [];
    var buffer = "";
    var brace = 0;
    var bracket = 0;
    for (var i = 0; i < body.length; i++) {
      var ch = body[i];
      if (ch === "{" && body[i + 1] === "{") { brace++; buffer += "{{"; i++; continue; }
      if (ch === "}" && body[i + 1] === "}") { brace--; buffer += "}}"; i++; continue; }
      if (ch === "[" && body[i + 1] === "[") { bracket++; buffer += "[["; i++; continue; }
      if (ch === "]" && body[i + 1] === "]") { bracket--; buffer += "]]"; i++; continue; }
      if (ch === "|" && brace === 0 && bracket === 0) { parts.push(buffer); buffer = ""; continue; }
      buffer += ch;
    }
    parts.push(buffer);
    return parts;
  }

  function templateName(raw) {
    return splitParams(raw.slice(2, -2))[0].trim();
  }

  /* The infobox: the biggest named-parameter template in the lead. Every MCU Wiki page opens
   * with one ({{Character}}, {{Phase}}, {{Film}}), and picking by shape rather than by name
   * means this does not need a per-wiki template list to work. */
  function parseInfobox(text) {
    var best = null;
    findTemplates(text).forEach(function (span) {
      var params = splitParams(span.raw.slice(2, -2));
      var fields = [];
      params.slice(1).forEach(function (param) {
        var eq = param.indexOf("=");
        if (eq === -1) return;
        var key = param.slice(0, eq).trim();
        var value = param.slice(eq + 1).trim();
        if (key && value) fields.push({ key: key, value: value });
      });
      if (fields.length >= 3 && (!best || fields.length > best.fields.length)) {
        best = { name: params[0].trim(), fields: fields };
      }
    });
    return best;
  }

  function stripRefs(text) {
    return text
      .replace(/<ref[^>]*\/>/gi, "")
      .replace(/<ref[^>]*>[\s\S]*?<\/ref>/gi, "")
      .replace(/<!--[\s\S]*?-->/g, "");
  }

  /* Depth-0 [[...]] spans. Needed for the same reason findTemplates is: file links carry
   * captions, captions carry links, and `[^\]]*` stops at the first `]` of the inner one —
   * which leaves a trail of stray `]]` through every Plot section. */
  function findLinks(text) {
    var spans = [];
    var depth = 0;
    var start = -1;
    for (var i = 0; i < text.length - 1; i++) {
      if (text[i] === "[" && text[i + 1] === "[") {
        if (depth === 0) start = i;
        depth++;
        i++;
      } else if (text[i] === "]" && text[i + 1] === "]") {
        depth--;
        if (depth === 0 && start >= 0) {
          spans.push({ start: start, end: i + 2, raw: text.slice(start, i + 2) });
          start = -1;
        }
        if (depth < 0) depth = 0;
        i++;
      }
    }
    return spans;
  }

  /* Files, categories and interwiki prefixes are page metadata, not prose. Dropped whole —
   * including the caption, which is where the nested links live. */
  var NAMESPACED = /^(?:file|image|category|[a-z]{2,3}):/i;

  function stripNamespacedLinks(text) {
    var out = "";
    var cursor = 0;
    findLinks(text).forEach(function (span) {
      var target = span.raw.slice(2, -2).split("|")[0].trim();
      if (!NAMESPACED.test(target)) return;
      out += text.slice(cursor, span.start);
      cursor = span.end;
    });
    return out + text.slice(cursor);
  }

  /* Citation and cross-wiki plumbing. Flattening these to their parameters yields noise
   * ("DW", "Marvel Cinematic Universe: Phase Six"), so they are dropped whole. */
  var NOISE_TEMPLATE = /^(?:ref|reflist|wp|wps|cite|citation|about|main)$/i;

  /* Reduce a template to its parameter *values*, recursively.
   *
   * Needed for infobox fields, which the block renderer never sees: it strips templates
   * before the line pass, but an infobox value is itself template-laden — `{{Citizenship|USA}}`,
   * `{{Alias|codenames = Gambit}}`, `{{Conjecture|Etienne}}`. Dropping those loses the answer;
   * printing them raw leaks braces into the page. Keeping the values gets both right.
   */
  function flattenTemplates(text) {
    var out = text;
    for (var pass = 0; pass < 4 && out.indexOf("{{") !== -1; pass++) {
      var spans = findTemplates(out);
      if (!spans.length) break;
      var next = "";
      var cursor = 0;
      spans.forEach(function (span) {
        next += out.slice(cursor, span.start);
        var params = splitParams(span.raw.slice(2, -2));
        if (!NOISE_TEMPLATE.test(params[0].trim())) {
          next += params.slice(1).map(function (param) {
            var eq = param.indexOf("=");
            return (eq === -1 ? param : param.slice(eq + 1)).trim();
          }).filter(Boolean).join(" ");
        }
        cursor = span.end;
      });
      out = next + out.slice(cursor);
    }
    return out;
  }

  function renderInline(text, opts) {
    var base = (opts && opts.articleBase) || "";
    var out = escapeHtml(stripNamespacedLinks(flattenTemplates(stripRefs(text))));

    // [[Target|Label]] and [[Target]]
    out = out.replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, function (_, target, label) {
      return link(base, target, label);
    });
    out = out.replace(/\[\[([^\]]+)\]\]/g, function (_, target) {
      return link(base, target, target);
    });

    // [https://example.com Label] and a bare [https://example.com]
    out = out.replace(/\[(https?:\/\/[^\s\]]+)\s+([^\]]+)\]/g, function (_, url, label) {
      return '<a class="ext" href="' + url + '" target="_blank" rel="noopener noreferrer">' +
        label + "</a>";
    });
    out = out.replace(/\[(https?:\/\/[^\s\]]+)\]/g, function (_, url) {
      return '<a class="ext" href="' + url + '" target="_blank" rel="noopener noreferrer">' +
        url + "</a>";
    });

    /* Quote markup runs AFTER link substitution, so the content between the delimiters can
       contain an apostrophe that was never in the wikitext — `[[Gambit's Bo Staff|...]]`
       becomes an href carrying one. `[^']+?` therefore stopped at the wrong character and
       left `'''` sitting in the output, visible only on sections the fixture never carried.
       So: any character that is not a quote or a newline, or a lone quote that does not
       begin the closing delimiter. Newlines stay excluded because MediaWiki's own quote
       markup does not span lines. */
    out = out.replace(/'''''((?:[^'\n]|'(?!''''))+?)'''''/g, "<strong><em>$1</em></strong>");
    out = out.replace(/'''((?:[^'\n]|'(?!''))+?)'''/g, "<strong>$1</strong>");
    out = out.replace(/''((?:[^'\n]|'(?!'))+?)''/g, "<em>$1</em>");
    out = out.replace(/<br\s*\/?>/gi, "<br>");
    out = out.replace(/<small>/gi, '<span class="small">').replace(/<\/small>/gi, "</span>");

    return out;
  }

  function link(base, target, label) {
    var href = base + encodeURIComponent(target.trim().replace(/ /g, "_"));
    return '<a class="wl" href="' + href + '" target="_blank" rel="noopener noreferrer">' +
      label + "</a>";
  }

  /* Replace templates before the line pass, since they span lines and would otherwise be
   * read as list items and headings. Two survive because they are *content* rather than
   * layout; everything else is dropped, because a half-expanded template reads worse than
   * none.
   *
   * {{Quote}} becomes a blockquote. {{WPS|Page|Label}} is a Wikipedia shortcut and becomes
   * its label: it is 110 of the trunk page's 134 template calls (`seed-plan.md` §7), so
   * dropping it lost most of several sections — and because it is nearly always written
   * inside italics as ''{{WPS|Old Yeller}}'', dropping it also left the surrounding quote
   * markers with nothing between them, which then leaked into the output as stray
   * apostrophes. Found by rendering all 284 sections rather than the fixture's sample. */
  function stripTemplates(text) {
    var spans = findTemplates(text);
    var out = "";
    var cursor = 0;
    spans.forEach(function (span) {
      out += text.slice(cursor, span.start);
      var name = templateName(span.raw);
      var params = splitParams(span.raw.slice(2, -2));
      if (/^quote$/i.test(name)) {
        var body = (params[1] || "").trim();
        var who = (params[2] || "").trim();
        if (body) out += "\n\u0003" + body + (who ? "\u0004" + who : "") + "\n";
      } else if (/^wps$/i.test(name)) {
        out += ((params[2] || params[1] || "").trim());
      }
      cursor = span.end;
    });
    return out + text.slice(cursor);
  }

  function renderWikitext(text, opts) {
    var options = opts || {};
    var body = stripTemplates(text);
    var lines = body.split("\n");
    var html = [];
    var paragraph = [];
    var listStack = [];

    function flushParagraph() {
      if (!paragraph.length) return;
      html.push("<p>" + renderInline(paragraph.join(" "), options) + "</p>");
      paragraph = [];
    }
    function closeLists(toDepth) {
      while (listStack.length > toDepth) html.push(listStack.pop() === "#" ? "</ol>" : "</ul>");
    }

    lines.forEach(function (line) {
      var heading = /^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$/.exec(line);
      if (heading) {
        flushParagraph();
        closeLists(0);
        var level = Math.min(heading[1].length, 6);
        html.push("<h" + level + ">" + renderInline(heading[2], options) + "</h" + level + ">");
        return;
      }

      if (line.indexOf("\u0003") === 0) {
        flushParagraph();
        closeLists(0);
        var parts = line.slice(1).split("\u0004");
        html.push('<blockquote><p>' + renderInline(parts[0], options) + "</p>" +
          (parts[1] ? "<cite>" + renderInline(parts[1], options) + "</cite>" : "") +
          "</blockquote>");
        return;
      }

      var item = /^([*#]+)\s?(.*)$/.exec(line);
      if (item) {
        flushParagraph();
        var markers = item[1];
        while (listStack.length > markers.length) {
          html.push(listStack.pop() === "#" ? "</ol>" : "</ul>");
        }
        while (listStack.length < markers.length) {
          var kind = markers[listStack.length];
          html.push(kind === "#" ? "<ol>" : "<ul>");
          listStack.push(kind);
        }
        html.push("<li>" + renderInline(item[2], options) + "</li>");
        return;
      }

      closeLists(0);
      if (!line.trim()) { flushParagraph(); return; }
      paragraph.push(line.trim());
    });

    flushParagraph();
    closeLists(0);

    return html.join("\n")
      .split(MARK_OPEN).join('<mark class="claim-hit">')
      .split(MARK_CLOSE).join("</mark>");
  }

  /* Wrap a claim's anchor in sentinels the renderer converts to <mark> at the end. Done on
   * wikitext rather than HTML because the anchor stored in the ledger *is* wikitext — the
   * same string the write path will patch. */
  function markAnchor(text, anchor) {
    if (!anchor) return text;
    var at = text.indexOf(anchor);
    if (at === -1) return text;
    return text.slice(0, at) + MARK_OPEN + anchor + MARK_CLOSE + text.slice(at + anchor.length);
  }

  /* Which infobox row a claim sits in, or null if it is anchored in prose.
   *
   * Claims anchored inside the infobox cannot be highlighted by markAnchor: the infobox is a
   * template, and stripTemplates removes it before the prose pass. They are highlighted in
   * the rendered infobox instead, which needs the parameter name — `|movie = ...` -> "movie".
   */
  function infoboxKey(anchor) {
    var match = /^\|\s*([^=|]+?)\s*=/.exec(anchor || "");
    return match ? match[1] : null;
  }

  global.Wikitext = {
    render: renderWikitext,
    inline: renderInline,
    infobox: parseInfobox,
    infoboxKey: infoboxKey,
    markAnchor: markAnchor,
    escapeHtml: escapeHtml,
  };
})(window);
