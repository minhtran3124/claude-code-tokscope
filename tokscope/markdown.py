"""A small Markdown renderer for reading SKILL.md files: headings, paragraphs, lists, fenced code, tables, quotes,
rules, and inline code, bold, italic and links. Every piece of text is escaped first, so raw HTML in a file shows as
text; a link keeps only http(s), mailto and #anchors, and `link(href)` maps a relative one (another file of the skill)."""

import html
import itertools
import re

FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)")
BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
SAFE = re.compile(r"^(https?:|mailto:|#)", re.IGNORECASE)


def frontmatter(text):
    """(dict of the YAML-ish header, the rest). Folded and literal values (`key: >`) join their indented lines."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head, rest = text[3:end], text[end + 4:].lstrip("\n")
    meta, key = {}, None
    for line in head.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            key, value = m.group(1), m.group(2).strip()
            meta[key] = "" if value in (">", "|", ">-", "|-", ">+", "|+") else value.strip("'\"")
        elif key and line.strip():
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, rest


def _inline(text, link):
    # code spans become placeholders first, so bold or a link may wrap them ("**Write `x` here**")
    codes = []

    def hold(m):
        codes.append(f"<code>{html.escape(m.group(0).strip('`').strip())}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = html.escape(re.sub(r"`+[^`]*?`+", hold, text))

    def anchor(m):
        label, href = m.group(1), html.unescape(m.group(2))
        url = href if SAFE.match(href) else (link(href) if link and not re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I) else None)
        return f'<a href="{html.escape(url)}">{label}</a>' if url else label

    s = LINK.sub(anchor, s)
    s = BOLD.sub(r"<strong>\1</strong>", s)
    s = ITALIC.sub(r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def inline(text):
    """One line of Markdown (a skill's description) as HTML: code, bold, italic; links keep their text only."""
    return _inline(text, lambda _: None)


def _code(lines, lang=""):
    cls = f' class="lang-{html.escape(lang)}"' if lang else ""
    return f"<pre><code{cls}>{html.escape(chr(10).join(lines))}</code></pre>"


def _cells(line):
    line = line.strip().replace("\\|", "\0")
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line
    return [c.strip().replace("\0", "|") for c in line.split("|")]


def _table(rows, link):
    head, body = _cells(rows[0]), [_cells(r) for r in rows[2:]]
    th = "".join(f"<th>{_inline(c, link)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c, link)}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def _fenced(lines, i):
    """(code lines, language, index after the closing fence) for the fence that opens at lines[i]."""
    m = FENCE.match(lines[i])
    mark, lang, body, i = m.group(1), m.group(2).strip().split(" ")[0], [], i + 1
    indent = len(lines[i - 1]) - len(lines[i - 1].lstrip())
    while i < len(lines) and not lines[i].strip().startswith(mark):
        body.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i].lstrip())
        i += 1
    return body, lang, i + 1


def _list(lines, i, link):
    """(HTML, next index) for the list that starts at lines[i]; nesting follows the indent of each marker."""
    root, stack, last = [], [], None
    stack.append((-1, root))
    while i < len(lines):
        line = lines[i]
        m = ITEM.match(line)
        if m:
            indent = len(m.group(1))
            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()
            last = {"ordered": m.group(2)[0].isdigit(), "text": [m.group(3)], "blocks": [], "kids": []}
            stack[-1][1].append(last)
            stack.append((indent, last["kids"]))
            i += 1
        elif not line.strip():
            nxt = next((ln for ln in lines[i + 1:] if ln.strip()), "")
            if not (ITEM.match(nxt) or nxt.startswith((" ", "\t"))):
                break
            i += 1
        elif line.startswith((" ", "\t")) and last:
            if FENCE.match(line):
                body, lang, i = _fenced(lines, i)
                last["blocks"].append(_code(body, lang))
            else:
                (last["blocks"].append(f"<p>{_inline(line.strip(), link)}</p>") if last["blocks"] or last["kids"]
                 else last["text"].append(line.strip()))
                i += 1
        else:
            break

    def emit(items):
        out = []
        for ordered, group in itertools.groupby(items, key=lambda it: it["ordered"]):
            tag = "ol" if ordered else "ul"
            lis = "".join(f"<li>{_inline(' '.join(it['text']), link)}{''.join(it['blocks'])}{emit(it['kids'])}</li>" for it in group)
            out.append(f"<{tag}>{lis}</{tag}>")
        return "".join(out)

    return emit(root), i


def render(text, link=None):
    lines, out, para, i = text.replace("\r\n", "\n").split("\n"), [], [], 0

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para), link)}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            flush()
            body, lang, i = _fenced(lines, i)
            out.append(_code(body, lang))
        elif m := HEADING.match(line):
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2), link)}</h{level}>")
            i += 1
        elif RULE.match(line):
            flush()
            out.append("<hr>")
            i += 1
        elif "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            flush()
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                j += 1
            out.append(_table(lines[i:j], link))
            i = j
        elif line.lstrip().startswith(">"):
            flush()
            j = i
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                j += 1
            quoted = [re.sub(r"^\s*>\s?", "", ln) for ln in lines[i:j]]
            out.append(f"<blockquote>{render(chr(10).join(quoted), link)}</blockquote>")
            i = j
        elif ITEM.match(line):  # a list may start right under a paragraph line ("Steps:" then "1. ...")
            flush()
            html_, i = _list(lines, i, link)
            out.append(html_)
        elif not line.strip():
            flush()
            i += 1
        else:
            para.append(line.strip())
            i += 1
    flush()
    return "".join(out)
