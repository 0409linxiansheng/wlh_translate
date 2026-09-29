import frappe

from .business_dictionary import BUSINESS_DICT


DICT = {

    "Purchase": "采购",
    "Sales": "销售",

    "Order": "订单",
    "Invoice": "发票",

    "Supplier": "供应商",
    "Customer": "客户",

    "Item": "商品",
    "Stock": "库存",
    "Warehouse": "仓库",

    "Employee": "员工",
    "Company": "公司",

    "Project": "项目",
    "Task": "任务",

    "User": "用户",
    "Role": "角色",

    "Settings": "设置",
    "Setup": "设置",

    "Report": "报表",
    "Analysis": "分析",
    "Summary": "汇总",

    "View": "查看",
    "Create": "创建",
    "Import": "导入",
    "Export": "导出",

    "Full": "完整",
    "Name": "名称",
    "Number": "编号",
    "Date": "日期",
    "Amount": "金额",
    "Count": "数量",

}


class DictionaryTranslator:


    def __init__(self):
        # 批量翻译时预加载，避免每条原文都去查一次库
        self._confirmed = None


    def prime(self, translations):
        """
        预加载已确认翻译。

        source_text 上没有索引，逐条查询等于每次全表扫描，几千条要跑
        十几分钟。批量任务开始前用 {原文: 译文} 预加载一次即可。

        translations 传 None 表示恢复逐条查询。
        """
        self._confirmed = translations


    def translate(self, text):

        if not text:
            return None


        # 1. 业务完整匹配（最高优先级）
        if text in BUSINESS_DICT:
            return BUSINESS_DICT[text]


        # 2. 普通词典完整匹配
        if text in DICT:
            return DICT[text]


        # 3. 已确认翻译
        if self._confirmed is not None:
            result = self._confirmed.get(text)
        else:
            result = frappe.db.get_value(
                "Translation Entry",
                {
                    "source_text": text,
                    "status": "Translated"
                },
                "translated_text"
            )

        if result:
            return result


        # 4. 分词翻译
        parts = text.split(" ")

        translated = []

        changed = False


        for part in parts:

            clean = part.strip(",.()")


            if clean in BUSINESS_DICT:

                translated.append(
                    BUSINESS_DICT[clean]
                )

                changed = True


            elif clean in DICT:

                translated.append(
                    DICT[clean]
                )

                changed = True


            elif clean.endswith("s") and clean[:-1] in DICT:

                translated.append(
                    DICT[clean[:-1]]
                )

                changed = True


            else:

                translated.append(part)


        if changed:
            return "".join(translated)


        return None
