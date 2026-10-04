import os
import re

import frappe

from wlh_translate.scanner import scanner
from wlh_translate.utils import progress


# ============================================================
# Untranslated text audit
# ============================================================
#
# The scanner answers "which strings does the app already declare as
# translatable?". This answers the opposite, and harder, question: "which
# text will the app render that no translation can ever reach?".
#
# Only the cases that are known to be unreachable are reported, so the report
# stays a short list somebody can act on:
#
#   {{ 'Getting started' }}     a literal rendered by the template itself
#   :label="'Skip all'"         a literal handed to a component prop
#   <div>Stock Level</div>      plain text between tags
#   label="Save"                a prop filled with a plain string
#
# All of them bypass the translation table completely: the frontend renders
# them verbatim, whatever Translation says. That is exactly why the panel in
# the Helpdesk sidebar kept showing English. The fix is an upstream patch,
# which is what the patcher is for.

AUDIT_JOB = "audit_app"

# Text lives in templates, and templates live in single file components, but a
# good deal of it also sits in the modules beside them: a toast message, a
# dialog title, a chart label. Leaving those out made every React style app a
# blind spot, so the plain JavaScript and TypeScript files are read too.
AUDITED_SUFFIXES = (".vue", ".tsx", ".jsx", ".ts", ".js")

# Suffixes that always carry markup. A file with one of these is read with the
# markup patterns even when no tag was spotted by the cheap test below.
MARKUP_SUFFIXES = (".vue", ".tsx", ".jsx")

# Packages the scanner skips on purpose but that still ship rendered text. The
# shared UI kit is the important one: it renders whole panels of its own, and
# an app author cannot recompile it away. Only these are read when the caller
# asks for dependencies; the rest of node_modules is somebody else's source.
DEPENDENCY_NAMES = ("frappe-ui",)

# A report is a worklist, not an archive: past a few hundred rows nobody reads
# further, so the run stops collecting and says how much it left out.
MAX_FINDINGS = 500

# No hand written source line is this long. A file that has one is a bundle or
# a vendored minified library, and its strings are not the app's to translate.
MAX_LINE_LENGTH = 2000

# Test suites assert on strings instead of rendering them, and a fixture is
# full of made up names. Type declarations are written by a generator. None of
# them is a worklist somebody can act on.
IGNORED_AUDIT_DIRS = {
    "tests",
    "__tests__",
    "__mocks__",
    "e2e",
    "cypress",
    "stories",
}

IGNORED_AUDIT_MARKERS = (".test.", ".spec.", ".cy.", ".stories.", ".d.ts")

_TEMPLATE_END = re.compile(r"<script\b")
_TEMPLATE_START = re.compile(r"<template\b")

# Text sitting between two tags, e.g. <div>Stock Level</div>.
_TAG_TEXT = re.compile(r">([^<>{}]{2,200})<")

# A template expression: the contents of {{ ... }}.
_INTERPOLATION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)

# A bound attribute, e.g. :label="..." or v-if="...".
_BOUND_ATTRIBUTE = re.compile(r'[:@][a-zA-Z][a-zA-Z0-9-]*="([^"]*)"')

# Attributes whose value is shown to a reader. Frappe UI spells most props
# with one of these names, and the HTML ones carry tooltips and help text.
# Everything else - class, id, ref, doctype, format - is markup or an
# identifier, and reporting it would only add rows nobody can act on.
_TEXT_ATTRIBUTE = (
    r"(?:"
    r"label|title|heading|subheading|placeholder|tooltip|hint|help|"
    r"description|caption|summary|note|message|text|content|alt|"
    r"emptyMessage|emptyText|confirmText|submitText|okText|cancelText|"
    r"buttonLabel|sectionLabel"
    r")"
)

# A JSX attribute written with a plain string, e.g. label="Save". Vue spells a
# static attribute the same way, so this covers those as well. The name has to
# start where an attribute name starts - after a space, a tag or a brace - so
# that a bound one (:aria-label) and a slot name (#item-label) are left alone;
# the bound pattern above already looks through those.
_STRING_ATTRIBUTE = re.compile(
    r"(?<=[\s<{])" + _TEXT_ATTRIBUTE + r'="([^"]*)"',
    re.IGNORECASE,
)

# A JSX attribute written with braces, e.g. label={'Save'}. The expression
# inside is scanned for literals exactly like a {{ }} interpolation is.
_BRACED_ATTRIBUTE = re.compile(
    r"(?<=[\s<{])" + _TEXT_ATTRIBUTE + r"=\{\s*([^{}]*?)\s*\}",
    re.IGNORECASE,
)

