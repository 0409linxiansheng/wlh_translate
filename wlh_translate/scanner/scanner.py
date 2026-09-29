import csv
import hashlib
import html
import json
import os
import re

import frappe
from frappe.utils import strip_html

from wlh_translate.utils.language import DEFAULT_LANGUAGE


# ============================================================
# WLH Translate Resource Scanner V2
# ============================================================

MAX_TEXT_LENGTH = 5000

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

TRANSLATION_PATTERNS = [
    re.compile(
        r"""__\(\s*(['"])(.*?)\1""",
        re.DOTALL,
    ),
    re.compile(
        r"""frappe\._\(\s*(['"])(.*?)\1""",
        re.DOTALL,
    ),
    re.compile(
        r"""(?<![\w.])_\(\s*(['"])(.*?)\1""",
        re.DOTALL,
    ),
]


# ============================================================
# Helpers
# ============================================================

def clean_text(value):
    """
    Normalize a candidate translation resource.

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


def has_human_text(value):
    """
    Determine whether a value contains actual human-readable content.

    Examples rejected:
        <div></div>
        <div id="stock-levels-placeholder"></div>
        <span class="foo"></span>

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
        return True

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
    text = clean_text(text)

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
                            context=current_path,
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
                                    context=option_context,
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
                    frappe.db.rollback()
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
            text = match.group(2)
        except (IndexError, AttributeError):
            continue

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
