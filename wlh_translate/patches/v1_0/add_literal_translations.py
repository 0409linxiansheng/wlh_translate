"""补上已套 __() 但翻译表里没有的硬编码文案的中文译名。

frappe-ui 与 Desk 里有几条文案一直以裸字符串渲染，所以扫描器从没见过它们，
翻译表里也就没有对应条目——即使给它们套上 __()，仍然会显示英文。
这里把这几条补进站点翻译表，并修正 "Assigned To" 的误译（原为「创建待办」，
应为「分配给」，与 "Assigned to" 的既有译法保持一致）。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    "No data to show": "暂无可显示的数据",
    "Save Current Filter": "保存当前筛选器",
    "Add Sidebar Item": "添加侧边栏项目",
    "Assigned To": "分配给",
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_literal_translations: applied {len(TRANSLATIONS)}")