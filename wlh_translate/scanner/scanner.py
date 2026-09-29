import csv
import hashlib
import html
import json
import os
import re

import frappe
from frappe.utils import strip_html

from wlh_translate.importer.po_importer import _apply_updates, iter_catalogue
from wlh_translate.utils.language import DEFAULT_LANGUAGE


# ============================================================
# WLH Translate Resource Scanner V2
# ============================================================

MAX_TEXT_LENGTH = 5000

# Translation Entry.context is a Frappe Data field, which the framework
# limits to 140 characters.
MAX_CONTEXT_LENGTH = 140

# Batch size for the bulk SQL helpers.
BULK_CHUNK_SIZE = 500

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
}

IGNORED_FILE_SUFFIXES = (
    ".bak",
    ".backup",
    ".pyc",
    ".pyo",
)

# App fixtures that only exist for the test runner (test_records.json,
# test_data_*.json). Their strings never reach the UI.
IGNORED_JSON_FILE_PREFIXES = ("test_",)

# Setup wizard seed files describing country specific fixtures - tax
# templates and charts of accounts - instead of user-facing text.
IGNORED_SETUP_WIZARD_FILES = {"country_wise_tax.json"}

# Setup wizard keys holding codes, abbreviations or conversion factors
# rather than a label ("m", "0.006993s").
IGNORED_SETUP_WIZARD_KEYS = {
    "value",
    "abbr",
    "symbol",
    "common_code",
    "must_be_whole_number",
}

SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JS",
    ".html": "HTML",
    ".htm": "HTML",
    ".jinja": "HTML",
    ".jinja2": "HTML",
}


# ============================================================
# JSON fields that may contain user-facing translation resources
# ============================================================

JSON_TEXT_FIELDS = {
    "label",
    "description",
    "title",
    "placeholder",
    "help",
    "tooltip",
    "intro",
    "message",
    "button_label",
    "section_label",
    "description_html",
}

# These are only considered when the value looks like actual
# human-readable Select options rather than HTML/code/configuration.
JSON_OPTION_FIELDS = {
    "options",
}


# ============================================================
# Translation call patterns
# ============================================================

# A complete source string literal, delimiters included.
#
# The old patterns stopped at the first quote character, so a string such as
# _("<div class=\"columnHeading\">Other Details</div>") was cut down to
# "<div class=" and then discarded as HTML without text. Matching the whole
# literal lets the escape sequences be resolved afterwards. Backticks cover
# JavaScript template literals, which Frappe also translates.
_STRING_LITERAL = (
    r'"(?:[^"\\]|\\.)*"'
    r"|'(?:[^'\\]|\\.)*'"
    r"|`(?:[^`\\]|\\.)*`"
)

TRANSLATION_PATTERNS = [
    re.compile(
        rf"__\(\s*({_STRING_LITERAL})",
        re.DOTALL,
    ),
    re.compile(
        rf"frappe\._\(\s*({_STRING_LITERAL})",
        re.DOTALL,
    ),
    re.compile(
        rf"(?<![\w.])_\(\s*({_STRING_LITERAL})",
        re.DOTALL,
    ),
]


# Escape sequences that mean the same thing in Python source and in
# JavaScript. Anything else keeps its backslash, matching both languages.
_ESCAPE_MAP = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "`": "`",
    "/": "/",
}


def unescape_literal(literal):
    """
    Resolve a source string literal into the value Frappe compares against.

    The translation key must be byte-for-byte what the running code passes to
    _(), so the escapes have to be resolved before the text is stored:
    _("<div class=\\"x\\">y</div>") looks up <div class="x">y</div>, not the
    literal with backslashes in it.

    HTML entities are deliberately left alone: the msgids shipped in
    <app>/<app>/locale/<lang>.po keep them verbatim.
    """
    if not literal or len(literal) < 2:
        return ""

    body = literal[1:-1]

    out = []
    index = 0
    length = len(body)

    while index < length:
        char = body[index]

        if char != "\\" or index + 1 >= length:
            out.append(char)
            index += 1
            continue

        nxt = body[index + 1]

        if nxt in _ESCAPE_MAP:
            out.append(_ESCAPE_MAP[nxt])
            index += 2
            continue

        # \uXXXX / \xXX are resolved so numeric escapes cannot leak a
        # different key than the one the runtime compares.
        if nxt == "u" and index + 6 <= length:
            try:
                out.append(chr(int(body[index + 2:index + 6], 16)))
                index += 6
                continue
            except ValueError:
                pass

        if nxt == "x" and index + 4 <= length:
            try:
                out.append(chr(int(body[index + 2:index + 4], 16)))
                index += 4
                continue
            except ValueError:
                pass

        out.append("\\")
        out.append(nxt)
        index += 2

    return "".join(out)


