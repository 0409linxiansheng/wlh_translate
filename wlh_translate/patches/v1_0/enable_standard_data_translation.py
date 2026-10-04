"""把标准数据接进框架的列表首列翻译。

框架的列表首列只在单据被标记 translated_doctype 时才翻译记录名，判断写在
frappe/frappe/public/js/frappe/list/list_view.js 里：

    translated_doctypes.includes(df.options)

配套的前端补丁是 wlh_translate/public/js/name_column_i18n.bundle.js。标准数据
里还有几类没被标上，这里补标记，并补齐缺失的中文译名。覆盖所有已安装应用：
前端补丁只看 translated_doctype 标记，译文表也按源文本全局生效，所以不区分
应用 —— payments / telephony / webshop / whatsapp / wiki 这几个没有官方
zh.po 的应用，界面文字由 wlh_translate 扫描后写进 "Translation"，同样生效。

标记用 Property Setter 而不是直接改 DocType：DocType 的 translated_doctype
会随 bench migrate 从应用的 JSON 重新同步，手改留不住；Property Setter 由
frappe.translate.get_translated_doctypes() 一并读取，既能生效也不会被
migrate 覆盖。本 patch 幂等，重复执行不会产生重复数据。
"""

import frappe

# 需要翻译记录名、但标准数据里没有标记的单据。
#
# 本 patch 不区分应用：前端补丁只看 translated_doctype 标记，译文表也是全局的，
# 所以 frappe / erpnext 之外的应用用同一套机制。下面按应用分组，方便以后增补。
TRANSLATED_DOCTYPES = (
	# frappe / erpnext
	"Workspace",
	"Print Style",
	"Party Type",
	"Workflow Action Master",
	# frappe / erpnext：报表与看板
	"Dashboard Chart",
	"Number Card",
	"Dashboard",
	# frappe / erpnext：基础资料
	"Currency",
	"Warehouse",
	"Company",
	"Workflow",
	"Custom Field",
	"Property Setter",
	"Terms and Conditions",
	"Letter Head",
	"Department",
	"Branch",
	"Cost Center",
	"Account",
	"Sales Taxes and Charges Template",
	"Purchase Taxes and Charges Template",
	"Payment Terms Template",
	"Shipping Rule",
	"Campaign",
	"Sales Partner",
	"Brand",
	"Asset Category",
	"Holiday List",
	"Employee Grade",
	# helpdesk
	"HD Ticket Priority",
	"HD Ticket Status",
	"HD Ticket Type",
	"HD Ticket Feedback Option",
	"HD Agent Status",
	"HD Article Category",
	"HD Team",
	# hrms
	"Job Applicant Source",
	"Offer Term",
	# lms：行业、职能、课程分类与来源
	"Industry",
	"Function",
	"LMS Category",
	"LMS Source",
	# builder：区块模板
	"Block Template",
)

# 已存在的错误译名。MISSING_TRANSLATIONS 只补空缺，盖不掉这些，所以单独列出
# 并允许覆盖。
CORRECTIONS = {
	# builder 区块模板名，源自 .po 的误译，应为品牌原名
	"YouTube": "YouTube",
}

