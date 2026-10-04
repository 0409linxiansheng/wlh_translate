"""把同一个源文本的多种译法统一到官方 .po 术语。

同一个英文短语在不同应用、不同时间被译成了不同中文（例如 "Account" 既有
「科目」也有「账户」），界面文字就会随出现位置而变。官方 .po 是各应用自己
维护的权威译名，这里以它为准，把工作单和 "Translation" 表统一过去。

只处理官方 .po 给出中文译文的源文本；.po 里没有的保持原样，不做猜测。
本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation
from wlh_translate.importer.po_importer import load_catalogue
from wlh_translate.utils.language import has_cjk


def execute():
    catalogue = load_catalogue()

    unified = _unify_conflicts(catalogue)

    if unified:
        frappe.db.commit()

    frappe.clear_cache()

    print(f"unify_conflicting_translations: unified {unified}")


def _unify_conflicts(catalogue):
    """把译法多于一种的源文本统一到官方译文，返回处理条数。"""
    unified = 0

    for source, texts in _collect_variants().items():
        if len(texts) < 2:
            continue

        authoritative = catalogue.get(source)

        # .po 里没有，或给的是不含中文的坏译文，都不动。
        if not authoritative or not has_cjk(authoritative):
            continue

        if texts == {authoritative}:
            continue

        apply_translation(source, authoritative)
        unified += 1

    return unified


def _collect_variants():
    """{source_text: {译法, ...}}，只含已译条目。"""
    rows = frappe.get_all(
        "Translation Entry",
        filters={
            "is_translatable": 1,
            "status": ["in", ["Translated", "Reviewed"]],
        },
        fields=["source_text", "translated_text"],
        limit_page_length=0,
    )

    variants = {}

    for row in rows:
        source = (row.source_text or "").strip()
        translated = (row.translated_text or "").strip()

        if source and translated:
            variants.setdefault(source, set()).add(translated)

    return variants