"""补齐 Helpdesk 列表页（筛选器/排序/列设置）遗漏的中文译名。

Helpdesk 列表页的筛选器弹层、排序、列设置把写死的英文 label 直接渲染出来、
没有套 __()。本次已在源码中为其套上 __()（见 helpdesk 补丁），此处补齐
其中尚缺译表的条目。

保留的英文：@me、PDF、rem、px 等按惯例保留的记号/单位。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    # 筛选器摘要（filterSummary）里拼接的操作词
    "is": "是",
    "is not": "不是",
    "contains": "包含",
    "doesn't contain": "不包含",
    "in": "包括",
    "not in": "不包括",
    "between": "介于",
    "greater than": "大于",
    "less than": "小于",
    "greater than or equal to": "大于等于",
    "less than or equal to": "小于等于",
    # 操作符下拉（大小写与源码严格一致）
    "Greater Than or Equal To": "大于等于",
    # 其他
    "Add Filter (A)": "添加筛选器 (A)",
    "Width can be in number, pixel or rem (eg. 3, 30px, 10rem)": (
        "宽度可以是数字、像素或 rem（例如 3、30px、10rem）"
    ),
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_helpdesk_listview_translations: applied {len(TRANSLATIONS)}")