# 缺失的中文译名。
#
# 国家与地区名一次覆盖三处：Country 的记录名、Address Template 的记录名、
# Territory 的 "China" —— "Translation" 按源文本全局生效，所以只写一份。
MISSING_TRANSLATIONS = {
	# 仪表盘图表名。官方 zh.po 没有收录这些记录名，只能在这里补。
	"Notifications By Type": "按类型的通知",
	"Background Job Activity": "后台任务活动",
	"Email Activity": "邮件活动",
	"Webpage Views": "网页浏览量",
	"Timesheet Activity Breakup": "工时表活动明细",
	"Claims by Type": "按类型的报销单",
	"Hiring vs Attrition Count": "招聘与流失人数对比",
	"Employees by Age": "按年龄的员工分布",
	"Department wise Expense Claims": "按部门的费用报销",
	"Employee Advance Status": "员工预支状态",
	"Employees by Type": "按类型的员工分布",
	"Employees by Branch": "按分支机构的员工分布",
	"Employees by Grade": "按职级的员工分布",
	"Job Applicants by Country": "按国家的求职者",
	"Shift Assignment Breakup": "轮班分配明细",
	"Department wise Timesheet Hours": "按部门的工时",
	"Y-O-Y Promotions": "晋升同比",
	"Training Type": "培训类型",
	"Y-O-Y Transfers": "调动同比",
	"Job Application Frequency": "求职申请频次",
	"Job Offer Status": "录用通知状态",
	"Job Applicant Pipeline": "求职者漏斗",
	"Oldest Items": "最久未动物料",
	"Warehouse wise Stock Value": "按仓库的库存价值",
	"New Signups": "新增注册",
	"Designation Wise Salary(Last Month)": "按职位的薪资（上月）",
	"Department Wise Salary(Last Month)": "按部门的薪资（上月）",
	"Designation Wise Openings": "按职位的空缺",
	"Designation Wise Employee Count": "按职位的员工人数",
	"Department Wise Employee Count": "按部门的员工人数",
	"Job Application Status": "求职申请状态",
	"Gender Diversity Ratio": "性别多样性比例",
	"Item Shortage Summary": "物料短缺汇总",
	"Delivery Trends": "交货趋势",
	"Top Suppliers": "主要供应商",
	"Material Request Analysis": "物料申请分析",
	"Top Customers": "主要客户",
	"Item-wise Annual Sales": "按物料的年度销售额",
	"Territory Wise Sales": "按区域的销售额",
	"Territory Wise Opportunity Count": "按区域的商机数",
	"Opportunities via Campaigns": "来自营销活动的商机",
	"Opportunity Trends": "商机趋势",
	"Incoming Leads": "新增线索",
	"Accounts Payable Ageing": "应付账款账龄",
	"Accounts Receivable Ageing": "应收账款账龄",
	"Outgoing Bills (Sales Invoice)": "销项账单（销售发票）",
	"Incoming Bills (Purchase Invoice)": "进项账单（采购发票）",
	"Location-wise Asset Value": "按地点的资产价值",
	"Category-wise Asset Value": "按类别的资产价值",
	# 数字卡片名
	"Total Applicants (This month)": "申请总人数（本月）",
	"Total Employees": "员工总数",
	"Monthly Quality Inspection": "月度质量检查",
	"Ongoing Job Card": "进行中的作业卡",
	"Monthly Completed Work Order": "月度已完成工单",
	"Monthly Total Work Order": "月度工单总数",
	# 仪表盘名
	"Human Resource": "人力资源",
	"Employee Lifecycle": "员工生命周期",
	# 打印样式
	"Classic": "经典",
	"Modern": "现代",
	"Monochrome": "单色",
	"Redesign": "重新设计",
	# 报表
	"ToDo": "待办",
	"Wiki Broken Links": "Wiki 失效链接",
	# 打印格式
	"Salary Slip based on Timesheet": "基于工时单的工资单",
	# 角色
	"Employee Self Service": "员工自助",
	"TP Manager": "TP 经理",
	"TP Agent": "TP 专员",
	"Wiki User": "Wiki 用户",
	"Wiki Manager": "Wiki 管理员",
	"Wiki Approver": "Wiki 审批人",
	# 通知
	"Reminder for Certificate Evaluation": "证书评估提醒",
	# helpdesk：工单评价选项
	"Instant, top-notch help": "响应即时，支持一流",
	"Exceptional support experience": "支持体验极佳",
	"Prompt, informative support": "响应迅速，信息充分",
	"Quick and precise solutions": "解决方案快速准确",
	"Helpful answers, reasonable wait": "答复有帮助，等待时间合理",
	"Clear guidance given": "指引清晰",
	"Adequate help, bit slow": "帮助尚可，稍显缓慢",
	"Delayed response time": "响应时间偏长",
	"No resolution provided": "未提供解决方案",
	"Response did not help": "答复没有帮助",
	# lms：课程分类、来源、行业、职能
	"Personal Development": "个人成长",
	"Design": "设计",
	"Business": "商业",
	"Finance": "金融",
	"Web Development": "Web 开发",
	"Frontend": "前端",
	"Google Search": "谷歌搜索",
	"Friend/Colleague/Connection": "朋友 / 同事 / 人脉",
	"Newsletter": "邮件订阅",
	"Security & Law Enforcement": "安全与执法",
	"Transportation & Logistics": "运输与物流",
	"Staffing & Recruiting": "人力派遣与招聘",
	"Retail, Fashion & FMCG": "零售、时尚与快消",
	"Public Service & NGOs": "公共服务与非政府组织",
	"Media & Entertainment": "媒体与娱乐",
	"Manufacturing & Production": "制造与生产",
	"IT / Ecommerce / Internet": "IT / 电商 / 互联网",
	"Hospitality & Tourism": "酒店与旅游",
	"Health & Medical": "健康与医疗",
	"Food & Beverages": "食品与饮料",
	"Engineering": "工程",
	"Energy & Utilities": "能源与公用事业",
	"Education & Training": "教育与培训",
	"Consulting & Professional Services": "咨询与专业服务",
	"Construction & Real Estate": "建筑与房地产",
	"Biotech & Pharmaceuticals": "生物技术与制药",
	"Banking, Financial Services & Insurance": "银行、金融服务与保险",
	"Aviation & Aerospace": "航空与航天",
	"Architecture": "建筑设计",
	"Agriculture, Fishing & Forestry": "农业、渔业与林业",
	"Ads, Marketing, PR & Events": "广告、市场营销、公关与活动",
	"Supply Chain, Logistics Strategy & Management": "供应链、物流战略与管理",
	"Sales & Customer Service": "销售与客户服务",
	"Research, Training & Education": "研究、培训与教育",
	"Operations & Admin": "运营与行政",
	"Marketing, Advertising & PR": "市场营销、广告与公关",
	"Human Resource & Recruiting": "人力资源与招聘",
	"Finance, Investment & Accounting": "财务、投资与会计",
	"Engineering (Software & IT)": "工程（软件与 IT）",
	"Engineering (Non Software)": "工程（非软件）",
	"Design & Creative": "设计与创意",
	"Data & Analytics": "数据与分析",
	# builder：区块模板
	"Navbar 1": "导航栏 1",
	"Navbar 2": "导航栏 2",
	"Theme Switcher": "主题切换器",
	"Hero 1": "首屏 1",
	"Hero 2": "首屏 2",
	"Testimonial 1": "客户评价 1",
	"Footer 1": "页脚 1",
	"Quick Stack": "快速堆叠",
	"Quick Grid": "快速网格",
	"Paragraph": "段落",
	"Text Link": "文本链接",
	"Blockquote": "引用块",
	"Form 1": "表单 1",
	"Form 2": "表单 2",
	"Form 3": "表单 3",
	"Embed": "嵌入",
	# hrms：车辆保养项目
	"Oil Change": "更换机油",
	"Engine Oil": "发动机机油",
	"Clutch Plate": "离合器片",
	"Brake Pad": "刹车片",
	"Brake Oil": "刹车油",
	# 国家与地区
	"Afghanistan": "阿富汗",
	"Åland Islands": "奥兰群岛",
	"Albania": "阿尔巴尼亚",
	"Algeria": "阿尔及利亚",
	"American Samoa": "美属萨摩亚",
	"Andorra": "安道尔",
	"Angola": "安哥拉",
	"Anguilla": "安圭拉",
	"Antarctica": "南极洲",
	"Antigua and Barbuda": "安提瓜和巴布达",
	"Argentina": "阿根廷",
	"Armenia": "亚美尼亚",
	"Aruba": "阿鲁巴",
	"Australia": "澳大利亚",
	"Austria": "奥地利",
	"Azerbaijan": "阿塞拜疆",
	"Bahamas": "巴哈马",
	"Bahrain": "巴林",
	"Bangladesh": "孟加拉国",
	"Barbados": "巴巴多斯",
	"Belarus": "白俄罗斯",
	"Belgium": "比利时",
	"Belize": "伯利兹",
	"Benin": "贝宁",
	"Bermuda": "百慕大",
	"Bhutan": "不丹",
	"Bolivia, Plurinational State of": "多民族玻利维亚国",
	"Bonaire, Sint Eustatius and Saba": "博纳尔、圣尤斯特歇斯和萨巴",
	"Bosnia and Herzegovina": "波斯尼亚和黑塞哥维那",
	"Botswana": "博茨瓦纳",
	"Bouvet Island": "布韦岛",
	"Brazil": "巴西",
	"British Indian Ocean Territory": "英属印度洋领地",
	"Brunei Darussalam": "文莱",
	"Bulgaria": "保加利亚",
	"Burkina Faso": "布基纳法索",
	"Burundi": "布隆迪",
	"Cambodia": "柬埔寨",
	"Cameroon": "喀麦隆",
	"Canada": "加拿大",
	"Cape Verde": "佛得角",
	"Cayman Islands": "开曼群岛",
	"Central African Republic": "中非共和国",
	"Chad": "乍得",
	"Chile": "智利",
	"China": "中国",
	"Christmas Island": "圣诞岛",
	"Cocos (Keeling) Islands": "科科斯（基林）群岛",
	"Colombia": "哥伦比亚",
	"Comoros": "科摩罗",
	"Congo": "刚果",
	"Congo, The Democratic Republic of the": "刚果民主共和国",
	"Cook Islands": "库克群岛",
	"Costa Rica": "哥斯达黎加",
	"Croatia": "克罗地亚",
	"Cuba": "古巴",
	"Curaçao": "库拉索",
	"Cyprus": "塞浦路斯",
	"Czech Republic": "捷克",
	"Denmark": "丹麦",
	"Djibouti": "吉布提",
	"Dominica": "多米尼克",
	"Dominican Republic": "多米尼加共和国",
	"Ecuador": "厄瓜多尔",
	"Egypt": "埃及",
	"El Salvador": "萨尔瓦多",
	"Equatorial Guinea": "赤道几内亚",
	"Eritrea": "厄立特里亚",
	"Estonia": "爱沙尼亚",
	"Ethiopia": "埃塞俄比亚",
	"Falkland Islands (Malvinas)": "福克兰群岛（马尔维纳斯）",
	"Faroe Islands": "法罗群岛",
	"Fiji": "斐济",
	"Finland": "芬兰",
	"France": "法国",
	"French Guiana": "法属圭亚那",
	"French Polynesia": "法属波利尼西亚",
	"French Southern Territories": "法属南部领地",
	"Gabon": "加蓬",
	"Gambia": "冈比亚",
	"Georgia": "格鲁吉亚",
	"Germany": "德国",
	"Ghana": "加纳",
	"Gibraltar": "直布罗陀",
	"Greece": "希腊",
	"Greenland": "格陵兰",
	"Grenada": "格林纳达",
	"Guadeloupe": "瓜德罗普",
	"Guam": "关岛",
	"Guatemala": "危地马拉",
	"Guernsey": "根西",
	"Guinea": "几内亚",
	"Guinea-Bissau": "几内亚比绍",
	"Guyana": "圭亚那",
	"Haiti": "海地",
	"Heard Island and McDonald Islands": "赫德岛和麦克唐纳群岛",
	"Holy See (Vatican City State)": "教廷（梵蒂冈城国）",
	"Honduras": "洪都拉斯",
	"Hong Kong": "中国香港",
	"Hungary": "匈牙利",
	"Iceland": "冰岛",
	"India": "印度",
	"Indonesia": "印度尼西亚",
	"Iran": "伊朗",
	"Iraq": "伊拉克",
	"Ireland": "爱尔兰",
	"Isle of Man": "马恩岛",
	"Israel": "以色列",
	"Italy": "意大利",
	"Ivory Coast": "科特迪瓦",
	"Jamaica": "牙买加",
	"Japan": "日本",
	"Jersey": "泽西",
	"Jordan": "约旦",
	"Kazakhstan": "哈萨克斯坦",
	"Kenya": "肯尼亚",
	"Kiribati": "基里巴斯",
	"Korea, Democratic Peoples Republic of": "朝鲜",
	"Korea, Republic of": "韩国",
	"Kosovo": "科索沃",
	"Kuwait": "科威特",
	"Kyrgyzstan": "吉尔吉斯斯坦",
	"Lao Peoples Democratic Republic": "老挝",
	"Latvia": "拉脱维亚",
	"Lebanon": "黎巴嫩",
	"Lesotho": "莱索托",
	"Liberia": "利比里亚",
	"Libya": "利比亚",
	"Liechtenstein": "列支敦士登",
	"Lithuania": "立陶宛",
	"Luxembourg": "卢森堡",
	"Macao": "中国澳门",
	"Macedonia": "北马其顿",
	"Madagascar": "马达加斯加",
	"Malawi": "马拉维",
	"Malaysia": "马来西亚",
	"Maldives": "马尔代夫",
	"Mali": "马里",
	"Malta": "马耳他",
	"Marshall Islands": "马绍尔群岛",
	"Martinique": "马提尼克",
	"Mauritania": "毛里塔尼亚",
	"Mauritius": "毛里求斯",
	"Mayotte": "马约特",
	"Mexico": "墨西哥",
	"Micronesia, Federated States of": "密克罗尼西亚联邦",
	"Moldova, Republic of": "摩尔多瓦",
	"Monaco": "摩纳哥",
	"Mongolia": "蒙古",
	"Montenegro": "黑山",
	"Montserrat": "蒙特塞拉特",
	"Morocco": "摩洛哥",
	"Mozambique": "莫桑比克",
	"Myanmar": "缅甸",
	"Namibia": "纳米比亚",
	"Nauru": "瑙鲁",
	"Nepal": "尼泊尔",
	"Netherlands": "荷兰",
	"New Caledonia": "新喀里多尼亚",
	"New Zealand": "新西兰",
	"Nicaragua": "尼加拉瓜",
	"Niger": "尼日尔",
	"Nigeria": "尼日利亚",
	"Niue": "纽埃",
	"Norfolk Island": "诺福克岛",
	"Northern Mariana Islands": "北马里亚纳群岛",
	"Norway": "挪威",
	"Oman": "阿曼",
	"Pakistan": "巴基斯坦",
	"Palau": "帕劳",
	"Palestinian Territory, Occupied": "巴勒斯坦",
	"Panama": "巴拿马",
	"Papua New Guinea": "巴布亚新几内亚",
	"Paraguay": "巴拉圭",
	"Peru": "秘鲁",
	"Philippines": "菲律宾",
	"Pitcairn": "皮特凯恩",
	"Poland": "波兰",
	"Portugal": "葡萄牙",
	"Puerto Rico": "波多黎各",
	"Qatar": "卡塔尔",
	"Réunion": "留尼汪",
	"Romania": "罗马尼亚",
	"Russian Federation": "俄罗斯",
	"Rwanda": "卢旺达",
	"Saint Barthélemy": "圣巴泰勒米",
	"Saint Helena, Ascension and Tristan da Cunha": "圣赫勒拿、阿森松和特里斯坦-达库尼亚",
	"Saint Kitts and Nevis": "圣基茨和尼维斯",
	"Saint Lucia": "圣卢西亚",
	"Saint Martin (French part)": "圣马丁（法属）",
	"Saint Pierre and Miquelon": "圣皮埃尔和密克隆",
	"Saint Vincent and the Grenadines": "圣文森特和格林纳丁斯",
	"Samoa": "萨摩亚",
	"San Marino": "圣马力诺",
	"Sao Tome and Principe": "圣多美和普林西比",
	"Saudi Arabia": "沙特阿拉伯",
	"Senegal": "塞内加尔",
	"Serbia": "塞尔维亚",
	"Seychelles": "塞舌尔",
	"Sierra Leone": "塞拉利昂",
	"Singapore": "新加坡",
	"Sint Maarten (Dutch part)": "圣马丁（荷属）",
	"Slovakia": "斯洛伐克",
	"Slovenia": "斯洛文尼亚",
	"Solomon Islands": "所罗门群岛",
	"Somalia": "索马里",
	"South Africa": "南非",
	"South Georgia and the South Sandwich Islands": "南乔治亚和南桑威奇群岛",
	"South Sudan": "南苏丹",
	"Spain": "西班牙",
	"Sri Lanka": "斯里兰卡",
	"Sudan": "苏丹",
	"Suriname": "苏里南",
	"Svalbard and Jan Mayen": "斯瓦尔巴和扬马延",
	"Swaziland": "斯威士兰",
	"Sweden": "瑞典",
	"Switzerland": "瑞士",
	"Syria": "叙利亚",
	"Taiwan": "中国台湾",
	"Tajikistan": "塔吉克斯坦",
	"Tanzania": "坦桑尼亚",
	"Thailand": "泰国",
	"Timor-Leste": "东帝汶",
	"Togo": "多哥",
	"Tokelau": "托克劳",
	"Tonga": "汤加",
	"Trinidad and Tobago": "特立尼达和多巴哥",
	"Tunisia": "突尼斯",
	"Türkiye": "土耳其",
	"Turkmenistan": "土库曼斯坦",
	"Turks and Caicos Islands": "特克斯和凯科斯群岛",
	"Tuvalu": "图瓦卢",
	"Uganda": "乌干达",
	"Ukraine": "乌克兰",
	"United Arab Emirates": "阿拉伯联合酋长国",
	"United Kingdom": "英国",
	"United States": "美国",
	"United States Minor Outlying Islands": "美国本土外小岛屿",
	"Uruguay": "乌拉圭",
	"Uzbekistan": "乌兹别克斯坦",
	"Vanuatu": "瓦努阿图",
	"Venezuela, Bolivarian Republic of": "委内瑞拉玻利瓦尔共和国",
	"Vietnam": "越南",
	"Virgin Islands, British": "英属维尔京群岛",
	"Virgin Islands, U.S.": "美属维尔京群岛",
	"Wallis and Futuna": "瓦利斯和富图纳",
	"Western Sahara": "西撒哈拉",
	"Yemen": "也门",
	"Zambia": "赞比亚",
	"Zimbabwe": "津巴布韦",
}


