/* ==========================================================================
   md.js — turn the model's Markdown into HTML, with no external library.

   WHY NOT marked.js
   -----------------
   A CDN <script> is a single point of failure during a defense demo on a
   laptop with no internet, and vendoring 40KB to format bold text and a
   two-column table is not a good trade. This handles exactly the subset
   openai/gpt-oss-120b actually produces:

       **bold**  *italic*  `code`  ### headings
       - bullets   1. numbered   | tables |   --- rules

   SAFETY
   ------
   The model's output is untrusted text. Every character is HTML-escaped
   FIRST, then formatting is applied to the escaped string, so a charter
   answer containing <script> renders as visible text rather than running.
   Link hrefs are restricted to http/https for the same reason.

   Exposes one global:  renderMarkdown(text) -> HTML string
   ========================================================================== */

(function (root) {
  "use strict";

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---- Inline spans -----------------------------------------------------
     Runs on already-escaped text. Code spans are extracted first and parked
     as placeholders so that a literal **asterisk** inside `code` is not
     mistaken for emphasis. */
  function inline(text) {
    var code = [];
    text = text.replace(/`([^`\n]+)`/g, function (_, c) {
      return "\u0000C" + (code.push(c) - 1) + "\u0000";
    });

    // Links, but only to real web schemes. &quot; appears because we escaped first.
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      function (_, label, href) {
        return '<a href="' + href + '" target="_blank" rel="noopener">' + label + "</a>";
      });

    // Two asterisks before one, or **bold** would be eaten as nested emphasis.
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // The underscore forms need word boundaries. Without them a sentence
    // mentioning two identifiers — use_fallback and __init__ — has its middle
    // swallowed as emphasis.
    text = text.replace(/(^|[\s(])__([^_\n]+)__(?=[\s.,;:!?)]|$)/g, "$1<strong>$2</strong>");
    text = text.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)/g, "$1<em>$2</em>");
    text = text.replace(/(^|[\s(])_([^_\n]+)_(?=[\s.,;:!?)]|$)/g, "$1<em>$2</em>");

    return text.replace(/\u0000C(\d+)\u0000/g, function (_, i) {
      return "<code>" + code[+i] + "</code>";
    });
  }

  function splitRow(line) {
    return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|")
               .map(function (c) { return c.trim(); });
  }

  var RE = {
    heading:  /^(#{1,6})\s+(.*)$/,
    bullet:   /^\s*[-*+]\s+(.*)$/,
    numbered: /^\s*(\d+)[.)]\s+(.*)$/,
    rule:     /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/,
    tableRow: /^\s*\|.*\|\s*$/,
    tableSep: /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/,
    fence:    /^\s*```/
  };

  function renderMarkdown(src) {
    var lines = escapeHtml(src).replace(/\r\n?/g, "\n").split("\n");
    var out = [];
    var i = 0;

    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) { i++; continue; }

      // Fenced code block
      if (RE.fence.test(line)) {
        var buf = [];
        i++;
        while (i < lines.length && !RE.fence.test(lines[i])) buf.push(lines[i++]);
        i++;
        out.push("<pre><code>" + buf.join("\n") + "</code></pre>");
        continue;
      }

      if (RE.rule.test(line)) { out.push("<hr>"); i++; continue; }

      var h = line.match(RE.heading);
      if (h) {
        // Clamped to h4-h6: these sit inside a chat bubble, so a model's "##"
        // must not outrank the page's own headings.
        var level = Math.min(6, 3 + h[1].length);
        out.push("<h" + level + ">" + inline(h[2].trim()) + "</h" + level + ">");
        i++;
        continue;
      }

      // Table: a pipe row followed by a |---|---| separator
      if (RE.tableRow.test(line) && i + 1 < lines.length && RE.tableSep.test(lines[i + 1])) {
        var head = splitRow(line);
        i += 2;
        var body = [];
        while (i < lines.length && RE.tableRow.test(lines[i])) body.push(splitRow(lines[i++]));

        var t = ["<table><thead><tr>"];
        head.forEach(function (c) { t.push("<th>" + inline(c) + "</th>"); });
        t.push("</tr></thead><tbody>");
        body.forEach(function (row) {
          t.push("<tr>");
          for (var c = 0; c < head.length; c++) {
            t.push("<td>" + inline(row[c] || "") + "</td>");
          }
          t.push("</tr>");
        });
        t.push("</tbody></table>");
        out.push(t.join(""));
        continue;
      }

      // Lists
      var isBullet = RE.bullet.test(line);
      var isNumber = RE.numbered.test(line);
      if (isBullet || isNumber) {
        var tag = isBullet ? "ul" : "ol";
        var re = isBullet ? RE.bullet : RE.numbered;
        var items = [];
        while (i < lines.length && re.test(lines[i])) {
          var m = lines[i].match(re);
          items.push("<li>" + inline((isBullet ? m[1] : m[2]).trim()) + "</li>");
          i++;
        }
        out.push("<" + tag + ">" + items.join("") + "</" + tag + ">");
        continue;
      }

      // Paragraph: consume until a blank line or the start of another block
      var para = [];
      while (i < lines.length && lines[i].trim() &&
             !RE.bullet.test(lines[i]) && !RE.numbered.test(lines[i]) &&
             !RE.heading.test(lines[i]) && !RE.rule.test(lines[i]) &&
             !RE.tableRow.test(lines[i]) && !RE.fence.test(lines[i])) {
        para.push(lines[i++]);
      }
      // Single newlines inside a paragraph become <br>: the model wraps
      // enumerated fees one per line without leaving a blank line between.
      out.push("<p>" + inline(para.join("\n")).replace(/\n/g, "<br>") + "</p>");
    }

    return out.join("");
  }

  root.renderMarkdown = renderMarkdown;
})(window);