# ============================================================
# Helpers
# ============================================================

def source_key(value):
    """
    Return the exact string Frappe compares against at runtime.

    frappe.utils.translations._() only strips the message. Escape sequences
    are already resolved by the time a value reaches here: source files go
    through unescape_literal(), JSON and CSV values are decoded by their
    readers. Turning "\\n" into a newline here again would corrupt a source
    string that legitimately contains a backslash.

    HTML entities are deliberately preserved: the msgids shipped in
    <app>/<app>/locale/<lang>.po keep them verbatim (for example
    "&lt;head&gt; HTML"), so an unescaped source text could never match.
    """
    if not isinstance(value, str):
        return ""

    return value.strip()


def make_context(context):
    """
    Keep a resource context inside the 140-character Data column.

    A nested JSON path such as country-wise tax templates easily exceeds the
    column width; Frappe truncates the value and then rejects the row, so the
    resource would be silently dropped. The overflow is replaced by a short
    hash of the full context, keeping two different paths distinct.
    """
    context = context or ""

    if len(context) <= MAX_CONTEXT_LENGTH:
        return context

    digest = hashlib.sha1(context.encode("utf-8")).hexdigest()[:16]

    keep = MAX_CONTEXT_LENGTH - len(digest) - 1

    return f"{context[:keep]}:{digest}"


