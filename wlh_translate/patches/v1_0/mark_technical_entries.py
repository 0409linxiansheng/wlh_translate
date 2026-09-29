import frappe

from wlh_translate.scanner.scanner import looks_like_technical_string


def execute():
    """
    Flag entries whose source text is a technical token, not prose.

    The scanner used to accept anything that survived the HTML strip, so
    icon class names, pure numbers and field names were stored as
    translatable resources. looks_like_technical_string() now filters them
    on insert; this marks the rows that were collected before that.
    """
    rows = frappe.get_all(
        "Translation Entry",
        filters={"is_translatable": 1},
        fields=["name", "source_text"],
        limit_page_length=0,
    )

    names = [
        row.name
        for row in rows
        if looks_like_technical_string(row.source_text)
    ]

    for index in range(0, len(names), 500):
        chunk = names[index : index + 500]

        frappe.db.sql(
            """
            UPDATE `tabTranslation Entry`
            SET is_translatable = 0, ignore_reason = %(reason)s
            WHERE name IN %(names)s
            """,
            {"names": chunk, "reason": "Technical string"},
        )

    if names:
        frappe.db.commit()

    print(f"Marked {len(names)} entries as non-translatable")