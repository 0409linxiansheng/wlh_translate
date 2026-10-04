import re
import frappe

from wlh_translate.exporter.exporter import export_to_site
from wlh_translate.translator.dictionary import DictionaryTranslator
from wlh_translate.utils import progress


translator = DictionaryTranslator()

# 进度上报使用的任务 id，与 wlh_translate.api.translate_pending_entries 入队时一致。
TRANSLATE_JOB = "translate_pending_entries"

# 每处理这么多条上报一次进度。逐条上报的写入开销比翻译本身还大。
PROGRESS_STEP = 200


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


def _confirmed_translations():
    """
    返回 {原文: 译文}，用于给词典做批量预加载。

    只取已经有译文的条目，原文和译文都按去掉首尾空白后的值做键，
    与词典查询保持一致。
    """

    rows = frappe.get_all(
        "Translation Entry",
        filters={
            "status": ["in", ["Translated", "Reviewed"]]
        },
        fields=[
            "source_text",
            "translated_text"
        ]
    )

    confirmed = {}

    for row in rows:

        source = str(row.source_text or "").strip()
        translated = str(row.translated_text or "").strip()

        if not source or not translated:
            continue

        confirmed.setdefault(source, translated)

    return confirmed


def translate_pending(app_name=None):
    """
    处理所有 Pending 翻译。

    只有通过质量检查的结果才会变成 Translated。
    不合格的继续保持 Pending。

    app_name 给定时只处理该应用的条目。
    """

    print("WLH Translator Start")

    filters = {
        "status": "Pending",
        # 不可翻译的条目（图标类名、字段名、纯符号等）必然过不了质量
        # 检查，取出来只会被反复拒绝，所以直接排除。
        "is_translatable": 1,
    }

    if app_name:
        filters["app_name"] = app_name

    rows = frappe.get_all(
        "Translation Entry",
        filters=filters,
        fields=[
            "name",
            "source_text"
        ],
        order_by="creation asc"
    )

    total = len(rows)

    print(f"{total} pending entries to translate")

    progress.report(TRANSLATE_JOB, 0, total)

    translated_count = 0
    rejected_count = 0

    # 预加载一次已确认翻译。source_text 没有索引，逐条查询会退化成
    # 每条一次全表扫描，几千条要跑十几分钟。
    translator.prime(_confirmed_translations())

    try:

        for index, row in enumerate(rows, start=1):

            if index % PROGRESS_STEP == 0:
                progress.report(TRANSLATE_JOB, index, total)

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

    finally:
        # 不要把这个缓存留给后续的单条翻译请求
        translator.prime(None)
        progress.clear(TRANSLATE_JOB)

    if translated_count:
        # 译好的条目直接发布到站点，不需要用户再点一次「导出到站点」。
        # language 传 None：translate_pending 不按语言过滤，所以按各条
        # 自己的 language 分组发布。
        export_to_site(language=None, app_name=app_name, overwrite=True)

    print(f"Translated: {translated_count}")
    print(f"Rejected/Pending: {rejected_count}")
    print("WLH Translator Finished")

    # returned so the list view can report what the run did
    return {
        "translated": translated_count,
        "rejected": rejected_count,
    }


def get_translation(source_text):
    """
    对外提供统一翻译接口。
    """

    return translate_one(source_text)
