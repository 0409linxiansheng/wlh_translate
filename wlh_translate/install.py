import frappe
from frappe.translate import set_default_language

from wlh_translate.utils.language import DEFAULT_LANGUAGE


def after_install():
	"""安装完成后把站点切成中文。

	Frappe 取语言的顺序是：User.language → System Settings.language →
	站点配置里的 lang → "en"。只改站点默认值还不够，已经单独选过语言的
	用户会把它盖掉，所以这里一并处理。
	"""
	enable_language(DEFAULT_LANGUAGE)
	set_site_language(DEFAULT_LANGUAGE)
	set_user_language(DEFAULT_LANGUAGE)
	frappe.clear_cache()


def enable_language(language):
	"""启用语言，未启用的语言不会出现在语言选择列表里。"""
	if not frappe.db.exists("Language", language):
		return

	language_doc = frappe.get_doc("Language", language)
	if language_doc.enabled:
		return

	language_doc.enabled = 1
	language_doc.save(ignore_permissions=True)


def set_site_language(language):
	"""设置站点默认语言，并同步全局默认值（新建用户、报表等会用到）。"""
	frappe.db.set_single_value("System Settings", "language", language)
	set_default_language(language)


def set_user_language(language):
	"""让现有用户跟随中文，否则他们各自的设置会覆盖站点默认值。"""
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["!=", "Guest"]},
		pluck="name",
	)

	for user in users:
		frappe.db.set_value("User", user, "language", language)