import frappe

from wlh_translate.utils.language import DEFAULT_LANGUAGE


# 扫描器已提取、但一直没有译文的最后一批界面文案。
# 这些字符串本身是人类可读文本（已通过 has_human_text 过滤），
# 只是一直没人翻译，所以停在 Pending。
TRANSLATIONS = {
    "No dynamic values found. Please add using": "未找到动态值。请使用以下方式添加",
    "Contribution %": "缴款比例",
    "Contribution Amount": "缴款金额",
    "A {0} exists between {1} and {2} (": "在 {1} 和 {2} 之间存在一个{0}（",
    "Backdated Leave Application is restricted. Please set the {} in {}": "不允许补录请假申请。请在 {} 中设置 {}",
    "Bulk attendance marking is already in progress for employee {0}. You can monitor the job status {1}": "员工 {0} 的批量考勤标记已在进行中。你可以在 {1} 查看任务状态",
    "The fraction of daily wages to be paid for half-day attendance": "半日出勤应支付的日薪比例",
    "Hey {0}": "你好 {0}",
    "Hi": "你好",
    "Please enroll for this course to view this lesson": "请先报名本课程以查看此课时",
    "Please provide your consent to proceed with the payment": "请确认同意以继续付款",
    "Please take appropriate action at {0}": "请在 {0} 采取相应操作",
    "The last day to schedule your evaluations is": "安排评价的最后一天是",
    "This program consists of {0} courses": "本项目包含 {0} 门课程",
    "We noticed that you started enrolling in the": "我们注意到你已开始报名",
    "You can only upload {0} files": "你最多只能上传 {0} 个文件",
    "You have already reviewed this course": "你已评价过本课程",
    "You have been enrolled in this batch": "你已加入本批次",
    "You have been enrolled in this course": "你已加入本课程",
    "You have exceeded the maximum number of attempts ({0}) for this quiz": "你已超出本测验的最大尝试次数（{0}）",
    "You must be enrolled in the course to submit a review": "你必须先加入课程才能提交评价",
    "You need to login first to enroll for this course": "你需要先登录才能报名本课程",
    "This cannot be undone. Deleting the space also removes:": "此操作无法撤销。删除该空间还会移除：",
}


def execute():
    filled = _fill_entries()
    published = _publish()

    if filled or published:
        frappe.db.commit()

    frappe.clear_cache()

    print(
        f"fill_pending_translations: "
        f"entries filled {filled}, published {published}"
    )


def _fill_entries():
    """把待译条目标记为已翻译，并写入译文。"""
    filled = 0

    for source_text, translated_text in TRANSLATIONS.items():
        names = frappe.get_all(
            "Translation Entry",
            filters={
                "source_text": source_text,
                "is_translatable": 1,
                "status": "Pending",
            },
            pluck="name",
        )

        for name in names:
            frappe.db.set_value(
                "Translation Entry",
                name,
                {
                    "translated_text": translated_text,
                    "status": "Translated",
                    "translation_source": "Manual",
                },
                update_modified=False,
            )
            filled += 1

    return filled


def _publish():
    """把译文写进 "Translation" 表。只填空缺，不覆盖已有译文。"""
    from wlh_translate.exporter.exporter import publish_one

    published = 0

    for source_text, translated_text in TRANSLATIONS.items():
        if publish_one(
            DEFAULT_LANGUAGE, source_text, translated_text, overwrite=False
        ) in ("inserted", "overwritten"):
            published += 1

    return published