def execute():
	added = ensure_translated_doctypes()
	published = publish_missing_translations()
	corrected = apply_corrections()

	if added or published or corrected:
		frappe.db.commit()

	frappe.clear_cache()
	print(
		f"translated_doctype: +{added}, translations: +{published}, "
		f"corrections: {corrected}"
	)


def ensure_translated_doctypes():
	"""给标准数据补 translated_doctype 标记，返回新增条数。"""
	from frappe.custom.doctype.property_setter.property_setter import (
		make_property_setter,
	)

	added = 0

	for doctype in TRANSLATED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.get_value("DocType", doctype, "translated_doctype"):
			continue

		# 同名标记已存在时 make_property_setter 会报重复，跳过更省事。
		if frappe.db.exists(
			"Property Setter",
			{"doc_type": doctype, "property": "translated_doctype", "value": "1"},
		):
			continue

		make_property_setter(
			doctype,
			"",
			"translated_doctype",
			"1",
			"Check",
			for_doctype=True,
			validate_fields_for_doctype=False,
		)
		added += 1

	return added


def publish_missing_translations():
	"""把缺失的中文译名写进 "Translation"，返回新增条数。

	只填空缺，已存在的译文不动 —— 手工校过的译名不能被这里盖掉。
	"""
	from wlh_translate.exporter.exporter import publish_one
	from wlh_translate.utils.language import DEFAULT_LANGUAGE

	published = 0

	for source_text, translated_text in MISSING_TRANSLATIONS.items():
		if publish_one(DEFAULT_LANGUAGE, source_text, translated_text, overwrite=False) in (
			"inserted",
			"overwritten",
		):
			published += 1

	return published


def apply_corrections():
	"""覆盖已存在的错误译名，返回修正条数。"""
	from wlh_translate.exporter.exporter import publish_one
	from wlh_translate.utils.language import DEFAULT_LANGUAGE

	corrected = 0

	for source_text, translated_text in CORRECTIONS.items():
		if publish_one(DEFAULT_LANGUAGE, source_text, translated_text, overwrite=True) in (
			"inserted",
			"overwritten",
		):
			corrected += 1

	return corrected