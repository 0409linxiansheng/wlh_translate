"""补齐并修正 Helpdesk 列表页筛选器/排序字段标签的中文译名。

get_filterable_fields()/sort_options()/get_quick_filters() 返回的字段 label
原先直接取自 DocField.label，未套 _()，导致筛选器与排序弹层显示英文。
源码已改为 _(field.label)（见 helpdesk 补丁），此处补齐/修正译表条目。

修正说明：
- Response By / Resolution By 是 HD Ticket 的 SLA 到期时间字段（Datetime），
  旧译「回复人」「分辨率」语义错误，改为「响应期限」「解决期限」。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

TRANSLATIONS = {
    "Assigned on": "分配于",
    "Response By": "响应期限",
    "Resolution By": "解决期限",
}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_helpdesk_field_label_translations: applied {len(TRANSLATIONS)}")