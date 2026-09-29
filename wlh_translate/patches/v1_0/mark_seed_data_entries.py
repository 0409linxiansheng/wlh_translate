import frappe

TEST_FIXTURE_REASON = "Test fixture"
SEED_DATA_REASON = "Setup wizard seed data"


def execute():
    """
    Flag entries collected from app fixtures instead of UI text.

    The scanner used to read the test runner fixtures (*/doctype/*/test_records.json,
    test_data_*.json), the country specific chart of accounts and tax templates and
    the numeric keys of the setup wizard UOM data. None of those strings are ever
    rendered, so they only added noise to the translation worklist. The scanner now
    skips them; this marks the rows that were collected before that.
    """
    rules = (
        (
            """
            source_path LIKE %(test_records)s
            OR source_path LIKE %(test_data)s
            """,
            {"test_records": "%/test_records.json", "test_data": "%/test_data_%"},
            TEST_FIXTURE_REASON,
        ),
        (
            "source_path LIKE %(country_tax)s",
            {"country_tax": "%/country_wise_tax.json"},
            SEED_DATA_REASON,
        ),
        (
            """
            source_path LIKE %(uom_conversion)s
            AND (context LIKE %(abbr)s OR context LIKE %(value)s)
            """,
            {"uom_conversion": "%/uom_conversion_data.json", "abbr": "%.abbr", "value": "%.value"},
            SEED_DATA_REASON,
        ),
    )

    marked = 0

    for condition, values, reason in rules:
        rows = frappe.db.sql_list(
            f"""
            SELECT name FROM `tabTranslation Entry`
            WHERE is_translatable = 1 AND ({condition})
            """,
            values,
        )

        for index in range(0, len(rows), 500):
            chunk = rows[index : index + 500]

            frappe.db.sql(
                """
                UPDATE `tabTranslation Entry`
                SET is_translatable = 0, ignore_reason = %(reason)s
                WHERE name IN %(names)s
                """,
                {"names": chunk, "reason": reason},
            )

        marked += len(rows)

    if marked:
        frappe.db.commit()

    print(f"Marked {marked} seed data entries as non-translatable")