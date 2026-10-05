"""补齐 Wiki 编辑器斜杠命令菜单的中文译名。

wiki 的斜杠命令菜单（`SlashCommandsList.vue` 渲染每个命令的 `title` 与分组
`group`）与编辑器工具栏一样，把写死的英文直接渲染出来、没有套 `__()`。本次
已在源码中为其套上 `__()`（见 wiki 补丁），此处补齐其中尚缺译表的条目。编辑器
工具栏与气泡菜单的 label 已在 add_editor_translations 中覆盖。

保留的英文：`PDF` 等按惯例保留的格式/产品名。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    # 斜杠命令标题
    "Numbered List": "编号列表",
    "Diagram": "图表",
    "Link to Page": "链接到页面",
    # 斜杠命令分组标题
    "Lists": "列表",
    "Callouts": "标注",
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_wiki_slash_translations: applied {len(TRANSLATIONS)}")