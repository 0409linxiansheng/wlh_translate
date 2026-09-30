import frappe
from frappe.model.document import Document

from wlh_translate.utils.language import (
    DEFAULT_LANGUAGE,
    language_aliases,
    normalize_language,
)


class TranslationProject(Document):
    def validate(self):
        """
        Recalculate the counters on every save.

        They are stored on the document instead of being aggregated at render
        time, so saving is the only moment they can be produced.
        """
        self.refresh_counters()

    def refresh_counters(self, commit=False):
        """
        Recalculate the counter fields from the translation resource table.

        The counts are stored on the project so a list view can show progress
        without aggregating the whole resource table on every render.
        """
        language = normalize_language(self.target_language) or DEFAULT_LANGUAGE

        filters = {
            "is_translatable": 1,
            "language": ["in", language_aliases(language)],
        }

        total = frappe.db.count("Translation Entry", filters)

        translated = frappe.db.count(
            "Translation Entry",
            {**filters, "status": ["in", ["Translated", "Reviewed"]]},
        )

        pending = frappe.db.count(
            "Translation Entry",
            {**filters, "status": "Pending"},
        )

        self.total_count = total
        self.translated_count = translated
        self.pending_count = pending

        if commit:
            self.db_update()

        return {
            "total_count": total,
            "translated_count": translated,
            "pending_count": pending,
        }