import base64
import csv
import io
import os
import zipfile

import frappe
from frappe.translate import clear_cache, write_translations_file
from frappe.utils import now_datetime, sanitize_html

from wlh_translate.utils import progress
from wlh_translate.utils.language import (
    DEFAULT_LANGUAGE,
    ensure_language,
    language_aliases,
    normalize_language,
)


# ============================================================
# WLH Translate Resource Exporter
# ============================================================
#
# Finished translations only live in "Translation Entry". Frappe renders a
# page from three sources:
#
#   1. <app>/<app>/translations/<lang>.csv
#   2. <app>/<app>/locale/<lang>.po  (compiled to a .mo)
#   3. the "Translation" doctype (tabTranslation), which is applied last
#
# This module writes to (3) because it takes effect immediately, per site,
# and never touches an app's git working tree.

BATCH_SIZE = 500

EXPORTABLE_STATUSES = ("Translated", "Reviewed")

# Job id this export reports its progress under. It matches the name
# wlh_translate.api.export_translations_to_site enqueues the job with.
EXPORT_JOB = "export_translations_to_site"

STATUS_PRIORITY = {
    "Reviewed": 0,
    "Translated": 1,
}


def _source_key(value):
    """
    Build the key Frappe uses at lookup time.

    frappe.utils.translations._() strips the message before looking it up,
    so stored and compared values must be stripped the same way.
    """
    return str(value or "").strip()


def _collect_candidates(
    language=None,
    app_name=None,
    statuses=EXPORTABLE_STATUSES,
    limit=None,
):
    """
    Pick the best translation for every distinct source text.

    The same source text can be scanned from several locations, possibly
    with different translations. Exactly one entry per source text may be
    exported, so conflicts are resolved by status and then recency.

    Returns (selected, conflicts).
    """
    filters = {
        "is_translatable": 1,
        "status": ["in", list(statuses)],
    }

    if app_name:
        filters["app_name"] = app_name

    if language:
        filters["language"] = ["in", language_aliases(language)]

    rows = frappe.get_all(
        "Translation Entry",
        filters=filters,
        fields=[
            "name",
            "source_text",
            "translated_text",
            "language",
            "status",
            "last_seen",
        ],
        order_by="last_seen desc",
        limit_page_length=limit,
    )

    selected = {}
    conflicts = []

    for row in rows:
        source = _source_key(row.source_text)
        translated = _source_key(row.translated_text)

        if not source or not translated:
            continue

        current = selected.get(source)

        if current is None:
            selected[source] = row
            continue

        # results are ordered by last_seen desc, so on equal status the
        # first row seen is already the most recent one
        if STATUS_PRIORITY.get(row.status, 99) < STATUS_PRIORITY.get(
            current.status, 99
        ):
            conflicts.append(current)
            selected[source] = row
        else:
            conflicts.append(row)

    return selected, conflicts


def get_existing_translations(language):
    """
    Return every context-less "Translation" row for a language.

    Rows carrying a context are skipped: our contexts are scanner-specific
    paths, not Frappe msgctxt values, so they would never match at runtime.
    """
    rows = frappe.get_all(
        "Translation",
        filters={"language": language},
        fields=["name", "source_text", "translated_text", "context"],
    )

    existing = {}

    for row in rows:
        if row.context:
            continue

        existing[_source_key(row.source_text)] = row

    return existing