# A bare string child inside braces, e.g. <div>{'Stock Level'}</div>.
_BRACED_CHILD = re.compile(r"\{\s*(" + scanner._STRING_LITERAL + r")\s*\}")

# A literal that fills one of the names a reader sees, written as an object key
# or an assignment rather than as an attribute: label: "Save". The names that
# carry text in markup carry it in a module too.
_KEYED_LITERAL = re.compile(
    r"(?<![\w.])" + _TEXT_ATTRIBUTE + r"\s*[:=]\s*(" + scanner._STRING_LITERAL + r")",
    re.DOTALL | re.IGNORECASE,
)

# The options of a select, which are the choices a reader picks from. The same
# key carries the DocType a Link field points at ("options: \"Company\""), so
# the shape of the value has to tell the two apart; that is done in _collect.
_KEYED_OPTIONS = re.compile(
    r"(?<![\w.])options\s*[:=]\s*(" + scanner._STRING_LITERAL + r")",
    re.DOTALL | re.IGNORECASE,
)

# A string literal in the source, delimiters included. Same pattern the
# scanner matches translation calls with, so the two agree on what a string
# is and the report cannot drift away from what gets scanned.
_LITERAL = re.compile(scanner._STRING_LITERAL, re.DOTALL)

# Characters that introduce a translation call. A literal is skipped when one
# of these sits directly in front of it. The bare "t" covers the short alias
# the frontends use (t("Save"), i18n.t("Save")); the word boundary is what
# keeps it from matching the tail of an ordinary call such as alert(.
_TRANSLATED_BEFORE = re.compile(
    r"(?:__|\b_|\b_lt|\bN_|\btrans(?:late)?|\bt)\(\s*$"
)

# Calls whose argument names something instead of saying it: an event, a
# route, a hook, a storage key, a date mask. None of them is read off the
# screen, and the frontends are full of them - emit('applyFilter'),
# frappe.ui.form.on("Item"), dayjs(date).format('DD MMM YYYY').
_NOT_TEXT_BEFORE = re.compile(
    r"(?:emit|dispatch|trigger|addEventListener|removeEventListener|"
    r"on|off|once|watch|require|querySelector|querySelectorAll|format|"
    r"getElementById|classList\.(?:add|remove|toggle)|"
    r"setItem|getItem|removeItem)\s*\(\s*$"
)

# How far back a literal is looked at for the two patterns above. The longest
# name either of them matches is a good deal shorter than this.
_LOOKBEHIND = 24

# Two words in a row, the shortest thing that reads as a sentence rather than
# as a key, a route or an event name.
_WORD_PAIR = re.compile(r"[A-Za-z]+\s+[A-Za-z]+")

# A plain lower case word, and a run of Chinese. Both mark prose: a name
# ("Sales Order", "DD MMM YYYY") carries neither, which is what separates the
# two in practice.
_LOWERCASE_WORD = re.compile(r"(?<![A-Za-z])[a-z]{3,}(?![A-Za-z])")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{4,}")

# A line break followed by indentation. Prose wrapped in a string is not
# indented; a template literal holding markup or code always is.
_INDENTED_LINE = re.compile(r"\n[ \t]+\S")

# A cheap test for markup in a plain module: a closing tag. Vue and JSX are
# the only things that spell </name>, so a .ts or .js file is read as markup
# only when it really contains JSX. An opening tag alone is not enough - a
# TypeScript generic such as ref<WhatsAppAccount> is written the same way.
_JSX_MARKUP = re.compile(r"</[A-Za-z][A-Za-z0-9_.]*>")

# A ${...} placeholder inside a JavaScript template literal.
_PLACEHOLDER = re.compile(r"\$\{[^{}]*\}")

# Every character a class list, a style value, an id template or a date format
# is written with. Deliberately broad: the goal is to recognise the shape of
# markup, not to validate it.
_MARKUP_CHARS = re.compile(r"^[a-z0-9_\-.:/\[\]()%*#&!?,+~\\$@=<>|;]+$")

_UPPERCASE = re.compile(r"[A-Z]")


