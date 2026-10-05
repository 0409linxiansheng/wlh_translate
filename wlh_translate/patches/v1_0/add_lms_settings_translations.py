"""补上 LMS 设置页与用户菜单里缺失的中文译名。

LMS 的设置结构定义在纯数据文件 settingsStructure.js 里，字段标签、区块标题
和整段说明都是裸字符串。渲染组件 SettingFields.vue 对 field.label 和
field.description 都套了 __()，对 section.label 却没套——所以区块标题一律
英文（Notifications、Email Templates 等，即使译表里有译名也一样）。

本 patch 负责"译表缺失"这一半：把设置结构里的标签与说明、用户菜单里的
Clear Demo Data、以及一条硬编码说明补进站点翻译表；同时把 "Log out" 的两
个冲突译法（退出系统 / 退出登录）统一为「退出登录」。

"Raven" 属产品品牌名，按惯例保留英文，不在此补译。
本 patch 幂等，重复执行结果相同。
"""

import frappe

from wlh_translate.exporter.exporter import apply_translation

# 设置结构里的区块标题与字段标签。
LABELS = {
    "System Configurations": "系统配置",
    "Batch Confirmation Email Template": "批次确认邮件模板",
    "Certification Email Template": "证书邮件模板",
    "Livecode URL": "Livecode 地址",
    "Dwell Time": "停留时间",
    "Lesson dwell time (seconds)": "课时停留时长（秒）",
    "Enforcement": "强制完成",
    "Enforce video completion": "强制完成视频",
    "Enforce assignment completion": "强制完成作业",
    "Enforce quiz completion": "强制完成测验",
    "Badges": "徽章",
    "User Management": "用户管理",
    "Show USD equivalent amount": "显示美元等值金额",
    "Apply rounding on equivalent": "对等值金额取整",
    "Payment Reminders": "付款提醒",
    "Send payment reminders for batch": "为批次发送付款提醒",
    "Send payment reminders for course": "为课程发送付款提醒",
    "Gateways": "支付网关",
    "Signup": "注册",
    "Signup Consent HTML": "注册同意条款 HTML",
}