def export_to_site(
    language=DEFAULT_LANGUAGE,
    app_name=None,
    statuses=EXPORTABLE_STATUSES,
    overwrite=True,
    limit=None,
):
    """
    Publish finished translations to the site's "Translation" doctype.

    Args:
        language: target language filter, None to export every language
        app_name: limit to one scanned app
        statuses: Translation Entry statuses considered finished
        overwrite: replace an existing "Translation" row whose text differs.
            Defaults to True: "Translation Entry" is the worklist where the
            translations are actually written and checked, so it decides
            what the site shows. With False an entry whose site row already
            holds a different text is counted as a conflict and dropped,
            which silently discards exactly the edits the user made here.
        limit: maximum number of Translation Entry rows to read

    Returns a summary dict.
    """
    print("=" * 70)
    print("WLH Translate: Export to site")
    print("=" * 70)

    selected, conflicts = _collect_candidates(
        language=language,
        app_name=app_name,
        statuses=statuses,
        limit=limit,
    )

    total_candidates = len(selected)
    processed = 0

    progress.report(EXPORT_JOB, 0, total_candidates)

    by_language = {}

    for source, row in selected.items():
        target_language = (
            normalize_language(row.language) or DEFAULT_LANGUAGE
        )
        by_language.setdefault(target_language, {})[source] = row

    summary = {
        "selected": len(selected),
        "inserted": 0,
        "overwritten": 0,
        "skipped": 0,
        "conflicts": len(conflicts),
        "conflict_samples": [
            {
                "entry": row.name,
                "source_text": row.source_text,
                "translated_text": row.translated_text,
                "status": row.status,
            }
            for row in conflicts[:20]
        ],
        "by_language": {},
        "candidates_by_language": {},
    }

    if not by_language:
        print("Nothing to export: no finished translations found.")
        print("=" * 70)
        progress.clear(EXPORT_JOB)
        return summary

    timestamp = now_datetime()
    user = frappe.session.user

    for target_language, items in sorted(by_language.items()):
        ensure_language(target_language)

        existing = get_existing_translations(target_language)

        to_insert = []
        overwritten = 0
        skipped = 0
        inserted = 0

        print(
            f"{target_language}: {len(items)} source strings, "
            f"{len(existing)} existing site translations"
        )

        for source, row in items.items():
            processed += 1

            # One cache write per row would cost more than the row itself,
            # so the progress is published once per batch.
            if processed % BATCH_SIZE == 0:
                progress.report(
                    EXPORT_JOB,
                    processed,
                    total_candidates,
                )

            translated = sanitize_html(_source_key(row.translated_text))

            if not translated:
                skipped += 1
                continue

            current = existing.get(source)

            if current is not None:
                if _source_key(current.translated_text) == _source_key(
                    translated
                ):
                    skipped += 1
                    continue

                if not overwrite:
                    # A human already translated this string differently.
                    # Never silently replace it.
                    summary["conflict_samples"].append(
                        {
                            "entry": row.name,
                            "source_text": source,
                            "translated_text": translated,
                            "existing": current.translated_text,
                            "reason": "existing site translation differs",
                        }
                    )
                    summary["conflicts"] += 1
                    skipped += 1
                    continue

                frappe.db.set_value(
                    "Translation",
                    current.name,
                    "translated_text",
                    translated,
                    update_modified=False,
                )
                overwritten += 1
                continue

            to_insert.append(
                _translation_row(
                    target_language,
                    source,
                    translated,
                    timestamp=timestamp,
                    user=user,
                )
            )

            if len(to_insert) >= BATCH_SIZE:
                _insert_rows(to_insert)
                inserted += len(to_insert)
                to_insert = []
                frappe.db.commit()

        if to_insert:
            _insert_rows(to_insert)
            inserted += len(to_insert)
            frappe.db.commit()

        summary["inserted"] += inserted
        summary["overwritten"] += overwritten
        summary["skipped"] += skipped
        summary["by_language"][target_language] = {
            "candidates": len(items),
            "existing": len(existing),
            "inserted": inserted,
            "overwritten": overwritten,
            "skipped": skipped,
        }

        progress.report(EXPORT_JOB, processed, total_candidates)

    progress.clear(EXPORT_JOB)

    summary["conflict_samples"] = summary["conflict_samples"][:20]

    # Runtime lookups are cached (bootinfo, user and merged translation
    # dictionaries). Without this the new rows stay invisible until the
    # cache happens to expire.
    clear_cache()

    print("-" * 70)
    print(f"Candidates           : {summary['selected']}")
    print(f"Inserted             : {summary['inserted']}")
    print(f"Overwritten          : {summary['overwritten']}")
    print(f"Skipped              : {summary['skipped']}")
    print(f"Conflicts            : {summary['conflicts']}")
    print("Cache cleared: frappe.translate.clear_cache()")
    print("=" * 70)

    return summary


def _insert_rows(rows):
    """
    Insert "Translation" rows directly.

    Going through doc.save() would be far too slow for a full language
    pack, and "Translation" tracks changes, which would fill the activity
    log for every row.
    """
    frappe.db.bulk_insert(
        "Translation",
        fields=[
            "name",
            "owner",
            "modified_by",
            "creation",
            "modified",
            "docstatus",
            "language",
            "source_text",
            "translated_text",
            "context",
        ],
        values=rows,
        ignore_duplicates=True,
        chunk_size=BATCH_SIZE,
    )


def _translation_row(
    language, source_text, translated_text, timestamp=None, user=None
):
    """
    Build one raw "Translation" row for _insert_rows().

    The tuple order has to match the fields list there.
    """
    return (
        frappe.generate_hash(length=10),
        user or frappe.session.user,
        user or frappe.session.user,
        timestamp or now_datetime(),
        timestamp or now_datetime(),
        0,
        language,
        source_text,
        translated_text,
        "",
    )


