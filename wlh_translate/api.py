import frappe
from frappe.utils.background_jobs import get_job, get_job_status, is_job_enqueued

from wlh_translate.auditor import auditor
from wlh_translate.exporter import exporter
from wlh_translate.importer import csv_importer
from wlh_translate.patcher import patcher
from wlh_translate.utils import progress
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
    patcher.PATCH_JOB,
    auditor.AUDIT_JOB,
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
def scan_all_apps(app_name=None):
    """
    Scan installed apps for translation resources.

    Pass "app_name" to refresh a single app, which is what the picker in the
    list view does after somebody installs an app.
    """
    return _enqueue(
        "scan_all_apps",
        "wlh_translate.scanner.scanner.scan_all",
        {"app_name": app_name},
    )


@frappe.whitelist()
def translate_pending_entries(app_name=None):
    """Translate every Pending entry with the dictionary translator."""
    return _enqueue(
        "translate_pending_entries",
        "wlh_translate.translator.translator.translate_pending",
        {"app_name": app_name},
    )


@frappe.whitelist()
def import_existing_translations(language=DEFAULT_LANGUAGE, app_name=None):
    """Fill empty Pending entries from the catalogues apps already ship."""
    return _enqueue(
        "import_existing_translations",
        "wlh_translate.importer.po_importer.import_from_po",
        {"language": language, "app_name": app_name},
    )


@frappe.whitelist()
def export_translations_to_site(language=DEFAULT_LANGUAGE, app_name=None):
    """Publish finished translations to the site's Translation doctype."""
    return _enqueue(
        "export_translations_to_site",
        "wlh_translate.exporter.exporter.export_to_site",
        {"language": language, "app_name": app_name},
    )


# ============================================================
# Upstream patches
# ============================================================
#
# Some text is hard coded in a frontend component - often inside a shared npm
# package - and rendered verbatim, so no Translation entry can reach it. The
# only way out is to edit that source and compile the bundle again. Each such
# edit is kept in the patcher library as a replayable diff; these methods are
# what the list view uses to see them and to replay one.


@frappe.whitelist()
def list_upstream_patches(app_name=None):
    """
    Describe every patch the library holds for an installed app.

    Patches for apps that are not installed are left out: applying one would
    fail with a missing file, and the list is meant to be actionable.
    """
    frappe.only_for("System Manager")

    installed = set(frappe.get_installed_apps())

    return [
        row
        for row in patcher.list_patches(app_name)
        if row["app_name"] in installed
    ]


def _enqueue_patch(app_name, action, patch_name=None):
    if not app_name:
        frappe.throw("An app is required to patch or rebuild a frontend")

    if app_name not in frappe.get_installed_apps():
        frappe.throw(f"App {app_name!r} is not installed on this site")

    return _enqueue(
        patcher.PATCH_JOB,
        "wlh_translate.patcher.patcher.patch_job",
        {"app_name": app_name, "action": action, "patch_name": patch_name},
    )


@frappe.whitelist()
def apply_upstream_patch(app_name, patch_name):
    """Apply one patch and compile the app's frontend again."""
    frappe.only_for("System Manager")

    return _enqueue_patch(app_name, "apply", patch_name)


@frappe.whitelist()
def revert_upstream_patch(app_name, patch_name):
    """Put the file the package shipped back, then compile again."""
    frappe.only_for("System Manager")

    return _enqueue_patch(app_name, "revert", patch_name)


@frappe.whitelist()
def rebuild_frontend(app_name):
    """
    Compile an app's frontend bundle without touching its sources.

    A patch is only visible in the browser once the bundle is built again,
    and a build can be interrupted or run before something else changed;
    this is the way to redo it on its own.
    """
    frappe.only_for("System Manager")

    return _enqueue_patch(app_name, "rebuild")


# ============================================================
# Untranslated text audit
# ============================================================


@frappe.whitelist()
def audit_app(app_name, include_dependencies=False):
    """
    List the text an app renders that no translation can ever reach.

    This is the counterpart of the scan: the scan finds what the app already
    declares as translatable, the audit finds hard coded literals and plain
    template text that bypass the translation table entirely. The result is
    a file:line worklist, and each row is a candidate for an upstream patch.
    """
    frappe.only_for("System Manager")

    return _enqueue(
        auditor.AUDIT_JOB,
        "wlh_translate.auditor.auditor.audit_app",
        {
            "app_name": app_name,
            "include_dependencies": frappe.utils.cint(include_dependencies),
        },
    )


@frappe.whitelist()
def get_installed_apps():
    """
    Return the installed apps and how many entries each already has.

    The list view builds its app picker from this. It has to come from the
    server: frappe.boot carries no installed app list, and an app that was
    installed a moment ago has no entries to infer its name from.
    """
    frappe.only_for("System Manager")

    counts = {
        row["value"]: row["count"]
        for row in _group_count("app_name")
    }

    return [
        {
            "app_name": app,
            "entries": counts.get(app, 0),
        }
        for app in frappe.get_installed_apps()
    ]


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

    if status.value in ("queued", "started"):
        # A running job publishes how far it has come in the cache, because
        # the worker and this request are different processes. Nothing is
        # reported once it ends, so a finished job has no "progress" key.
        running_progress = progress.read(name)

        if running_progress:
            state["progress"] = running_progress

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
def export_all_by_app(language=DEFAULT_LANGUAGE):
    """Return every entry, split into one CSV per app, as a zip file."""
    frappe.only_for("System Manager")

    target_language = normalize_language(language) or DEFAULT_LANGUAGE

    return exporter.build_all_by_app_zip(language=target_language)


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
