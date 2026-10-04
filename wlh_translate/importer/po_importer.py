import frappe
from babel.messages.mofile import read_mo

from frappe.gettext.translate import get_catalog, get_mo_path

from wlh_translate.exporter.exporter import export_to_site
from wlh_translate.utils import progress
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

# 进度上报使用的任务 id，与 wlh_translate.api.import_existing_translations 入队时一致。
IMPORT_JOB = "import_existing_translations"

# 每检查这么多条上报一次进度。逐条上报的写入开销比检查本身还大。
PROGRESS_STEP = 200


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


def iter_catalogue(app, language):
    """
    Yield (msgid, translated_text) for every context-free, non-fuzzy message
    an app ships for a language.

    Unlike _catalog_to_dict() the untranslated entries are kept, because the
    scanner needs them to surface strings the official catalogue itself still
    leaves in English. A missing translation is returned as an empty string.
    """
    locale = language.replace("-", "_")

    catalog = get_catalog(app, locale)

    if not len(catalog):
        mo_path = get_mo_path(app, locale)

        if not mo_path.exists():
            return

        with open(mo_path, "rb") as mo_file:
            catalog = read_mo(mo_file)

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

        msgid = str(message.id).strip()

        if not msgid:
            continue

        yield msgid, str(string or "").strip()


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
    app_name=None,
):
    """
    从应用自带的译文里，填充还空着的 Pending 条目。

    Args:
        apps: apps whose catalogues are used as the memory base
        language: language code to import
        limit: maximum number of Translation Entry rows to read
        app_name: limit to the entries of one scanned app

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

    pending_filters = {
        "status": "Pending",
        "language": ["in", language_aliases(target_language)],
    }

    if app_name:
        pending_filters["app_name"] = app_name

    pending = frappe.get_all(
        "Translation Entry",
        filters=pending_filters,
        fields=["name", "source_text", "translated_text"],
        limit_page_length=limit,
    )

    total = len(pending)

    print(f"{total} pending entries to check")

    progress.report(IMPORT_JOB, 0, total)

    updates = []
    matched = 0

    for index, row in enumerate(pending, start=1):

        if index % PROGRESS_STEP == 0:
            progress.report(IMPORT_JOB, index, total)

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

    if matched:
        # 导入完直接发布，导入的译文不该还要用户再点一次「导出到站点」。
        # overwrite=False：只补站点上还没有的，绝不覆盖已有译文。
        export_to_site(
            language=target_language,
            app_name=app_name,
            overwrite=False,
        )

    progress.clear(IMPORT_JOB)

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