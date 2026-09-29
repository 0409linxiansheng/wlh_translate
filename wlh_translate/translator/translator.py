import re
import frappe

from wlh_translate.translator.dictionary import DictionaryTranslator


translator = DictionaryTranslator()


def is_good_translation(source_text, translated_text):
    """
    判断翻译结果是否达到可入库标准。

    原则：
    1. 必须有中文
    2. 不能保留明显的大量英文单词
    3. 不能出现中英文直接粘连
    4. 英文原文如果本身就是代码、缩写、数字等，不强制翻译
    5. 中文完整翻译优先
    """

    if not source_text or not translated_text:
        return False

    source_text = str(source_text).strip()
    translated_text = str(translated_text).strip()

    if not translated_text:
        return False

    # 完全没有变化
    if translated_text == source_text:
        return False

    # 必须包含中文
    if not re.search(r"[\u4e00-\u9fff]", translated_text):
        return False

    # ---------------------------------------------------------
    # 禁止明显的中英文直接粘连
    #
    # 例如：
    # 供应商FormTour
    # Active供应商
    # Campaign名称
    # GSTExempt采购
    # ---------------------------------------------------------
    if re.search(
        r"[\u4e00-\u9fff][A-Za-z]{2,}|[A-Za-z]{2,}[\u4e00-\u9fff]",
        translated_text
    ):
        return False

    # ---------------------------------------------------------
    # 找出翻译结果中的英文单词
    # ---------------------------------------------------------
    english_words = re.findall(
        r"\b[A-Za-z]{2,}\b",
        translated_text
    )

    # 允许少量 ERP/技术缩写
    allowed_words = {
        "ERP",
        "ERPNext",
        "POS",
        "CRM",
        "GST",
        "VAT",
        "API",
        "URL",
        "UOM",
        "RFQ",
        "SMS",
        "PDF",
        "CSV",
        "HTML",
        "JSON",
        "ID",
    }

    remaining_english = [
        word
        for word in english_words
        if word not in allowed_words
    ]

    # 有两个以上普通英文单词，基本可以判断为半翻译
    if len(remaining_english) >= 2:
        return False

    # 一个普通英文单词，如果原文没有这个单词作为技术词，也拒绝
    if len(remaining_english) == 1:
        word = remaining_english[0]

        source_words = set(
            re.findall(r"\b[A-Za-z]{2,}\b", source_text)
        )

        if word in source_words:
            return False

    # ---------------------------------------------------------
    # 英文字符比例过高，拒绝
    # ---------------------------------------------------------
    chinese_count = len(
        re.findall(r"[\u4e00-\u9fff]", translated_text)
    )

    english_count = len(
        re.findall(r"[A-Za-z]", translated_text)
    )

    if chinese_count == 0:
        return False

    if english_count > chinese_count:
        return False

    return True


def translate_one(source_text):
    """
    单条翻译。

    翻译顺序：
    1. 业务词典
    2. 通用词典
    3. 质量检查
    """

    if not source_text:
        return None

    source_text = str(source_text).strip()

    if not source_text:
        return None

    result = translator.translate(source_text)

    if not result:
        return None

    result = str(result).strip()

    if not is_good_translation(source_text, result):
        return None

    return result


def translate_pending():
    """
    处理所有 Pending 翻译。

    只有通过质量检查的结果才会变成 Translated。
    不合格的继续保持 Pending。
    """

    print("WLH Translator Start")

    rows = frappe.get_all(
        "Translation Entry",
        filters={
            "status": "Pending"
        },
        fields=[
            "name",
            "source_text"
        ],
        order_by="creation asc"
    )

    translated_count = 0
    rejected_count = 0

    for row in rows:

        source_text = row.source_text

        try:
            translated = translate_one(source_text)

            if not translated:
                rejected_count += 1
                continue

            doc = frappe.get_doc(
                "Translation Entry",
                row.name
            )

            doc.translated_text = translated
            doc.status = "Translated"

            doc.save(
                ignore_permissions=True
            )

            translated_count += 1

            print(
                f"Translated: {source_text} => {translated}"
            )

        except Exception as e:

            rejected_count += 1

            print(
                f"Rejected: {source_text} => {e}"
            )

    frappe.db.commit()

    print(f"Translated: {translated_count}")
    print(f"Rejected/Pending: {rejected_count}")
    print("WLH Translator Finished")


def get_translation(source_text):
    """
    对外提供统一翻译接口。
    """

    return translate_one(source_text)