def clean_text(value):
    """
    Normalize a candidate translation resource for the visibility filter.

    This is only used to decide whether a value is worth translating, so
    HTML entities are decoded here to reveal the text they carry. The stored
    key must come from source_key(), never from this function.

    Reject:
    - None
    - empty strings
    - excessively long strings
    - HTML with no human-readable text
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        return ""

    value = html.unescape(value)
    value = value.replace("\\n", "\n").strip()

    if not value:
        return ""

    if len(value) > MAX_TEXT_LENGTH:
        return ""

    return value


# Strings that survive the HTML strip but carry nothing a translator can
# act on. They are read out of source files as labels, options or field
# names and would otherwise pile up in the worklist forever.
TECHNICAL_STRING_PATTERNS = (
    # Icon class names: "fa fa-money", "fa-file-text-o"
    re.compile(r"^fa[srb]?\s+fa-[a-z0-9-]+$"),
    re.compile(r"^fa-[a-z0-9-]+$"),
    # Identifiers: "reference_doctype", "party_type", "desk.page"
    re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$"),
)


def looks_like_technical_string(value):
    """
    Decide whether a value is a technical token rather than prose.

    Examples rejected:
        fa fa-money
        reference_doctype
        2
        ----
    """
    value = (value or "").strip()

    if not value:
        return True

    # Nothing readable at all: pure digits, punctuation, symbols. CJK is
    # kept so a Chinese source string is never mistaken for a symbol run.
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", value):
        return True

    return any(pattern.match(value) for pattern in TECHNICAL_STRING_PATTERNS)


def has_human_text(value):
    """
    Determine whether a value contains actual human-readable content.

    Examples rejected:
        <div></div>
        <div id="stock-levels-placeholder"></div>
        <span class="foo"></span>
        fa fa-money
        reference_doctype

    Examples accepted:
        <div>Stock Level</div>
        Stock Level
        Draft
    """
    value = clean_text(value)

    if not value:
        return False

    text = strip_html(value).strip()

    if text:
        return not looks_like_technical_string(text)

    # An image can still be meaningful HTML, but a bare structural
    # placeholder should not become a translation resource.
    if "<img" in value.lower():
        return True

    return False


def looks_like_html(value):
    value = value or ""
    return bool(re.search(r"<[a-zA-Z][^>]*>", value))


def looks_like_code_or_config(value):
    """
    Conservative filter for JSON options/configuration values.

    We don't want HTML, JavaScript, URLs, CSS selectors, or large
    configuration fragments entering the translation table.
    """
    value = value.strip()

    if not value:
        return True

    if looks_like_html(value):
        return True

    if value.startswith(("/", "./", "../")):
        return True

    if value.startswith(("http://", "https://", "mailto:")):
        return True

    # Common technical/configuration patterns.
    if re.search(r"[{};]\s*$", value):
        return True

    if re.search(r"^[.#]?[A-Za-z0-9_-]+\s*[:=]", value):
        return True

    return False


def is_translatable_json_option(value):
    """
    Decide whether a JSON 'options' value is suitable as a translation
    resource.

    Select options often use newline-separated human-readable values.
    HTML placeholders and configuration values are rejected.
    """
    value = clean_text(value)

    if not value:
        return False

    if looks_like_html(value):
        return False

    if looks_like_code_or_config(value):
        return False

    # Reject obviously technical values.
    if re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
        # Keep short natural words such as Draft / Submitted / Cancelled.
        if " " not in value and len(value) > 40:
            return False

    return has_human_text(value)


def make_hash(app, source_type, text, context=""):
    """
    Stable content hash.

    This identifies the exact source content.
    """
    raw = "\x1f".join(
        [
            app or "",
            source_type or "",
            context or "",
            text or "",
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def make_resource_key(
    app,
    source_type,
    path,
    line_number=None,
    context="",
):
    """
    Stable location/resource identity used by the incremental scanner.

    Unlike hash_key, source text is deliberately excluded.

    This allows the scanner to distinguish:

        same resource + same text    -> Unchanged
        same resource + new text     -> Changed
        previously unseen resource  -> New
    """
    try:
        app_path = frappe.get_app_path(app)
        relative_path = os.path.relpath(path, app_path)
    except Exception:
        relative_path = path or ""

    raw = "\x1f".join(
        [
            app or "",
            source_type or "",
            relative_path or "",
            str(line_number or ""),
            context or "",
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def get_module_name(app, filepath):
    """
    Best-effort module detection from the app path.
    """
    try:
        app_path = frappe.get_app_path(app)
    except Exception:
        return ""

    try:
        relative = os.path.relpath(filepath, app_path)
    except Exception:
        return ""

    parts = relative.split(os.sep)

    ignored = {
        "doctype",
        "report",
        "page",
        "workspace",
        "dashboard",
        "www",
        "templates",
        "public",
        "translations",
    }

    for part in parts[:-1]:
        if part and part not in ignored:
            return part

    return ""


def get_existing_entry(hash_key):
    """
    Return the existing Translation Entry name if present.
    """
    return frappe.db.exists(
        "Translation Entry",
        {"hash_key": hash_key},
    )


def get_existing_resource(resource_key):
    """
    Return the existing Translation Entry name for a resource identity.
    """
    if not resource_key:
        return None

    return frappe.db.exists(
        "Translation Entry",
        {"resource_key": resource_key},
    )


def backfill_resource_keys():
    """
    One-time migration helper.

    Populate resource_key for existing Translation Entry records created
    before the incremental Diff engine was introduced.

    Existing translation data and change status are preserved.
    """
    print("=" * 70)
    print("WLH Translate: Backfill Resource Keys")
    print("=" * 70)

    rows = frappe.get_all(
        "Translation Entry",
        fields=[
            "name",
            "app_name",
            "source_type",
            "source_path",
            "line_number",
            "context",
            "resource_key",
        ],
        order_by="name",
    )

    total = len(rows)
    updated = 0
    skipped = 0
    errors = 0

    print(f"Existing Translation Entry records: {total}")

    for index, row in enumerate(rows, start=1):

        if row.resource_key:
            skipped += 1
            continue

        try:
            resource_key = make_resource_key(
                app=row.app_name,
                source_type=row.source_type,
                path=row.source_path or "",
                line_number=row.line_number,
                context=row.context or "",
            )

            frappe.db.set_value(
                "Translation Entry",
                row.name,
                "resource_key",
                resource_key,
                update_modified=False,
            )

            updated += 1

        except Exception as exc:
            errors += 1
            print(
                f"[ERROR] {row.name}: "
                f"{type(exc).__name__}: {exc}"
            )

        if index % 500 == 0:
            frappe.db.commit()
            print(
                f"  Progress: {index}/{total} "
                f"(updated={updated}, errors={errors})"
            )

    frappe.db.commit()

    print("=" * 70)
    print(f"Total   : {total}")
    print(f"Updated : {updated}")
    print(f"Skipped : {skipped}")
    print(f"Errors  : {errors}")
    print("=" * 70)

    return {
        "total": total,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


# ============================================================
# Save resource
# ============================================================

def save_entry(
    app,
    source_type,
    path,
    text,
    line_number=None,
    context="",
    translated_text="",
    translation_source="Manual",
    status="Pending",
):
    """
    Save one translation resource.

    Existing entries are NEVER overwritten.

    Returns:
        True  -> newly created
        False -> skipped/existing/invalid
    """
    # Store the runtime-exact string. clean_text() is only applied through
    # has_human_text() below, which must never leak its unescaped form into
    # the source text that Frappe later looks up.
    text = source_key(text)

    if not text:
        return False

    if not has_human_text(text):
        return False

    hash_key = make_hash(
        app=app,
        source_type=source_type,
        text=text,
        context=context,
    )

    resource_key = make_resource_key(
        app=app,
        source_type=source_type,
        path=path,
        line_number=line_number,
        context=context,
    )

    existing_name = get_existing_resource(resource_key)

    if existing_name:
        existing = frappe.get_doc(
            "Translation Entry",
            existing_name,
        )

        old_hash = existing.hash_key or ""

        if old_hash == hash_key:
            existing.last_seen = frappe.utils.now_datetime()
            existing.change_status = "Unchanged"

            if not existing.first_seen:
                existing.first_seen = frappe.utils.now_datetime()

            existing.save(ignore_permissions=True)
            return False

        # Same resource identity, but source content changed.
        #
        # Preserve the existing translation. The source text is updated,
        # while the change is explicitly marked for human review.
        existing.source_text = text
        existing.hash_key = hash_key
        existing.source_path = path
        existing.line_number = line_number
        existing.last_seen = frappe.utils.now_datetime()
        existing.change_status = "Changed"

        existing.save(ignore_permissions=True)
        return False

    # No resource identity exists. This is a genuinely new resource.
    values = {
        "doctype": "Translation Entry",
        "source_text": text,
        "translated_text": translated_text or "",
        "language": DEFAULT_LANGUAGE,
        "app_name": app,
        "module_name": get_module_name(app, path),
        "source_type": source_type,
        "source_path": path,
        "line_number": line_number,
        "context": context,
        "translation_source": translation_source,
        "status": status,
        "hash_key": hash_key,
        "resource_key": resource_key,
        "first_seen": frappe.utils.now_datetime(),
        "last_seen": frappe.utils.now_datetime(),
        "change_status": "New",
        "is_translatable": 1,
        "ignore_reason": "",
    }

    savepoint_name = "wlh_translate_resource"

    try:
        # Protect the current resource with a savepoint.
        #
        # A resource-level failure must not roll back resources that
        # were already processed successfully during this scan.
        frappe.db.savepoint(savepoint_name)

        doc = frappe.get_doc(values)

        # Frappe considers HTML containing no visible text to be empty
        # for mandatory fields. We already filter those above.
        doc.insert(
            ignore_permissions=True,
        )

        return True

    except Exception as exc:
        print("")
        print("  [RESOURCE ERROR]")
        print(f"    app         : {app!r}")
        print(f"    source_type : {source_type!r}")
        print(f"    path        : {path!r}")
        print(f"    line        : {line_number!r}")
        print(f"    context     : {context!r}")
        print(f"    text        : {text!r}")
        print(f"    error       : {type(exc).__name__}: {exc}")
        print("    resource failed; scan will be marked incomplete")
        print("")

        # Roll back only this resource.
        try:
            frappe.db.rollback(save_point=savepoint_name)
        except Exception:
            pass

        # IMPORTANT:
        # Do not swallow the exception.
        #
        # scan_app() must see this failure so that it can:
        #   1. increment its error counter
        #   2. report an incomplete scan
        #   3. skip Suspected Deleted detection
        raise


# ============================================================
# JSON scanner
# ============================================================

def scan_json(app, filepath):
    """
    Scan JSON metadata.

    JSON resources use semantic identity where possible.

    Examples:
        json:fields[fieldname=customer].label
        json:fields[fieldname=customer].description
        json:fields[fieldname=customer].options:1
    """
    try:
        with open(
            filepath,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0

    count = 0

    def list_identity(item, index):
        if isinstance(item, dict):
            for key in ("fieldname", "name", "id", "route", "key"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return f"{key}={value.strip()}"

        return str(index)

    def walk(obj, json_path="json"):
        nonlocal count

        if isinstance(obj, dict):
            for key, value in obj.items():

                current_path = f"{json_path}.{key}"

                if key in JSON_TEXT_FIELDS:
                    if isinstance(value, str) and has_human_text(value):
                        if save_entry(
                            app=app,
                            source_type="Label",
                            path=filepath,
                            text=value,
                            context=make_context(current_path),
                        ):
                            count += 1

                elif key in JSON_OPTION_FIELDS:
                    if isinstance(value, str):
                        if is_translatable_json_option(value):
                            option_lines = [
                                line.strip()
                                for line in value.splitlines()
                                if line.strip()
                            ]

                            for option_index, option in enumerate(
                                option_lines,
                                start=1,
                            ):
                                if not is_translatable_json_option(option):
                                    continue

                                option_context = (
                                    f"{current_path}:{option_index}"
                                )

                                if save_entry(
                                    app=app,
                                    source_type="Message",
                                    path=filepath,
                                    text=option,
                                    context=make_context(option_context),
                                ):
                                    count += 1

                walk(value, current_path)

        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                identity = list_identity(item, index)

                if identity == str(index):
                    item_path = f"{json_path}[{index}]"
                else:
                    item_path = f"{json_path}[{identity}]"

                walk(item, item_path)

    walk(data)

    return count


def is_setup_wizard_data(path):
    """
    True for the setup wizard seed data directory.

    Values such as uom_name ("Cubic Yard") or an industry ("Technology") are
    plain JSON values that the metadata scanner ignores, yet the setup wizard
    and the records it creates display them.
    """
    parts = (path or "").split(os.sep)

    return "setup_wizard" in parts and "data" in parts


def scan_setup_wizard_data(app, filepath):
    """
    Scan the human-facing string values of a setup wizard seed data file.

    Scoped to setup_wizard/data on purpose: reading string values everywhere
    would drag structural identifiers into the worklist. Country specific
    fixtures and numeric keys are skipped for the same reason.
    """
    if os.path.basename(filepath) in IGNORED_SETUP_WIZARD_FILES:
        return 0

    try:
        with open(
            filepath,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0

    count = 0

    def walk(obj, json_path="json"):
        nonlocal count

        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in IGNORED_SETUP_WIZARD_KEYS:
                    continue

                current_path = f"{json_path}.{key}"

                if isinstance(value, str) and has_human_text(value):
                    if save_entry(
                        app=app,
                        source_type="Message",
                        path=filepath,
                        text=value,
                        context=make_context(f"setup_wizard:{current_path}"),
                    ):
                        count += 1

                walk(value, current_path)

        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                walk(item, f"{json_path}[{index}]")

    walk(data)

    return count


def scan_translation_csv(app, filepath):
    """
    Read existing Frappe translation CSV resources.

    We only import the source text and existing translation.
    Existing Translation Entry records are never overwritten.
    """
    count = 0

    try:
        with open(
            filepath,
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            reader = csv.reader(f)

            for line_number, row in enumerate(reader, start=1):
                if not row:
                    continue

                source_text = (
                    row[0].strip()
                    if len(row) >= 1
                    else ""
                )

                translated_text = (
                    row[1].strip()
                    if len(row) >= 2
                    else ""
                )

                if not has_human_text(source_text):
                    continue

                if save_entry(
                    app=app,
                    source_type="Message",
                    path=filepath,
                    text=source_text,
                    line_number=line_number,
                    context="translation_csv",
                    translated_text=translated_text,
                    translation_source=(
                        "Imported"
                        if translated_text
                        else "Manual"
                    ),
                    status=(
                        "Translated"
                        if translated_text
                        else "Pending"
                    ),
                ):
                    count += 1

    except (OSError, UnicodeDecodeError):
        pass

    return count


# ============================================================
# App catalogue (.po) reconciliation
# ============================================================

def scan_catalogue(app, language=DEFAULT_LANGUAGE):
    """
    Reconcile one app against the msgid catalogue it ships.

    <app>/<app>/locale/<lang>.po is the list Frappe generates from its own
    source tree, so it holds strings the pattern scanner cannot recover
    (report and doctype names, template literals, strings with escaped
    quotes) as well as the msgids the official catalogue itself still leaves
    untranslated. Reaching the catalogue is what makes the worklist complete.

    Translations the app already ships are imported; human work is never
    overwritten.

    Args:
        app: installed app name
        language: catalogued language code

    Returns a summary dict.
    """
    messages = list(iter_catalogue(app, language))

    if not messages:
        print(f"  {app}/{language}: no msgid catalogue found")
        return {"app": app, "catalogue": 0, "created": 0, "filled": 0}

    try:
        locale_path = frappe.get_app_path(app, "locale")
    except Exception:
        locale_path = os.path.join(app, "locale")

    # Catalogue identity is the msgid rather than a line number: regenerating
    # a .po file shifts every line and would otherwise mark the whole
    # catalogue as Changed on the next scan.
    po_path = os.path.join(locale_path, f"{language.replace('-', '_')}.po")

    # One read instead of a lookup per msgid: source_text is a Long Text
    # column with no index, and untouched by any query below.
    rows = frappe.get_all(
        "Translation Entry",
        filters={"app_name": app},
        fields=[
            "name",
            "source_text",
            "translated_text",
            "resource_key",
        ],
    )

    by_resource = {}
    by_source = {}

    for row in rows:
        if row.resource_key:
            by_resource[row.resource_key] = row

        source = source_key(row.source_text)

        if source:
            by_source.setdefault(source, row)

    created = 0
    seen = []
    updates = []
    realign = []

    for msgid, translated in messages:
        if not msgid:
            continue

        # The same visibility filter the source scanners use, so catalogue
        # symbols such as "!=" never become translation work.
        if not has_human_text(msgid):
            continue

        context = (
            f"po:{language}:"
            f"{hashlib.sha1(msgid.encode('utf-8')).hexdigest()[:16]}"
        )

        resource_key = make_resource_key(
            app=app,
            source_type="Message",
            path=po_path,
            context=context,
        )

        # A po-derived row for this exact msgid.
        row = by_resource.get(resource_key)

        if row is not None:
            seen.append(row.name)

            # The catalogue is what the runtime looks up, so a po-derived row
            # whose stored text drifted from the msgid (the source was edited
            # and the shipped .po regenerated afterwards) can never match a
            # translation. Realign the stored key to the catalogue.
            if source_key(row.source_text) != msgid:
                realign.append(
                    {
                        "name": row.name,
                        "source_text": msgid,
                        "hash_key": make_hash(
                            app=app,
                            source_type="Message",
                            text=msgid,
                            context=context,
                        ),
                    }
                )
                row.source_text = msgid

            if translated and not source_key(row.translated_text):
                updates.append(
                    {"name": row.name, "translated_text": translated}
                )
                row.translated_text = translated

            continue

        # A msgid may already be tracked because it was scanned from a source
        # file. Filling that row beats adding a second row for the same text.
        row = by_source.get(msgid)

        if row is not None:
            seen.append(row.name)

            if translated and not source_key(row.translated_text):
                updates.append(
                    {"name": row.name, "translated_text": translated}
                )
                row.translated_text = translated

            continue

        if save_entry(
            app=app,
            source_type="Message",
            path=po_path,
            text=msgid,
            context=context,
            translated_text=translated,
            translation_source="Imported" if translated else "Manual",
            status="Translated" if translated else "Pending",
        ):
            created += 1

    # Matched rows never went through save_entry, so last_seen has to be
    # refreshed in bulk or the Suspected Deleted pass would flag them all.
    _refresh_last_seen(seen)

    _realign_sources(realign)

    if updates:
        _apply_updates(updates)

    frappe.db.commit()

    print(
        f"  {app}/{language}: catalogue {len(messages)}, "
        f"new {created}, filled {len(updates)}, realigned {len(realign)}"
    )

    return {
        "app": app,
        "catalogue": len(messages),
        "created": created,
        "filled": len(updates),
        "realigned": len(realign),
    }


def _realign_sources(rows):
    """
    Rewrite the source text of po-derived rows that drifted from the msgid.

    Only the key columns change; the existing translation is kept, since it
    still belongs to the same resource.
    """
    for item in rows:
        frappe.db.sql(
            """
            UPDATE `tabTranslation Entry`
            SET source_text = %s,
                hash_key = %s
            WHERE name = %s
            """,
            (item["source_text"], item["hash_key"], item["name"]),
        )


def _refresh_last_seen(names):
    """
    Bulk-refresh last_seen for entries matched from memory.

    They are matched in Python to avoid a query per msgid, so nothing else
    updates their last_seen during the scan.
    """
    timestamp = frappe.utils.now_datetime()

    for start in range(0, len(names), BULK_CHUNK_SIZE):
        chunk = names[start:start + BULK_CHUNK_SIZE]

        if not chunk:
            continue

        placeholders = ", ".join(["%s"] * len(chunk))

        frappe.db.sql(
            f"""
            UPDATE `tabTranslation Entry`
            SET last_seen = %s,
                change_status = CASE
                    WHEN change_status = 'Suspected Deleted' THEN 'Restored'
                    ELSE change_status
                END
            WHERE name IN ({placeholders})
            """,
            tuple([timestamp] + chunk),
        )


# ============================================================
# App scanner
# ============================================================

def scan_app(app):
    """
    Scan one installed Frappe app.
    """
    print(f"Scanning app: {app}")

    try:
        app_path = frappe.get_app_path(app)
    except Exception as exc:
        print(f"  [APP PATH ERROR] {app}: {exc}")
        return {
            "app": app,
            "created": 0,
            "errors": 1,
        }

    if not os.path.isdir(app_path):
        print(f"  Path not found: {app_path}")
        return {
            "app": app,
            "created": 0,
            "errors": 1,
        }

    created = 0
    errors_before = 0

    # Record the beginning of this scan.
    #
    # We must NOT mark the whole app as "Suspected Deleted" here.
    # Only a completely successful scan may decide that a resource
    # disappeared from the current source tree.
    scan_started = frappe.utils.now_datetime()

    # Reconcile against the app's own msgid catalogue first. It is the list
    # Frappe generates from the source tree, so it covers strings the pattern
    # scanner cannot recover (report names, template literals, strings with
    # escaped quotes) and the msgids the official catalogue leaves in English.
    try:
        created += scan_catalogue(app, DEFAULT_LANGUAGE).get("created", 0)
    except Exception as exc:
        errors_before += 1

        print("")
        print("  [CATALOGUE ERROR]")
        print(f"    app  : {app}")
        print(f"    error: {type(exc).__name__}: {exc}")
        print("    continuing without catalogue reconciliation")
        print("")

        try:
            frappe.db.rollback()
        except Exception:
            pass

    for root, dirs, files in os.walk(app_path):

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRS
        ]

        for filename in files:

            if filename.endswith(IGNORED_FILE_SUFFIXES):
                continue

            filepath = os.path.join(
                root,
                filename,
            )

            try:

                # A per-file savepoint keeps one broken file from discarding
                # every row already inserted for this app in this scan.
                frappe.db.savepoint("wlh_translate_file")

                # Existing Frappe translation CSV.
                if (
                    filename.endswith(".csv")
                    and "translations" in root.split(os.sep)
                ):
                    created += scan_translation_csv(
                        app,
                        filepath,
                    )
                    continue

                extension = os.path.splitext(
                    filename
                )[1].lower()

                # JSON metadata.
                if extension == ".json":
                    if filename.startswith(IGNORED_JSON_FILE_PREFIXES):
                        continue

                    if is_setup_wizard_data(root):
                        # Seed data holds user-facing values in plain strings
                        # (uom_name, industries, ...) that scan_json ignores.
                        created += scan_setup_wizard_data(
                            app,
                            filepath,
                        )
                    else:
                        created += scan_json(
                            app,
                            filepath,
                        )
                    continue

                # Explicit translation calls.
                if extension in SOURCE_EXTENSIONS:
                    created += scan_source_file(
                        app,
                        filepath,
                        SOURCE_EXTENSIONS[extension],
                    )

            except Exception as exc:
                errors_before += 1

                print("")
                print("  [FILE ERROR]")
                print(f"    app  : {app}")
                print(f"    file : {filepath}")
                print(f"    error: {type(exc).__name__}: {exc}")
                print("    continuing...")
                print("")

                try:
                    frappe.db.rollback(save_point="wlh_translate_file")
                except Exception:
                    pass

    print(
        f"  {app}: {created} new translation resources"
    )

    if errors_before:
        print(
            f"  {app}: {errors_before} file-level errors"
        )

    # Only after a completely successful scan may we decide that
    # previously known resources have disappeared.
    #
    # Resources without resource_key are legacy records and are
    # intentionally excluded from this lifecycle check.
    if errors_before == 0:
        suspected_deleted = frappe.db.sql(
            """
            UPDATE `tabTranslation Entry`
            SET change_status = 'Suspected Deleted'
            WHERE app_name = %(app)s
              AND resource_key IS NOT NULL
              AND resource_key != ''
              AND (
                    last_seen IS NULL
                    OR last_seen < %(scan_started)s
              )
            """,
            {
                "app": app,
                "scan_started": scan_started,
            },
        )

        print(
            f"  {app}: completed successfully; "
            "missing resources marked as Suspected Deleted"
        )
    else:
        print(
            f"  {app}: scan incomplete; "
            "skipping Suspected Deleted detection"
        )

    return {
        "app": app,
        "created": created,
        "errors": errors_before,
    }



def scan_source_file(app, filepath, source_type):
    """
    Scan Python / JavaScript / HTML source files.

    Only explicit translation calls are extracted:
        __()
        frappe._()
        _()

    Ordinary English strings are NOT treated as translation resources.
    """
    try:
        with open(
            filepath,
            "r",
            encoding="utf-8",
            errors="ignore",
        ) as f:
            content = f.read()

    except OSError:
        raise

    count = 0

    matches = []

    for pattern in TRANSLATION_PATTERNS:
        matches.extend(pattern.finditer(content))

    # Sort by actual source position so occurrence identity is stable.
    matches.sort(key=lambda match: match.start())

    for occurrence_index, match in enumerate(matches, start=1):
        try:
            literal = match.group(1)
        except (IndexError, AttributeError):
            continue

        # The stored key must equal the value the running code passes to _(),
        # so the escape sequences are resolved here.
        text = unescape_literal(literal)

        if not text:
            continue

        # Ignore obvious non-human / structural values.
        if not has_human_text(text):
            continue

        # Calculate the source line number.
        line_number = content.count("\n", 0, match.start()) + 1

        context = (
            f"translation_call:{occurrence_index}"
        )

        if save_entry(
            app=app,
            source_type=source_type,
            path=filepath,
            text=text,
            line_number=line_number,
            context=context,
        ):
            count += 1

    return count

# ============================================================
# All installed apps
# ============================================================

def scan_all():
    """
    Scan every app installed on the current Frappe site.

    Existing Translation Entry records are preserved.
    """
    print("=" * 70)
    print("WLH Translate Resource Scanner V2")
    print("=" * 70)

    apps = frappe.get_installed_apps()

    print("Installed apps:")
    for app in apps:
        print(f"  - {app}")

    total_created = 0
    total_errors = 0
    results = []

    for app in apps:
        result = scan_app(app)

        results.append(result)

        total_created += result.get("created", 0)
        total_errors += result.get("errors", 0)

        # Commit each app separately.
        # This prevents one later app from rolling back everything
        # discovered in earlier apps.
        frappe.db.commit()

    print("=" * 70)
    print(
        f"Scan finished."
    )
    print(
        f"Apps scanned       : {len(apps)}"
    )
    print(
        f"New resources      : {total_created}"
    )
    print(
        f"File-level errors  : {total_errors}"
    )
    print("=" * 70)

    return {
        "apps": apps,
        "new_resources": total_created,
        "errors": total_errors,
        "results": results,
    }
