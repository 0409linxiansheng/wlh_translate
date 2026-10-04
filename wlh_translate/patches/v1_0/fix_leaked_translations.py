import frappe

from wlh_translate.exporter.exporter import apply_translation
from wlh_translate.importer.po_importer import load_catalogue
from wlh_translate.utils.language import has_cjk


# 官方 .po 里没有对应 msgstr 的残留外语条目（主要是 lms 的西班牙语），
# 只能在这里补齐。
MANUAL_FIXES = {
    "All Classes": "所有班级",
    "All Live Courses": "所有直播课程",
    "All Live Courses ({0})": "所有直播课程（{0}）",
    "Apply for Certificate": "申请证书",
    "Ask a Question": "提问",
    "Checkout Course": "去结算课程",
    "Classes": "班级",
    "Complete your {0} to access the courses.": "完成你的 {0} 以访问课程。",
    "Course Creators": "课程创建者",
    "Courses Mentored": "辅导的课程",
    "Creator": "创建者",
    "Evaluation On:": "评价于：",
    "Have a doubt?": "有疑问？",
    "Help us improve our course material.": "帮助我们改进课程材料。",
    "Hey, my name is": "你好，我是",
    "Hi {0}": "你好 {0}",
    "<li>Item {0} in row(s) {1} billed more than {2}</li>": "<li>第 {1} 行的物料 {0} 已开票数量超过 {2}</li>",
    "Live": "直播",
    "Manage the course": "管理课程",
    "Manage third party apps": "管理第三方应用",
    "Manage your apps": "管理你的应用",
    "Mark as Complete": "标记为已完成",
    "Mark as complete on moving to the next lesson": "进入下一课时时标记为已完成",
    "Mark as Incomplete": "标记为未完成",
    "No Classes": "暂无班级",
    "No Live Courses": "暂无直播课程",
    "Nothing to see here.": "这里没有内容。",
    "Open Network": "开放网络",
    "Other Courses": "其他课程",
    "People": "人员",
    "Pick a Slot": "选择时间段",
    "Press Cmd+Enter to post your comment": "按 Cmd+Enter 发布评论",
    "Profilee": "个人资料",
    "Reset the password for your account": "重置你的账户密码",
    "Review the course": "评价课程",
    "Slots": "时间段",
    "Submit for Review": "提交审核",
    "There are no live courses on this site.": "本站暂无直播课程。",
    "There are no slots available on this day.": "今天没有可用的时间段。",
    "This course requires you to complete an evaluation to get certified. Please pick a slot based on your convenience for the evaluations.": "本课程需要通过评价才能获得认证。请根据你的方便选择评价时间段。",
    "This lesson is not available for preview. As you are the Instructor of the course only you can see it.": "本课时不可预览。你是本课程的讲师，只有你可以看到它。",
    "To manage your authorized third party apps": "管理你已授权的第三方应用",
    "Type here. Use markdown to format.": "在此输入。使用 Markdown 格式化。",
    "Write a review": "写评价",
    "You have exceeded the maximum number of attempts allowed to appear for evaluations of this course.": "你已超出本课程允许参加评价的最大尝试次数。",
    "You haven't completed your profile.": "你尚未完成个人资料。",
    "Your course is currently under review. Once the review is complete, the System Admins will publish it on the website.": "你的课程正在审核中。审核完成后，系统管理员会将其发布到网站上。",
}


def execute():
    catalogue = load_catalogue()

    repaired = _repair_leaks(catalogue)

    if repaired:
        frappe.db.commit()

    frappe.clear_cache()

    print(f"fix_leaked_translations: repaired {repaired}")


def _repair_leaks(catalogue):
    """修正译文里完全没有中文的条目。"""
    rows = frappe.get_all(
        "Translation Entry",
        filters={
            "is_translatable": 1,
            "status": ["in", ["Translated", "Reviewed"]],
        },
        fields=["source_text", "translated_text"],
        limit_page_length=0,
    )

    targets = {}

    for row in rows:
        source = (row.source_text or "").strip()
        translated = (row.translated_text or "").strip()

        if not source or not translated or source == translated:
            continue

        if has_cjk(translated):
            continue

        good = catalogue.get(source)

        # 官方 .po 偶尔也会给出不含中文的坏译文（例如 "Hi {0}" -> "{0}"），
        # 这时以手工表为准。
        if not good or not has_cjk(good):
            good = MANUAL_FIXES.get(source) or good

        if good and has_cjk(good):
            targets[source] = good

    for source, good in targets.items():
        apply_translation(source, good)

    return len(targets)