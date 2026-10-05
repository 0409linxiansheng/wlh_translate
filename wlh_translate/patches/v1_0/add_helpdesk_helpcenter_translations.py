"""补齐 Helpdesk 框架帮助中心面板遗漏的中文译名。

frappe-ui 的 HelpCenter.vue（帮助弹窗内嵌面板）搜索占位与
“All articles” 标题原先为裸英文，已套 __()（见 helpdesk 补丁），
此处补齐译表条目。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    "Search articles...": "搜索文章…",
    "All articles": "所有文章",
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_helpdesk_helpcenter_translations: applied {len(TRANSLATIONS)}")