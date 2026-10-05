"""补上 LMS 前端剩余缺失的中文译名（一次性清尾）。

这批条目来自对 apps/lms/frontend/src 的完整性扫描：源码里已经套了 __()，
但站点翻译表（tabTranslation，language=zh）里没有对应译名，所以显示英文。
扫描范围包括 .vue / .ts / .js / .tsx / .jsx（跳过 tests / node_modules /
e2e / cypress / assets）。

另有一批裸数据字符串：它们本身不带 __()，靠渲染组件包裹，扫描器看不见，
因此单独核验后一并补上（LessonHelp 的 5 组问答、Exercises）。

保留英文（不在此补译）：
  - 品牌/产品名：Raven、YouTube、Vimeo、Unsplash、Google、Zoom、Meet；
  - 代码/格式名：PDF、URL、HTML、BackSpace；
  - 键盘按键名：esc。

本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

# ---------------------------------------------------------------
# Raven 集成（品牌名 Raven 保留英文）
# ---------------------------------------------------------------
RAVEN = {
    "A condition here was written for an older version and can no longer be applied. Remove it and add the condition you want.": "此处的某个条件是为旧版本编写的，已无法再应用。请将其移除，然后添加你想要的条件。",
    "Add Condition": "添加条件",
    "Add Condition Group": "添加条件组",
    "Add one to give this workspace its first members.": "添加一个成员，为这个工作区引入首批成员。",
    "Added by rules": "由规则添加",
    "All channels": "所有频道",
    "All members": "所有成员",
    "Anyone matching these is kept in this channel, and in its workspace.": "符合这些条件的成员会保留在此频道及其所在工作区中。",
    "Channel created": "频道已创建",
    "Channel saved": "频道已保存",
    "Condition actions": "条件操作",
    "Condition types could not be loaded. Reload the page and try again.": "无法加载条件类型。请重新加载页面后再试。",
    "Condition types could not be loaded. Reload the page to try again.": "无法加载条件类型。请重新加载页面后再试。",
    "Could not change the visibility": "无法更改可见性",
    "Could not create the channel": "无法创建频道",
    "Could not create the workspace": "无法创建工作区",
    "Could not load the members": "无法加载成员",
    "Could not load the workspace": "无法加载工作区",
    "Could not load this channel": "无法加载此频道",
    "Could not load this workspace": "无法加载此工作区",
    "Could not rename the workspace": "无法重命名工作区",
    "Could not save the channel": "无法保存频道",
    "Could not update the channel": "无法更新频道",
    "Enable Raven Integration": "启用 Raven 集成",
    "Every member of this workspace was added by a rule.": "此工作区的所有成员均由规则添加。",
    "Every member of {0} was added by a rule.": "{0} 的所有成员均由规则添加。",
    "Filter by added by rules": "按「由规则添加」筛选",
    "Filter by channel": "按频道筛选",
    "Filter by state": "按状态筛选",
    "Finish every condition before saving.": "请先完成所有条件再保存。",
    "Fix the problems listed under the conditions first": "请先解决条件下列出的问题",
    "Give this channel a name before saving": "保存前请先为此频道命名",
    "Install the {0} app to enable this integration.": "安装 {0} 应用以启用此集成。",
    "It may have been deleted, or the request did not get through.": "它可能已被删除，或请求未能送达。",
    "Managed by {0}": "由 {0} 管理",
    "Membership conditions": "成员条件",
    "New Channel": "新建频道",
    "No member of this workspace was added by a rule.": "此工作区没有成员是由规则添加的。",
    "No member of {0} was added by a rule.": "{0} 没有成员是由规则添加的。",
    "No workspace to create this channel in. Go back and start again from a workspace's Channels tab.": "没有可用于创建此频道的工作区。请返回，并从某个工作区的「频道」标签页重新开始。",
    "Nobody is in a channel of this workspace yet.": "此工作区还没有人加入任何频道。",
    "Nobody is in {0} anymore.": "{0} 中已无人。",
    "Not added by rules": "非规则添加",
    "Not linked": "未关联",
    "Open in Raven": "在 Raven 中打开",
    "Save anyway": "仍然保存",
    "Save this workspace before adding channels to it.": "请先保存此工作区，再向其添加频道。",
    "Save without checking who this affects?": "要在不检查影响对象的情况下保存吗？",
    "Search workspaces": "搜索工作区",
    "Sync members into channels by rule.": "按规则把成员同步到频道。",
    "Sync members of {0}": "同步 {0} 的成员",
    "The conditions on {0} could not be worked out, so there is no telling who this change adds or removes. It usually means the app that supplies a condition type is no longer installed. Saving applies the change anyway.": "无法解析 {0} 上的条件，因此无法确定此次更改会添加或移除哪些人。这通常意味着提供某个条件类型的应用已不再安装。保存仍会应用此更改。",
    "The list did not come through. Try again in a moment.": "列表未能加载。请稍后再试。",
    "These conditions were saved joining some rows with and and others with or. This screen shows one joiner per group, so it cannot draw that. They are written back as they are until you move a joiner or change the rows, either of which sets one joiner for the whole group.": "这些条件保存时，部分行用「and」连接，部分行用「or」连接。此界面每组只显示一个连接符，因此无法呈现该情况。在你移动某个连接符或更改行之前，它们会按原样写回；而这两种操作都会为整组设置同一个连接符。",
    "This channel is missing in Raven, so its conditions cannot be changed.": "此频道在 Raven 中不存在，因此无法更改其条件。",
    "This deletes the channel mapping and its conditions, and removes everyone those conditions added to the channel. Anyone added by hand in Raven stays. This action cannot be undone.": "这会删除该频道的映射及其条件，并移除由这些条件添加到该频道的所有人。在 Raven 中手动添加的人会保留。此操作无法撤销。",
    "This deletes the workspace mapping and every channel mapping under it, with their conditions, and removes everyone those conditions added to its channels. Anyone added by hand in Raven stays. This action cannot be undone.": "这会删除该工作区的映射及其下的所有频道映射（连同其条件），并移除由这些条件添加到此工作区各频道的人。在 Raven 中手动添加的人会保留。此操作无法撤销。",
    "Workspace created": "工作区已创建",
    "You have unsaved changes, leave anyway?": "你有未保存的更改，仍要离开吗？",
}

# ---------------------------------------------------------------
# 测验 / 作业（Quiz、Assignment）
# ---------------------------------------------------------------
QUIZ = {
    "Closes": "关闭",
    "Opens": "开放",
    "attempt": "次尝试",
    "attempts": "次尝试",
    "attempted": "已作答",
    "unattempted": "未作答",
    "event": "条事件",
    "events": "条事件",
    "mark": "分",
    "marks": "分",
    "min": "分钟",
    "question": "道题",
    "questions": "道题",
    "violation": "次违规",
    "violations": "次违规",
    "The schedule for this assignment has ended.": "此作业的提交时间已结束。",
    "The schedule for this quiz has ended.": "此测验的开放时间已结束。",
    "This assignment opens on {0}.": "此作业将于 {0} 开放。",
    "This quiz opens on {0}.": "此测验将于 {0} 开放。",
}

# ---------------------------------------------------------------
# 统计页（Statistics）
# ---------------------------------------------------------------
STATISTICS = {
    "Certifications per day": "每日认证数",
    "Completions": "完成数",
    "Course Completion": "课程完成情况",
    "Enrollments per day": "每日报名数",
    "Signups per day": "每日注册数",
}

# ---------------------------------------------------------------
# 表单（作业 / 测验 / 个人画像）
# ---------------------------------------------------------------
FORMS = {
    "Enable Scheduling": "启用日程安排",
    "Optional. Leave empty to keep the assignment open after it starts.": "可选。留空则作业开始后保持一直可提交。",
    "Optional. Leave empty to keep the quiz open after it starts.": "可选。留空则测验开始后保持一直开放。",
    "Persona": "个人画像",
    "Restrict when learners can start and submit this quiz.": "限制学员可开始和提交此测验的时间。",
    "Restrict when learners can submit this assignment.": "限制学员可提交此作业的时间。",
    "Schedule End": "结束时间",
    "Schedule End must be after Schedule Start.": "结束时间必须晚于开始时间。",
    "Schedule Start": "开始时间",
    "Schedule Start is required when scheduling is enabled.": "启用日程安排时必须填写开始时间。",
}

# ---------------------------------------------------------------
# 页面与零散文案
# ---------------------------------------------------------------
PAGES = {
    "Could not load this certification.": "无法加载此证书。",
    "Could not load your saved progress": "无法加载你保存的进度",
    "Course content coming soon!": "课程内容即将上线！",
    "This chapter has no lesson to play yet.": "此章节还没有可播放的课时。",
    "This lesson has no content to play yet.": "此课时还没有可播放的内容。",
    "This lesson will start from the beginning. Reload the page to try resuming where you left off.": "此课时将从头开始。请重新加载页面，以尝试从上次中断处继续。",
    "Please login to access this page.": "请登录后访问此页面。",
    "No {0} match this filter": "没有符合条件的{0}",
    "and {0} more: {1}": "另有 {0} 项：{1}",
    "Only image file is allowed.": "仅允许上传图片文件。",
    "search by keyword": "按关键词搜索",
    "sections": "个章节",
    "The last day to schedule your evaluations is ": "安排评估的最后一天是 ",
}

# ---------------------------------------------------------------
# 裸数据字符串（模板处才套 __()，扫描器看不见）
# ---------------------------------------------------------------
BARE = {
    "Exercises": "练习",
    "What are Instructor Notes?": "什么是讲师笔记？",
    "Instructor Notes are private notes that only instructors can see. They can be used to provide additional context or guidance for the lesson.": "讲师笔记是只有讲师可见的私密笔记，可用于为课时提供额外的背景说明或指导。",
    "How to add a Quiz?": "如何添加测验？",
    "Click on the add icon in the editor and select Quiz from the menu. It opens up a dialog, where you can either select a quiz from the list or create a new quiz. When you select the Create New option it redirects you to the quiz creation page.": "在编辑器中点击添加图标，然后从菜单中选择「测验」。随后会弹出对话框，你可以从列表中选择测验，或新建测验。选择「新建」选项后，会跳转到测验创建页面。",
    "How to upload content from your system?": "如何从本地上传内容？",
    "To upload Image, Video, Audio or PDF from your system, click on the add icon and select upload from the menu. Then choose the file you want to add to the lesson and it gets added to your lesson.": "要从本地上传图片、视频、音频或 PDF，请点击添加图标，然后从菜单中选择「上传」。接着选择要添加到课时的文件，它就会被添加到你的课时中。",
    "How to add a YouTube Video?": "如何添加 YouTube 视频？",
    "Copy the URL of the video from YouTube and paste it in the editor.": "复制 YouTube 视频的 URL，然后粘贴到编辑器中。",
    "How to remove an embed?": "如何移除嵌入内容？",
    "To remove an embed like YouTube or Vimeo, put your cursor on the line below the embed, then drag your mouse cursor upwards to select the embed. Once the embed is selected press BackSpace.": "要移除 YouTube 或 Vimeo 之类的嵌入内容，请把光标放在嵌入内容下方的那一行，然后向上拖动鼠标以选中该嵌入内容。选中后按 BackSpace 键即可删除。",
}

TRANSLATIONS = {**RAVEN, **QUIZ, **STATISTICS, **FORMS, **PAGES, **BARE}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_lms_remaining_translations: applied {len(TRANSLATIONS)}")