def publish_one(language, source_text, translated_text, overwrite=True):
    """
    Write a single source text into the site's "Translation" doctype.

    This is the per row counterpart of export_to_site(). It exists so an
    entry edited in the desk takes effect right away: the change otherwise
    sits in "Translation Entry" until somebody remembers to run a full
    export, which is what made the flow look like it did nothing.

    Returns "skipped", "conflict", "overwritten" or "inserted". Clearing the
    translation cache is left to the caller, so a bulk run can do it once.
    """
    target_language = normalize_language(language) or DEFAULT_LANGUAGE

    source = _source_key(source_text)
    translated = sanitize_html(_source_key(translated_text))

    if not source or not translated:
        return "skipped"

    existing = frappe.db.sql(
        """
        SELECT name, source_text, translated_text
        FROM `tabTranslation`
        WHERE language = %s AND source_text = %s AND COALESCE(context, '') = ''
        """,
        (target_language, source),
        as_dict=True,
    )

    # The comparison above is the database's, and it ignores case: a lookup
    # for "Getting started" is answered by a stored "Getting Started". The
    # frontend looks the key up in a plain JavaScript object, which does not
    # ignore case, so a source string that only differs from the stored one by
    # case would keep rendering English. Such a spelling needs a row of its
    # own, next to the one already there.
    exact = [row for row in existing if row.source_text == source]

    if not exact and existing:
        _insert_rows([_translation_row(target_language, source, translated)])

        return "inserted"

    if exact:
        current = exact[0]

        if _source_key(current.translated_text) == _source_key(translated):
            return "skipped"

        if not overwrite:
            return "conflict"

        frappe.db.set_value(
            "Translation",
            current.name,
            "translated_text",
            translated,
            update_modified=False,
        )

        return "overwritten"

    _insert_rows([_translation_row(target_language, source, translated)])

    return "inserted"


def apply_translation(source_text, translated_text, overwrite=True):
    """
    Force one translated text onto every entry carrying a source text, and
    publish it.

    Unlike sync_entry_on_save() this ignores the per-entry status and text: it
    is meant for patches correcting a whole source text at once, where the new
    text has been checked against an authoritative catalogue.
    """
    for row in frappe.get_all(
        "Translation Entry",
        filters={"source_text": source_text, "is_translatable": 1},
        pluck="name",
        limit_page_length=0,
    ):
        frappe.db.set_value(
            "Translation Entry",
            row,
            {
                "translated_text": translated_text,
                "status": "Translated",
                "translation_source": "Manual",
            },
            update_modified=False,
        )

    return publish_one(
        DEFAULT_LANGUAGE,
        source_text,
        translated_text,
        overwrite=overwrite,
    )


def sync_entry_on_save(doc, method=None):
    """
    Document hook: publish an entry the moment it is saved from the desk.

    Background jobs are skipped on purpose. They save their rows one by one
    and publish the whole batch once when they finish, which is far cheaper
    than clearing the translation cache for every row.
    """
    if getattr(frappe.local, "job", None):
        return

    if not doc.is_translatable or doc.status not in EXPORTABLE_STATUSES:
        return

    if not str(doc.translated_text or "").strip():
        return

    if publish_one(doc.language, doc.source_text, doc.translated_text) in (
        "inserted",
        "overwritten",
    ):
        clear_cache()


CSV_COLUMNS = ("source_text", "translated_text", "app_name", "source_type", "status")


def build_pending_csv(
    language=DEFAULT_LANGUAGE,
    app_name=None,
    statuses=("Pending",),
):
    """
    Build a CSV of the entries that still need a translation.

    The file is meant to be filled in and handed back to
    wlh_translate.importer.csv_importer.import_translated_csv(), so it uses
    plain column names and keeps source_text exactly as stored: HTML
    entities included, because that is the string Frappe compares against.

    One row per distinct source text. The same English string is scanned
    from every file that mentions it, so a raw export repeats it dozens of
    times ("Posting Date" showed up in 24 entries). The importer matches on
    the source text and fills in every entry carrying it, so collapsing the
    duplicates loses no coverage.

    Returns {"content": csv text, "rows": distinct source texts,
             "occurrences": entries those rows cover}.
    """
    filters = {
        "is_translatable": 1,
        "status": ["in", list(statuses)],
    }

    if app_name:
        filters["app_name"] = app_name

    if language:
        filters["language"] = ["in", language_aliases(language)]

    rows = frappe.get_all(
        "Translation Entry",
        filters=filters,
        fields=list(CSV_COLUMNS),
        order_by="app_name asc, source_text asc",
    )

    # results are ordered by app then source text, so the row kept for a
    # source text is always the same one
    distinct = {}

    for row in rows:
        key = str(row.get("source_text") or "").strip()

        if not key:
            continue

        distinct.setdefault(key, row)

    buffer = io.StringIO()

    # the BOM keeps Excel from reading the file as latin-1
    buffer.write("\ufeff")

    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)

    for row in distinct.values():
        writer.writerow([row.get(field) or "" for field in CSV_COLUMNS])

    print("=" * 70)
    print("WLH Translate: Export pending CSV")
    print("=" * 70)
    print(f"Distinct source texts: {len(distinct)}")
    print(f"Entries covered      : {len(rows)}")
    print("=" * 70)

    return {
        "content": buffer.getvalue(),
        "rows": len(distinct),
        "occurrences": len(rows),
    }