# 设置结构里的整段说明文字。
DESCRIPTIONS = {
    "Configure system-wide defaults, notifications, and contact information": "配置系统级默认项、通知和联系信息",
    "If enabled, users can access the course and batch lists without logging in.": "启用后，用户无需登录即可访问课程和批次列表。",
    "If enabled, users will no able to move forward in a video": "启用后，用户将无法在视频中快进。",
    "If checked, users will not be able to install the application as a Progressive Web App.": "勾选后，用户将无法把本应用安装为渐进式 Web 应用（PWA）。",
    "If enabled, it sends google calendar invite to the student for evaluations.": "启用后，会向学生发送用于评估的 Google 日历邀请。",
    "Notify members when a new course is published.": "发布新课程时通知成员。",
    "Notify members when a new batch is published.": "发布新批次时通知成员。",
    "Email template sent to students upon batch enrollment confirmation.": "学员确认加入批次时发送的邮件模板。",
    "Email template sent to students when they earn a certification.": "学员获得证书时发送的邮件模板。",
    "Users can reach out to this email for support or inquiries.": "用户可通过此邮箱寻求支持或咨询。",
    "Users can reach out to this URL for support or inquiries.": "用户可通过此网址寻求支持或咨询。",
    "If enabled, users can post job openings on the job board. Else only admins can post jobs.": "启用后，用户可在招聘板上发布职位；否则仅管理员可发布。",
    "Allows users to pick a profile cover image from Unsplash. https://unsplash.com/documentation#getting-started.": "允许用户从 Unsplash 选择个人主页封面图。https://unsplash.com/documentation#getting-started.",
    "Control how lessons are marked complete: dwell time and enforcement toggles for video, quiz, and assignment.": "控制课时的完成判定方式：视频、测验和作业的停留时长与强制完成开关。",
    "Seconds a learner must stay on a lesson before it auto-marks complete.": "学员需在课时停留多少秒后才自动标记为完成。",
    "When enabled, lessons that contain a video can only be marked complete by playing the video to the end. If the video fails to load, the dwell timer is used as a fallback.": "启用后，含视频的课时需把视频播放到结尾才能标记完成；若视频加载失败，则回退使用停留计时。",
    "When enabled, lessons with an assignment cannot be marked complete until the assignment is submitted.": "启用后，含作业的课时需先提交作业才能标记完成。",
    "When enabled, lessons with a quiz cannot be marked complete until the quiz is submitted.": "启用后，含测验的课时需先提交测验才能标记完成。",
    "Create badges and assign them to students to acknowledge their achievements": "创建徽章并授予学员，以表彰其成就",
    "Group courses under a category": "将课程归类到某个分类下",
    "Manage email accounts for incoming and outgoing mail": "管理收发邮件所用的邮箱账户",
    "Manage the email templates for your learning system": "管理学习系统的邮件模板",
    "Manage users by adding or inviting them, and assign roles to control their access and permissions": "通过添加或邀请来管理用户，并分配角色以控制其访问与权限",
    "Manage all your payment related settings and defaults": "管理所有与付款相关的设置和默认值",
    "Default currency used for course and batch pricing.": "课程和批次定价所用的默认货币。",
    "If enabled, it shows the USD equivalent amount for all transactions based on the current exchange rate.": "启用后，将按当前汇率显示所有交易的美元等值金额。",
    "If enabled, it applies rounding on the USD equivalent amount.": "启用后，会对美元等值金额取整。",
    "Payment gateway used to process course and batch purchases.": "用于处理课程和批次购买的支付网关。",
    "If enabled, GST will be applied to the price for students from India.": "启用后，将对印度学员的价格收取 GST。",
    "If enabled, it sends payment reminders to students who left the payment incomplete for a batch.": "启用后，会向未完成批次付款的学员发送付款提醒。",
    "If enabled, it sends payment reminders to students who left the payment incomplete for a course.": "启用后，会向未完成课程付款的学员发送付款提醒。",
    "Add and manage all your payment gateways": "添加并管理所有支付网关",
    "View all your payment transactions": "查看所有付款交易",
    "Manage discount coupons for courses and batches": "管理课程和批次的折扣优惠券",
    "Manage zoom accounts to conduct live classes from batches": "管理 Zoom 账户，以便通过批次开展直播课",
    "Manage Google Meet accounts to conduct live classes from batches": "管理 Google Meet 账户，以便通过批次开展直播课",
    "Automatically add your students and staff to Raven channels, by your own rules": "按自定义规则自动把学员和员工加入 Raven 频道",
    "Customize the brand name and logo to make the application your own": "自定义品牌名称和 Logo，让应用更具你的特色",
    "Choose the items you want to show in the sidebar": "选择要在侧边栏中显示的项",
    "Show the Courses link in the sidebar.": "在侧边栏显示「课程」链接。",
    "Show the Batches link in the sidebar.": "在侧边栏显示「批次」链接。",
    "Show the Programming Exercises link in the sidebar.": "在侧边栏显示「编程练习」链接。",
    "Show the Certifications link in the sidebar.": "在侧边栏显示「证书」链接。",
    "Show the Jobs link in the sidebar.": "在侧边栏显示「招聘」链接。",
    "Show the Statistics link in the sidebar.": "在侧边栏显示「统计」链接。",
    "Show the Notifications link in the sidebar.": "在侧边栏显示「通知」链接。",
    "Manage the settings related to user signup and registration": "管理用户注册与登记相关的设置",
    "Enable this option to identify the user category during signup.": "启用此选项以在注册时识别用户类别。",
    "New users will have to be manually registered by Admins.": "新用户将必须由管理员手动注册。",
    "Custom HTML shown on the signup page, e.g. for consent notices or terms of service.": "注册页显示的自定义 HTML，例如同意声明或服务条款。",
    "Manage the SEO settings to improve your website ranking on search engines": "管理 SEO 设置，以提升网站在搜索引擎中的排名",
    "Comma separated keywords for search engines to find your website.": "供搜索引擎发现本站的关键词，以逗号分隔。",
    "Default social-share image used when pages lack their own meta image.": "页面没有自己的 meta 图片时使用的默认社交分享图片。",
}

# 用户菜单与硬编码说明。
OTHERS = {
    "Clear Demo Data": "清除演示数据",
    "The HTML you add here will be shown on your sign up page.": "此处添加的 HTML 会显示在你的注册页上。",
}

# 同一源文本存在多种译法，统一到官方术语。
UNIFY = {
    "Log out": "退出登录",
}

TRANSLATIONS = {**LABELS, **DESCRIPTIONS, **OTHERS, **UNIFY}


def execute():
    for source, translated in TRANSLATIONS.items():
        apply_translation(source, translated)

    frappe.db.commit()
    frappe.clear_cache()

    print(f"add_lms_settings_translations: applied {len(TRANSLATIONS)}")