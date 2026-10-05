"""补齐 Helpdesk 知识库客户页遗漏的中文译名。

KnowledgeBaseCustomer.vue 的标题与搜索占位、CategoryFolder.vue 的
article/articles 计数原先为裸英文，已套 __()（见 helpdesk 补丁），
此处补齐译表条目。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    "Ask a question...": "输入你的问题…",
    "article": "篇文章",
    "articles": "篇文章",
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_helpdesk_kb_translations: applied {len(TRANSLATIONS)}")