def export_to_csv(app, language=DEFAULT_LANGUAGE):
    """
    Write finished translations to <app>/<app>/translations/<lang>.csv.

    This produces a distributable file, but unlike export_to_site() it
    writes into the app's working tree and needs a rebuild to take effect.
    """
    target_language = ensure_language(language)

    selected, _ = _collect_candidates(language=target_language, app_name=app)

    if not selected:
        print(f"{app}: nothing to export")
        return {"app": app, "language": target_language, "exported": 0}

    full_dict = {
        source: _source_key(row.translated_text)
        for source, row in selected.items()
    }

    # write_translations_file() returns None and silently does nothing when the
    # app exposes no source messages, so the path is derived here and the file
    # is checked afterwards.
    path = os.path.join(
        frappe.get_app_path(app, "translations"),
        f"{target_language}.csv",
    )

    write_translations_file(
        app,
        target_language,
        full_dict,
    )

    if not os.path.exists(path):
        print(
            f"{app}: no source messages found in the app, nothing written"
        )
        return {
            "app": app,
            "language": target_language,
            "exported": 0,
            "path": None,
        }

    print(
        f"{app}: exported {len(full_dict)} translations to {path}"
    )

    return {
        "app": app,
        "language": target_language,
        "exported": len(full_dict),
        "path": path,
    }


# When a source text was scanned from several places it may exist once per
# status. The file keeps one row per source text, and a finished
# translation is always preferred over a pending one.
OUTPUT_PRIORITY = {
    "Reviewed": 0,
    "Translated": 1,
    "Pending": 2,
}


def _row_rank(row):
    status_rank = OUTPUT_PRIORITY.get(row.get("status"), 9)
    has_translation = 0 if _source_key(row.get("translated_text")) else 1

    return (status_rank, has_translation)


def _csv_text(rows):
    buffer = io.StringIO()

    # the BOM keeps Excel from reading the file as latin-1
    buffer.write("\ufeff")

    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)

    for row in rows:
        writer.writerow([row.get(field) or "" for field in CSV_COLUMNS])

    return buffer.getvalue()


def build_all_by_app_zip(language=DEFAULT_LANGUAGE):
    """
    Build one CSV per app, holding every entry of that app, and zip them.

    Unlike build_pending_csv() this is a full dump: pending entries are
    included so a single file shows what is finished and what is not. Each
    app gets its own file so the work can be handed out per app.

    Returns {"content": base64 zip, "filename", "apps", "rows"}.
    """
    target_language = ensure_language(language)

    rows = frappe.get_all(
        "Translation Entry",
        filters={
            "is_translatable": 1,
            "language": ["in", language_aliases(target_language)],
        },
        fields=list(CSV_COLUMNS),
        order_by="app_name asc, source_text asc",
    )

    by_app = {}

    for row in rows:
        app = row.get("app_name") or "unknown"
        source = _source_key(row.get("source_text"))

        if not source:
            continue

        entries = by_app.setdefault(app, {})
        current = entries.get(source)

        if current is None or _row_rank(row) < _row_rank(current):
            entries[source] = row

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for app in sorted(by_app):
            archive.writestr(f"{app}.csv", _csv_text(by_app[app].values()))

    print("=" * 70)
    print("WLH Translate: Export all by app")
    print("=" * 70)

    for app in sorted(by_app):
        print(f"  {app}: {len(by_app[app])} source texts")

    print("=" * 70)

    return {
        "content": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "filename": f"wlh_translate_all_{target_language}.zip",
        "apps": sorted(by_app),
        "rows": sum(len(entries) for entries in by_app.values()),
    }