def _looks_like_code(value):
    """
    Whether a literal reads as markup rather than as something a person sees.

    Class lists, style values and template ids are quoted inside templates
    exactly like labels are, and without this they bury the report in rows
    nobody can act on. The test leans on the one thing that separates the two
    in practice: text written for a reader carries a capital letter in these
    files, markup does not. So a value is only called markup when it has no
    upper case letter at all and every word is spelled with the characters a
    class or a style is written in.
    """
    # A placeholder carries no text of its own, so what surrounds it is what a
    # reader would see: "comment-${name}" leaves "comment-".
    plain = _PLACEHOLDER.sub(" ", value)

    tokens = plain.split()

    if not tokens:
        return True

    if _UPPERCASE.search(plain):
        return False

    return all(_MARKUP_CHARS.match(token) for token in tokens)


def _looks_like_sentence(value):
    """
    Whether a literal in a plain module reads as a sentence.

    A module is full of short strings that are never shown - doctype names,
    date masks, event names - and reporting all of them would bury the rows
    that matter. Prose is at least two words long and carries a plain lower
    case word or a run of Chinese, so the names and masks are what gets left
    out rather than the text.
    """
    if _CJK_RUN.search(value):
        return True

    if not _WORD_PAIR.search(value):
        return False

    return bool(_LOWERCASE_WORD.search(value))


def _looks_generated(source):
    """Whether a file is a bundle rather than somebody's source."""
    return any(len(line) > MAX_LINE_LENGTH for line in source.splitlines())


def _template_of(source):
    """Return the <template> block of a Vue file, or the whole source."""
    start = _TEMPLATE_START.search(source)

    if not start:
        return source, 0

    end = _TEMPLATE_END.search(source, start.end())

    if not end:
        return source[start.end():], start.end()

    return source[start.end():end.start()], start.end()


def _is_markup(path, source):
    """Whether a file should be read with the markup patterns."""
    if path.endswith(MARKUP_SUFFIXES):
        return True

    return bool(_JSX_MARKUP.search(source))


def _line_of(source, offset):
    return source.count("\n", 0, offset) + 1


def _skip(source, offset):
    """
    Whether the literal at this offset is already handled or is not text.

    A literal is skipped when it is the argument of a translation call, and
    when it is the argument of a call that names something rather than says
    it. Both are read from the source in front of the literal.
    """
    before = source[max(0, offset - _LOOKBEHIND):offset]

    if _TRANSLATED_BEFORE.search(before):
        return True

    return bool(_NOT_TEXT_BEFORE.search(before))


def _collect(source, block, block_offset, markup=True):
    """
    Return (offset, text) for every unreachable piece of text in a block.

    With markup set the block is read as a template or as JSX, which is where
    the renderable text sits. Without it the block is an ordinary module and
    only literals that read as a sentence are kept, because everything else
    there is a key, a route or an event name rather than something a person
    reads on screen. Only text is returned; the caller turns offsets into
    line numbers.
    """
    found = []
    seen = set()

    def add(offset, value):
        value = value.strip()

        if not value or offset in seen:
            return

        if _INDENTED_LINE.search(value):
            # A literal broken across indented lines is a markup or code
            # template, never a label; real markup is caught by the tag
            # patterns above, which read it as tags rather than as one string.
            return

        if '"' in value or "`" in value:
            # Text between tags that carries a quote is a piece of a string
            # concatenation that builds markup: ">" + value + "<".
            return

        if not scanner.has_human_text(value):
            return

        if _looks_like_code(value):
            return

        seen.add(offset)
        found.append((offset, value))

    def add_expression(expression, base):
        """Add the literals inside an expression that are not translated."""
        for literal in _LITERAL.finditer(expression):
            offset = base + literal.start()

            if _skip(source, offset):
                continue

            add(offset, scanner.unescape_literal(literal.group(0)))

    def add_keyed(pattern):
        """Add the literal each match of a key pattern holds."""
        for match in pattern.finditer(block):
            offset = block_offset + match.start(1)

            if _skip(source, offset):
                continue

            add(offset, scanner.unescape_literal(match.group(1)))

    if not markup:
        # A literal that fills a name a reader sees is text whatever its
        # shape, so it is taken first and is not put through the prose test.
        add_keyed(_KEYED_LITERAL)

        # A select's choices are newline separated. A single value under the
        # same key is the DocType a Link field points at, not a choice.
        for match in _KEYED_OPTIONS.finditer(block):
            literal = match.group(1)

            if "\n" not in literal and "\\n" not in literal:
                continue

            offset = block_offset + match.start(1)

            if _skip(source, offset):
                continue

            add(offset, scanner.unescape_literal(literal))

        for literal in _LITERAL.finditer(block):
            offset = block_offset + literal.start()

            if _skip(source, offset):
                continue

            value = scanner.unescape_literal(literal.group(0))

            if _looks_like_sentence(value):
                add(offset, value)

        return found

    # Plain text between tags is rendered as is and can never be translated.
    for match in _TAG_TEXT.finditer(block):
        add(block_offset + match.start(1), match.group(1))

    # A literal inside {{ }}, inside a bound attribute or inside a braced JSX
    # attribute is only fine when it is the argument of a translation call.
    for pattern in (_INTERPOLATION, _BOUND_ATTRIBUTE, _BRACED_ATTRIBUTE):
        for match in pattern.finditer(block):
            add_expression(match.group(1), block_offset + match.start(1))

    # A plain string handed to an attribute, and a bare string child.
    for match in _STRING_ATTRIBUTE.finditer(block):
        add(block_offset + match.start(1), match.group(1))

    for match in _BRACED_CHILD.finditer(block):
        offset = block_offset + match.start(1)

        if _skip(source, offset):
            continue

        add(offset, scanner.unescape_literal(match.group(1)))

    return found


