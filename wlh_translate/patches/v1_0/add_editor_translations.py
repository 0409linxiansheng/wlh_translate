"""补齐富文本编辑器工具栏按钮的中文译名。

frappe-ui 的编辑器工具栏（`frappe-ui/editor` 的 MenuItems.vue）直接把
`item.label` 渲染出来、没有套 `__()`，而这些 label 是 frappe-ui 源码里写死的
英文。受影响的界面：

  - Helpdesk 回复/评论编辑器（desk/src/components/editor/config.ts 已就地套
    `__()`，见帮助台补丁）；
  - Wiki 编辑器工具栏（wiki/frontend/.../WikiToolbar.vue，含其自定义按钮）；
  - frappe-ui 编辑器内置的表格浮动工具条（合并/拆分单元格等）。

这里一次性把上述英文 label 的译名写进站点译表（tabTranslation），使各处在套上
`__()` 后能直接显示中文。保留英文的：品牌/产品名与纯格式名（PDF 等按惯例保留
大写，仅按钮文案译为「插入 PDF」）。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

# 编辑器工具栏按钮文案（frappe-ui / wiki / helpdesk 共用同一批英文 label）
EDITOR = {
    "Bold": "粗体",
    "Strike": "删除线",
    "Bullet List": "项目符号列表",
    "Ordered List": "编号列表",
    "Task List": "任务列表",
    "Font Color": "字体颜色",
    "Align Left": "左对齐",
    "Align Center": "居中对齐",
    "Image / Gallery": "图片 / 图库",
    "Horizontal Rule": "水平分割线",
    "Clear formatting": "清除格式",
    "Code Block": "代码块",
    "Table of Contents": "目录",
    "Insert Image": "插入图片",
    "Insert PDF": "插入 PDF",
    "Insert Video": "插入视频",
    # frappe-ui 编辑器内置的表格工具条
    "Add Column Before": "在左侧插入列",
    "Add Column After": "在右侧插入列",
    "Add Row Before": "在上方插入行",
    "Add Row After": "在下方插入行",
    "Merge Cells": "合并单元格",
    "Split Cell": "拆分单元格",
    "Toggle Header Column": "切换标题列",
    "Toggle Header Row": "切换标题行",
    "Toggle Header Cell": "切换标题单元格",
    "Cell color": "单元格颜色",
}

TRANSLATIONS = {**EDITOR}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_editor_translations: applied {len(TRANSLATIONS)}")