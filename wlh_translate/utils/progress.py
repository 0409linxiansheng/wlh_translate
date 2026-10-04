import frappe


# The worker and the polling request are different processes, so the progress
# of a running job is kept in the site's Redis cache instead of in memory.
# The value is short lived and carries a TTL, so a worker that dies without
# clearing it cannot leave anything behind forever.
PROGRESS_TTL = 6 * 60 * 60

KEY_PREFIX = "wlh_translate:progress:"


def _key(job):
    return KEY_PREFIX + job


def report(job, done, total, app_name=None, app_index=None, app_total=None):
    """
    Publish how far a running job has come.

    "done" and "total" count the units of the current job: files while
    scanning, rows while translating or importing, rows while exporting.
    The percentage and the wording stay on the list view, so nothing
    written here has to be translated.
    """
    frappe.cache.set_value(
        _key(job),
        {
            "done": int(done),
            "total": int(total),
            "app_name": app_name,
            "app_index": app_index,
            "app_total": app_total,
        },
        expires_in_sec=PROGRESS_TTL,
    )


def read(job):
    """
    Return the progress of a running job, or None when none was reported.

    The value has to bypass the process local cache (expires=True), because
    it is written by the worker process, not by this one. Without that, the
    first poll - taken before the worker had reported anything - caches a
    None here and every following poll keeps returning it.
    """
    return frappe.cache.get_value(_key(job), expires=True)


def clear(job):
    """Drop the progress of a job. Called however the job ends."""
    frappe.cache.delete_value(_key(job))