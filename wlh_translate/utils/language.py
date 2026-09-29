import frappe


# Default target language for scanned resources. This must be a language code
# known to Frappe ("zh" for Simplified Chinese, not "zh-CN").
DEFAULT_LANGUAGE = "zh"


# Frappe identifies languages with its own codes ("zh", "zh-TW"), not with
# BCP-47 region codes ("zh-CN"). Translation Entry rows and the "Translation"
# doctype therefore have to agree on the exact code, otherwise exported
# entries are never matched at runtime.
LANGUAGE_ALIASES = {
    "zh_cn": "zh",
    "zh-cn": "zh",
    "zh_hans": "zh",
    "zh-hans": "zh",
    "zh_hans_cn": "zh",
    "zh-hans-cn": "zh",
    "zh_tw": "zh-TW",
    "zh-tw": "zh-TW",
    "zh_hant": "zh-TW",
    "zh-hant": "zh-TW",
}


def normalize_language(language):
    """Map a language value onto the code used by Frappe's Language doctype."""
    if not language:
        return ""

    language = str(language).strip()

    return LANGUAGE_ALIASES.get(language.lower(), language)


def language_aliases(language):
    """
    Return every spelling that may refer to the same Frappe language.

    Used when querying existing rows, so that data written before the
    language code was normalized ("zh-CN") is still found.
    """
    normalized = normalize_language(language)

    aliases = {normalized}
    original = str(language).strip() if language else ""

    if original:
        aliases.add(original)

    for alias, target in LANGUAGE_ALIASES.items():
        if target == normalized:
            aliases.add(alias)

    return sorted(alias for alias in aliases if alias)


def ensure_language(language):
    """
    Normalize a language and make sure Frappe knows about it.

    Writing an unknown language into "Translation" fails its Link
    validation, so fail early with a readable message instead.
    """
    normalized = normalize_language(language)

    if not normalized:
        frappe.throw("Language is required")

    if not frappe.db.exists("Language", normalized):
        frappe.throw(
            f"Language {normalized!r} does not exist. "
            "Use a language code known to Frappe, for example 'zh'."
        )

    return normalized