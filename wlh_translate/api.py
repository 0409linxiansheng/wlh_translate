import frappe
from frappe.utils.background_jobs import get_job, get_job_status, is_job_enqueued

from wlh_translate.exporter import exporter
from wlh_translate.importer import csv_importer
from wlh_translate.utils.language import DEFAULT_LANGUAGE, normalize_language


# ============================================================
# Background jobs
# ============================================================
#
# Scanning, translating, importing and exporting a full language pack all
# take longer than a web request may live, so they run on the long queue.
#
# Duplicate protection is delegated to RQ: every job gets a fixed job_id and
# frappe.enqueue(deduplicate=True) refuses to queue it again while the
# previous run is still queued or running. This replaces a hand written
# cache lock, which leaked whenever a worker died mid job and left the
# button dead until the lock expired hours later.

JOB_TIMEOUT = 6 * 60 * 60

# The job ids of every background job this app can queue. Used by
# get_job_state() and reset_stuck_jobs(), and as the key the list view
# polls with.
JOB_NAMES = (
    "scan_all_apps",
    "translate_pending_entries",
    "import_existing_translations",
    "export_translations_to_site",
)


def _validate_job_name(name):
    if name not in JOB_NAMES:
        frappe.throw(f"Unknown wlh_translate job: {name}")


def _enqueue(name, job_method, kwargs=None):
    frappe.only_for("System Manager")

    # the argument is called job_method because frappe.enqueue() already
    # uses "method" for the callable it has to run
    job = frappe.enqueue(
        job_method,
        queue="long",
        timeout=JOB_TIMEOUT,
        job_id=name,
        deduplicate=True,
        **(kwargs or {}),
    )

    if job is None:
        # frappe.enqueue(deduplicate=True) returns None when a job with the
        # same id is already queued or running
        return {"queued": False, "running": True, "job": name}

    return {"queued": True, "job": name, "job_id": job.id}


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


@frappe.whitelist()
def get_job_state(name):
    """
    Report the state of one background job, for the list view to poll.

    The status is "idle" when no job with that id exists any more, which
    happens once RQ expires the record after a finished run.
    """
    frappe.only_for("System Manager")

    _validate_job_name(name)

    status = get_job_status(name)

    if status is None:
        return {"job": name, "status": "idle"}

    state = {"job": name, "status": status.value}

    job = get_job(name)

    if job is None:
        return state

    if status.value == "finished":
        state["result"] = job.return_value()

    elif status.value == "failed":
        # the full traceback is already in Error Log, the button only
        # needs the last line
        lines = [
            line
            for line in (job.exc_info or "").strip().splitlines()
            if line.strip()
        ]
        state["error"] = lines[-1] if lines else ""

    return state


@frappe.whitelist()
def reset_stuck_jobs():
    """
    Drop the records of jobs that are still queued or running.

    A worker that dies mid job leaves the job marked as started, and
    deduplication trusts that flag, so the button would stay dead until RQ
    cleans the registry up. This is the manual way out.
    """
    frappe.only_for("System Manager")

    removed = []

    for name in JOB_NAMES:
        if not is_job_enqueued(name):
            continue

        job = get_job(name)

        if job is None:
            continue

        job.delete()
        removed.append(name)

    return {"removed": removed}


# ============================================================
# Translation worklist (CSV round trip)
# ============================================================
#
# These run inside the request on purpose: the file is produced or consumed
# in one go, and the user has to see the outcome immediately. They are
# explicit exports, unlike the two comma separated lists a logged in user
# can already download from a list view.


@frappe.whitelist()
def export_pending_csv(language=DEFAULT_LANGUAGE, app_name=None):
    """Return the entries that still need a translation as a CSV file."""
    frappe.only_for("System Manager")

    target_language = normalize_language(language) or DEFAULT_LANGUAGE

    result = exporter.build_pending_csv(
        language=target_language,
        app_name=app_name,
    )

    return {
        "filename": f"wlh_translate_pending_{target_language}.csv",
        "rows": result["rows"],
        "occurrences": result["occurrences"],
        "content": result["content"],
    }


@frappe.whitelist()
def import_translated_csv_file(content, language=DEFAULT_LANGUAGE):
    """Load a filled in CSV back into Translation Entry."""
    frappe.only_for("System Manager")

    return csv_importer.import_translated_csv(content, language=language)


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