def _is_audited(filename):
    """Whether a file is source the audit should read."""
    if not filename.endswith(AUDITED_SUFFIXES):
        return False

    return not any(marker in filename for marker in IGNORED_AUDIT_MARKERS)


def _dependency_dirs(root):
    """
    Yield every copy of a dependency that ships rendered text.

    A package manager may place node_modules at the app root or beside the
    frontend, so the tree is searched rather than a fixed path joined. The
    walk stops at each node_modules: nothing below it belongs to the app.
    """
    for directory, dirnames, _ in os.walk(root):
        if os.path.basename(directory) == "node_modules":
            dirnames[:] = []

            for name in DEPENDENCY_NAMES:
                candidate = os.path.join(directory, name)

                if os.path.isdir(candidate):
                    yield candidate

            continue

        dirnames[:] = [
            name
            for name in dirnames
            if name not in scanner.IGNORED_DIRS or name == "node_modules"
        ]


def _candidate_files(app_name, include_dependencies):
    """Every source file the audit should read for one app."""
    root = os.path.dirname(frappe.get_app_path(app_name))

    files = []

    # node_modules is left out of the app's own walk on purpose: a package
    # carries thousands of modules that the app does not own, and reading them
    # buries the report. The few that ship rendered text are added below.
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in scanner.IGNORED_DIRS
            and name not in IGNORED_AUDIT_DIRS
        ]

        for filename in sorted(filenames):
            if _is_audited(filename):
                files.append(os.path.join(directory, filename))

    if include_dependencies:
        for dependency_root in _dependency_dirs(root):
            for directory, _, filenames in os.walk(dependency_root):
                for filename in sorted(filenames):
                    if _is_audited(filename):
                        files.append(os.path.join(directory, filename))

    return files


def audit_app(app_name, include_dependencies=False):
    """
    Report the text an app renders but cannot translate.

    Runs on the long queue: reading a whole tree, and especially the shared
    UI kit, takes far longer than a request may live. Progress is published
    under the job id the list view polls.
    """
    root = os.path.dirname(frappe.get_app_path(app_name))
    files = _candidate_files(app_name, include_dependencies)

    findings = []
    truncated = False
    total = 0
    scanned = 0

    # Drop any progress left behind by an earlier run before the first file
    # is read, so the status bar cannot show a stale percentage.
    progress.clear(AUDIT_JOB)

    try:
        for path in files:
            scanned += 1

            progress.report(AUDIT_JOB, scanned, len(files), app_name=app_name)

            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
            except OSError:
                continue

            if _looks_generated(source):
                continue

            if path.endswith(".vue"):
                block, offset = _template_of(source)
            else:
                # A module has no <template> block; the whole file is the
                # block, and only the sentence-like literals in it are kept.
                block, offset = source, 0

            markup = _is_markup(path, source)

            for position, text in _collect(source, block, offset, markup):
                total += 1

                if len(findings) >= MAX_FINDINGS:
                    truncated = True
                    continue

                findings.append(
                    {
                        "file": os.path.relpath(path, root),
                        "line": _line_of(source, position),
                        "text": text,
                    }
                )
    finally:
        progress.clear(AUDIT_JOB)

    return {
        "app_name": app_name,
        "files": scanned,
        "findings": findings,
        "total": total,
        "truncated": truncated,
    }