import frappe

from wlh_translate.utils.language import LANGUAGE_ALIASES


def execute():
    """
    Normalize stored language values onto Frappe's language codes.

    Earlier versions hardcoded "zh-CN", which is not a language code known
    to Frappe, so those rows would never match anything at runtime.
    """
    targets = [
        ("Translation Entry", "language"),
        ("Translation Project", "target_language"),
    ]

    for doctype, fieldname in targets:
        table = f"tab{doctype}"

        if not frappe.db.table_exists(doctype):
            continue

        for alias, target in LANGUAGE_ALIASES.items():
            if alias == target:
                continue

            frappe.db.sql(
                f"""
                UPDATE `{table}`
                SET `{fieldname}` = %(target)s
                WHERE LOWER(`{fieldname}`) = %(alias)s
                """,
                {"target": target, "alias": alias},
            )

    frappe.db.commit()