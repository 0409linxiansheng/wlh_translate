// 让列表首列的记录名走框架自带的翻译。
//
// 单据没有 title_field 时，框架在 list_view.js 的 setup_columns() 里会现造
// 一个首列字段：{ label: __("ID"), fieldname: "name" }。这个对象没有
// options，于是 get_column_html() 里的判断
//
//     translated_doctypes.includes(df.options)
//
// 永远不成立，首列记录名就一直原样显示英文 —— 侧边栏、下拉框都已经是中文，
// 只有列表首列还是英文，原因就在这里。
//
// 这里不改框架源码：在框架造好列之后，给首列补一个 options（当前单据名），
// 框架自己会去 frappe.boot.translated_doctypes 里判断要不要翻译。哪些单据
// 需要翻译由后台的 translated_doctype 标记决定，本文件不含任何硬编码清单，
// 升级 frappe / erpnext 都不会被覆盖。
(function () {
	const ListView = frappe.views && frappe.views.ListView;
	if (!ListView || !ListView.prototype || !ListView.prototype.setup_columns) {
		return;
	}

	const setup_columns = ListView.prototype.setup_columns;

	ListView.prototype.setup_columns = function (...args) {
		setup_columns.apply(this, args);

		const first = this.columns && this.columns[0];
		if (!first || first.type !== "Subject" || !first.df || first.df.options) {
			return;
		}

		if (first.df.fieldname === "name") {
			// 框架 setup_columns() 现造的字段对象，可以直接补。
			first.df.options = this.doctype;
		} else {
			// title_field 取自 frappe.meta，复制一份再补，避免污染元数据。
			first.df = Object.assign({}, first.df, { options: this.doctype });
		}
	};
})();