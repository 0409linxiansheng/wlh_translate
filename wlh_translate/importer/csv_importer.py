import csv
import io

import frappe

from wlh_translate.exporter.exporter import export_to_site
from wlh_translate.utils.language import (
    DEFAULT_LANGUAGE,
    language_aliases,
    normalize_language,
)


# ============================================================
# WLH Translate CSV Importer
# ============================================================
#
# Fills Translation Entry back in from a CSV produced by
# wlh_translate.exporter.build_pending_csv(). Rows are matched on the source
# text, because that is the key Frappe itself compares against at runtime.
#
# source_text is never rewritten here: it has to stay byte for byte
# identical to the message Frappe looks up, HTML entities included. Only
# translated_text, translation_source and status are touched.

BATCH_SIZE = 500

SOURCE_COLUMN = "source_text"
TRANSLATED_COLUMN = "translated_text"


def _read_pairs(content):
    """
    Return [(source_text, translated_text), ...] from an uploaded CSV.

    The header row is optional. A file without one is read as two columns,
    source first.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")

    # the exporter writes a BOM so Excel picks utf-8; strip it again
    content = str(content or "").lstrip("\ufeff")

    if not content.strip():
        return []

    rows = [
        row
        for row in csv.reader(io.StringIO(content))
        if any(str(cell).strip() for cell in row)
    ]

    if not rows:
        return []

    header = [str(cell).strip().lower() for cell in rows[0]]

    if SOURCE_COLUMN in header:
        source_index = header.index(SOURCE_COLUMN)
        translated_index = (
            header.index(TRANSLATED_COLUMN)
            if TRANSLATED_COLUMN in header
            else source_index + 1
        )
        rows = rows[1:]
    else:
        source_index = 0
        translated_index = 1

    pairs = []

    for row in rows:
        if source_index >= len(row) or translated_index >= len(row):
            continue

        source = str(row[source_index])
        translated = str(row[translated_index]).strip()

        if not source.strip() or not translated:
            continue

        pairs.append((source, translated))

    return pairs


def _load_entries(language):
    """
    Map every source text of a language to the entries carrying it.

    The same source text is usually scanned from several files and apps, so
    one CSV row can fill in more than one entry.
    """
    rows = frappe.get_all(
        "Translation Entry",
        filters={"language": ["in", language_aliases(language)]},
        fields=["name", "source_text", "translated_text"],
    )

    entries = {}

    for row in rows:
        key = str(row.source_text or "").strip()

        if not key:
            continue

        entries.setdefault(key, []).append(row)

    return entries


def import_translated_csv(content, language=DEFAULT_LANGUAGE, overwrite=False):
    """
    Fill Translation Entry from a CSV of source/translated pairs.

    Args:
        content: the CSV file, as text or bytes
        language: language the rows belong to
        overwrite: also replace entries that already have a translation

    Returns a summary dict.
    """
    target_language = normalize_language(language) or DEFAULT_LANGUAGE

    pairs = _read_pairs(content)

    print("=" * 70)
    print("WLH Translate: Import translated CSV")
    print("=" * 70)
    print(f"Filled in rows       : {len(pairs)}")

    if not pairs:
        print("Nothing to import.")
        print("=" * 70)
        return {
            "language": target_language,
            "rows": 0,
            "updated": 0,
            "unknown": 0,
            "skipped": 0,
        }

    entries = _load_entries(target_language)

    updates = []
    updated = 0
    unknown = 0
    skipped = 0

    for source, translated in pairs:
        matched = entries.get(source.strip())

        if not matched:
            unknown += 1
            continue

        for row in matched:
            if not overwrite and str(row.translated_text or "").strip():
                # somebody already translated this one, never overwrite it
                # by accident
                skipped += 1
                continue

            updates.append({"name": row.name, "translated_text": translated})

            if len(updates) >= BATCH_SIZE:
                _apply_updates(updates)
                updated += len(updates)
                updates = []

    if updates:
        _apply_updates(updates)
        updated += len(updates)

    frappe.db.commit()

    if updated:
        # 导入的译文立刻发布到站点，省掉用户再点一次「导出到站点」。
        # 但绝不覆盖站点上已有的译文：Translation Entry 装的是扫描出来的
        # 待办，站点上已有的多半是官方译文或人工校对过的。这里曾经传
        # overwrite=True，一次误导入就把整站字段标签换成了别的语言。
        # 新增的照样发布，有冲突的交回用户用「导出到站点」显式决定。
        export_to_site(language=target_language, overwrite=False)

    print("-" * 70)
    print(f"Updated              : {updated}")
    print(f"Unknown source text  : {unknown}")
    print(f"Already translated   : {skipped}")
    print("=" * 70)

    return {
        "language": target_language,
        "rows": len(pairs),
        "updated": updated,
        "unknown": unknown,
        "skipped": skipped,
    }


def _apply_updates(updates):
    """
    Apply the imports one row at a time.

    frappe.db.sql() executes a single statement, so a list of mappings
    cannot be used as an executemany argument; callers batch and commit.
    """
    for item in updates:
        frappe.db.sql(
            """
            UPDATE `tabTranslation Entry`
            SET translated_text = %s,
                translation_source = 'Imported',
                status = 'Translated'
            WHERE name = %s
            """,
            (item["translated_text"], item["name"]),
        )