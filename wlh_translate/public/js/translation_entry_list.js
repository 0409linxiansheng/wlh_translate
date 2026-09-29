// Actions for the Translation Entry list view.
//
// Scanning, translating and exporting are long running server side jobs,
// so every button only queues the work and reports the job name.

frappe.listview_settings["Translation Entry"] = {
	add_fields: ["status", "change_status"],

	get_indicator(doc) {
		if (doc.change_status === "Suspected Deleted") {
			return [__("Suspected Deleted"), "red", "change_status,=,Suspected Deleted"];
		}

		if (doc.change_status === "Changed") {
			return [__("Changed"), "orange", "change_status,=,Changed"];
		}

		if (doc.status === "Reviewed") {
			return [__("Reviewed"), "green", "status,=,Reviewed"];
		}

		if (doc.status === "Translated") {
			return [__("Translated"), "blue", "status,=,Translated"];
		}

		return [__("Pending"), "gray", "status,=,Pending"];
	},

	onload(listview) {
		if (!frappe.user.has_role("System Manager")) {
			return;
		}

		const actions = [
			{
				label: __("Scan All Apps"),
				method: "wlh_translate.api.scan_all_apps",
			},
			{
				label: __("Translate Pending"),
				method: "wlh_translate.api.translate_pending_entries",
			},
			{
				label: __("Import From Catalogue"),
				method: "wlh_translate.api.import_existing_translations",
				args: { language: "zh" },
			},
			{
				label: __("Export To Site"),
				method: "wlh_translate.api.export_translations_to_site",
				args: { language: "zh" },
			},
		];

		for (const action of actions) {
			listview.page.add_inner_button(action.label, () => {
				frappe.call({
					method: action.method,
					args: action.args || {},
					freeze: true,
					callback(response) {
						const result = response.message;

						if (result && result.queued) {
							frappe.show_alert({
								message: __("Queued: {0}", [result.job]),
								indicator: "green",
							});
						}
					},
				});
			});
		}
	},
};