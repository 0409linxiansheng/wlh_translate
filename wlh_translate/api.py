import frappe

from wlh_translate.utils.language import DEFAULT_LANGUAGE


# ============================================================
# Background jobs
# ============================================================
#
# Scanning, translating and exporting a full language pack all take longer
# than a web request may live, so they run on the long queue. A cache lock
# keeps a double clicked button from queueing the same job twice.

LOCK_TIMEOUT = 6 * 60 * 60

JOB_LOCK_PREFIX = "wlh_translate:job:"


def _job_lock_key(name):
    # several sites share one redis instance, so the lock is site scoped
    return f"{frappe.local.site}|{JOB_LOCK_PREFIX}{name}"


def _acquire_job_lock(name):
    if not frappe.cache.set(
        _job_lock_key(name),
        1,
        nx=True,
        ex=LOCK_TIMEOUT,
    ):
        frappe.throw(
            f"A wlh_translate job ({name}) is already running. "
            "Wait for it to finish before starting another one."
        )


def _run_job(name, method, kwargs=None):
    """Run a queued job and always release its lock."""
    try:
        frappe.get_attr(method)(**(kwargs or {}))
    finally:
        frappe.cache.delete(_job_lock_key(name))


def _enqueue(name, method, kwargs=None):
    frappe.only_for("System Manager")

    _acquire_job_lock(name)

    frappe.enqueue(
        "wlh_translate.api._run_job",
        queue="long",
        timeout=LOCK_TIMEOUT,
        name=name,
        method=method,
        kwargs=kwargs or {},
    )

    return {"queued": True, "job": name}


@frappe.whitelist()
def scan_all_apps():
    """Scan every installed app for translation resources."""
    return _enqueue(
        "scan_all_apps",
        "wlh_translate.scanner.scanner.scan_all",
    )


@frappe.whitelist()
def translate_pending_entries():
    """Translate every Pending entry with the dictionary translator."""
    return _enqueue(
        "translate_pending_entries",
        "wlh_translate.translator.translator.translate_pending",
    )


@frappe.whitelist()
def import_existing_translations(language=DEFAULT_LANGUAGE):
    """Fill empty Pending entries from the catalogues apps already ship."""
    return _enqueue(
        "import_existing_translations",
        "wlh_translate.importer.po_importer.import_from_po",
        {"language": language},
    )


@frappe.whitelist()
def export_translations_to_site(language=DEFAULT_LANGUAGE):
    """Publish finished translations to the site's Translation doctype."""
    return _enqueue(
        "export_translations_to_site",
        "wlh_translate.exporter.exporter.export_to_site",
        {"language": language},
    )


# ============================================================
# Statistics
# ============================================================


def _build_conditions(language=None, app_name=None):
    conditions = []
    values = {}

    if language:
        conditions.append("language = %(language)s")
        values["language"] = language

    if app_name:
        conditions.append("app_name = %(app_name)s")
        values["app_name"] = app_name

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    return where_clause, values


def _group_count(fieldname, language=None, app_name=None):
    allowed_fields = {
        "app_name",
        "source_type",
        "status",
        "change_status",
    }

    if fieldname not in allowed_fields:
        frappe.throw("Invalid statistics field")

    where_clause, values = _build_conditions(language, app_name)

    return frappe.db.sql(
        f"""
        SELECT `{fieldname}` AS value, COUNT(*) AS count
        FROM `tabTranslation Entry`
        {where_clause}
        GROUP BY `{fieldname}`
        ORDER BY count DESC
        """,
        values,
        as_dict=True,
    )


def _count_with_extra_condition(
    extra_condition,
    language=None,
    app_name=None,
    extra_values=None,
):
    where_clause, values = _build_conditions(language, app_name)

    if where_clause:
        where_clause += " AND " + extra_condition
    else:
        where_clause = " WHERE " + extra_condition

    if extra_values:
        values.update(extra_values)

    return frappe.db.sql(
        f"""
        SELECT COUNT(*) AS count
        FROM `tabTranslation Entry`
        {where_clause}
        """,
        values,
        as_dict=True,
    )[0]["count"]


@frappe.whitelist()
def get_translation_statistics(language=None, app_name=None):
    """
    Return translation statistics for the translation resource database.

    Optional filters:
        language
        app_name
    """

    where_clause, values = _build_conditions(language, app_name)

    total = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS count
        FROM `tabTranslation Entry`
        {where_clause}
        """,
        values,
        as_dict=True,
    )[0]["count"]

    translated = _count_with_extra_condition(
        "status = %(status)s",
        language=language,
        app_name=app_name,
        extra_values={"status": "Translated"},
    )

    reviewed = _count_with_extra_condition(
        "status = %(status)s",
        language=language,
        app_name=app_name,
        extra_values={"status": "Reviewed"},
    )

    pending = _count_with_extra_condition(
        "status = %(status)s",
        language=language,
        app_name=app_name,
        extra_values={"status": "Pending"},
    )

    with_translation = _count_with_extra_condition(
        "translated_text IS NOT NULL AND TRIM(translated_text) != ''",
        language=language,
        app_name=app_name,
    )

    percentage = 0
    if total:
        percentage = round((translated + reviewed) * 100 / total, 2)

    return {
        "total": total,
        "translated": translated,
        "reviewed": reviewed,
        "pending": pending,
        "with_translation": with_translation,
        "translation_percentage": percentage,
        "by_app": _group_count(
            "app_name",
            language=language,
            app_name=app_name,
        ),
        "by_source_type": _group_count(
            "source_type",
            language=language,
            app_name=app_name,
        ),
        "by_status": _group_count(
            "status",
            language=language,
            app_name=app_name,
        ),
        "by_change_status": _group_count(
            "change_status",
            language=language,
            app_name=app_name,
        ),
    }
