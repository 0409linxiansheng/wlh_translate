import frappe
from babel.messages.mofile import read_mo

from frappe.gettext.translate import get_catalog, get_mo_path

from wlh_translate.utils.language import (
    DEFAULT_LANGUAGE,
    language_aliases,
    normalize_language,
)


# ============================================================
# WLH Translate Existing Translation Importer
# ============================================================
#
# erpnext and frappe already ship a large Simplified Chinese catalogue in
# <app>/<app>/locale/zh.po (compiled to sites/assets/locale/zh/...). Those
# strings do not need to be translated again, but Translation Entry has no
# idea they exist, so they would be reported as Pending forever.
#
# This module fills the memory base from those catalogues. It only ever
# fills entries that are still empty, so human work is never overwritten.

BATCH_SIZE = 500

DEFAULT_SOURCE_APPS = ("erpnext", "frappe")


def _catalog_to_dict(catalog):
    """
    Convert a babel catalogue into {source_text: translated_text}.

    Messages carrying a context are skipped: our translation keys are
    context-free, matching how the exporter writes them.
    """
    translations = {}

    for message in catalog:
        if not message.id:
            continue

        if message.context:
            continue

        if getattr(message, "fuzzy", False):
            continue

        string = message.string

        if isinstance(string, (list, tuple)):
            string = string[0] if string else ""

        string = str(string or "").strip()

        if not string:
            continue

        translations[str(message.id)] = string

    return translations


def load_app_translations(app, language):
    """
    Read an app's existing translations for one language.

    The .po file is the source of truth; the compiled .mo is used when no
    .po file is available.
    """
    locale = language.replace("-", "_")

    po_catalog = get_catalog(app, locale)

    translations = _catalog_to_dict(po_catalog)

    if translations:
        return translations

    mo_path = get_mo_path(app, locale)

    if not mo_path.exists():
        return {}

    with open(mo_path, "rb") as mo_file:
        return _catalog_to_dict(read_mo(mo_file))


def import_from_po(
    apps=DEFAULT_SOURCE_APPS,
    language=DEFAULT_LANGUAGE,
    limit=None,
):
    """
    Fill empty Pending entries from the translations an app already ships.

    Args:
        apps: apps whose catalogues are used as the memory base
        language: language code to import
        limit: maximum number of Translation Entry rows to read

    Returns a summary dict.
    """
    target_language = normalize_language(language) or DEFAULT_LANGUAGE

    print("=" * 70)
    print("WLH Translate: Import existing translations")
    print("=" * 70)

    translations = {}

    for app in apps:
        app_translations = load_app_translations(app, target_language)

        print(f"{app}: {len(app_translations)} existing translations")

        for source, translated in app_translations.items():
            translations.setdefault(source, translated)

    if not translations:
        print("No existing translations found.")
        print("=" * 70)
        return {
            "language": target_language,
            "catalogues": 0,
            "matched": 0,
            "pending": 0,
        }

    pending = frappe.get_all(
        "Translation Entry",
        filters={
            "status": "Pending",
            "language": ["in", language_aliases(target_language)],
        },
        fields=["name", "source_text", "translated_text"],
        limit_page_length=limit,
    )

    print(f"{len(pending)} pending entries to check")

    updates = []
    matched = 0

    for row in pending:
        if str(row.translated_text or "").strip():
            continue

        translated = translations.get(str(row.source_text or "").strip())

        if not translated:
            continue

        updates.append({"name": row.name, "translated_text": translated})

        if len(updates) >= BATCH_SIZE:
            _apply_updates(updates)
            matched += len(updates)
            updates = []

    if updates:
        _apply_updates(updates)
        matched += len(updates)

    frappe.db.commit()

    print("-" * 70)
    print(f"Catalogue entries    : {len(translations)}")
    print(f"Pending checked      : {len(pending)}")
    print(f"Imported             : {matched}")
    print(f"Still pending        : {len(pending) - matched}")
    print("=" * 70)

    return {
        "language": target_language,
        "catalogues": len(translations),
        "pending": len(pending),
        "matched": matched,
        "unmatched": len(pending) - matched,
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