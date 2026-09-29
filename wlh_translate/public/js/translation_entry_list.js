// Actions for the Translation Entry list view.
//
// Scanning, translating, importing from a catalogue and exporting to the
// site are long running server side jobs: a click only queues them, and the
// state is polled afterwards so the user sees whether the run finished or
// failed. The CSV round trip runs inside the request instead, because the
// file has to be produced or consumed in one go.

(function () {
	const LANGUAGE = "zh";

	const POLL_INTERVAL = 3000;
	// 3s * 1200 = one hour, which is the job timeout
	const MAX_POLLS = 1200;

	frappe.listview_settings["Translation Entry"] = {
		add_fields: ["status", "change_status"],

		formatters: {
			// The first column is the subject, so a plain string is right.
			// Newlines and long HTML snippets would otherwise stretch the row.
			source_text(value) {
				return shorten(value);
			},
			// Other columns render whatever the formatter returns as HTML.
			translated_text(value) {
				return frappe.utils.escape_html(shorten(value));
			},
		},

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

			const jobs = [
				{
					label: __("Scan All Apps"),
					job: "scan_all_apps",
					method: "wlh_translate.api.scan_all_apps",
				},
				{
					label: __("Translate Pending"),
					job: "translate_pending_entries",
					method: "wlh_translate.api.translate_pending_entries",
				},
				{
					label: __("Import From Catalogue"),
					job: "import_existing_translations",
					method: "wlh_translate.api.import_existing_translations",
					args: { language: LANGUAGE },
				},
				{
					label: __("Export To Site"),
					job: "export_translations_to_site",
					method: "wlh_translate.api.export_translations_to_site",
					args: { language: LANGUAGE },
				},
			];

			for (const action of jobs) {
				listview.page.add_inner_button(
					action.label,
					() => {
						queue_job(listview, action);
					},
					__("Bulk Jobs")
				);
			}

			listview.page.add_inner_button(__("Export Pending CSV"), () => {
				export_pending_csv();
			});

			listview.page.add_inner_button(__("Export All By App"), () => {
				export_all_by_app();
			});

			listview.page.add_inner_button(__("Import Translated CSV"), () => {
				import_translated_csv(listview);
			});

			listview.page.add_inner_button(__("Reset Stuck Job"), () => {
				reset_stuck_jobs(listview);
			});
		},
	};

	function shorten(value) {
		return String(value || "")
			.replace(/\s+/g, " ")
			.trim()
			.slice(0, 120);
	}

	function queue_job(listview, action) {
		frappe.call({
			method: action.method,
			args: action.args || {},
			freeze: true,
			callback(response) {
				const result = response.message || {};

				if (result.queued) {
					frappe.show_alert({
						message: __("{0}: queued", [action.label]),
						indicator: "blue",
					});
				} else {
					frappe.show_alert({
						message: __("{0}: the previous run is still going", [
							action.label,
						]),
						indicator: "orange",
					});
				}

				watch_job(listview, action);
			},
		});
	}

	function watch_job(listview, action) {
		let polls = 0;

		const timer = setInterval(() => {
			polls += 1;

			if (polls > MAX_POLLS) {
				clearInterval(timer);
				return;
			}

			frappe.call({
				method: "wlh_translate.api.get_job_state",
				args: { name: action.job },
				callback(response) {
					const state = response.message || {};

					if (state.status === "finished") {
						clearInterval(timer);
						frappe.show_alert({
							message: describe_result(action, state.result),
							indicator: "green",
						});
						listview.refresh();
					} else if (state.status === "failed") {
						clearInterval(timer);
						frappe.msgprint({
							title: __("{0} failed", [action.label]),
							indicator: "red",
							message:
								frappe.utils.escape_html(state.error || "") ||
								__("Check the Error Log for the full traceback"),
						});
						listview.refresh();
					} else if (state.status === "stopped" || state.status === "canceled") {
						clearInterval(timer);
						frappe.show_alert({
							message: __("{0}: stopped", [action.label]),
							indicator: "orange",
						});
					} else if (state.status === "idle" && polls >= 3) {
						// the job record expired before we could read it,
						// but the data has already been written
						clearInterval(timer);
						listview.refresh();
					}
				},
			});
		}, POLL_INTERVAL);
	}

	function describe_result(action, result) {
		if (!result) {
			return __("{0}: done", [action.label]);
		}

		if (action.job === "scan_all_apps") {
			return __("{0}: {1} new, {2} errors", [
				action.label,
				result.new_resources,
				result.errors,
			]);
		}

		if (action.job === "translate_pending_entries") {
			return __("{0}: {1} translated, {2} left", [
				action.label,
				result.translated,
				result.rejected,
			]);
		}

		if (action.job === "import_existing_translations") {
			return __("{0}: {1} imported, {2} still pending", [
				action.label,
				result.matched,
				result.unmatched,
			]);
		}

		if (action.job === "export_translations_to_site") {
			return __("{0}: {1} added, {2} overwritten, {3} skipped", [
				action.label,
				result.inserted,
				result.overwritten,
				result.skipped,
			]);
		}

		return __("{0}: done", [action.label]);
	}

	function export_pending_csv() {
		frappe.call({
			method: "wlh_translate.api.export_pending_csv",
			args: { language: LANGUAGE },
			freeze: true,
			callback(response) {
				const result = response.message || {};

				if (!result.rows) {
					frappe.show_alert({
						message: __("Nothing is pending"),
						indicator: "orange",
					});
					return;
				}

				download(result.filename, result.content);

				frappe.show_alert({
					message: __(
						"{0} source texts ({1} occurrences) exported to {2}",
						[result.rows, result.occurrences, result.filename]
					),
					indicator: "green",
				});
			},
		});
	}

	function download(filename, content) {
		save_blob(filename, new Blob([content], { type: "text/csv;charset=utf-8" }));
	}

	// The zip comes back base64 encoded, so it has to be decoded into raw
	// bytes before the browser can save it.
	function download_base64(filename, base64) {
		const binary = atob(base64);
		const bytes = new Uint8Array(binary.length);

		for (let index = 0; index < binary.length; index += 1) {
			bytes[index] = binary.charCodeAt(index);
		}

		save_blob(filename, new Blob([bytes], { type: "application/zip" }));
	}

	function save_blob(filename, blob) {
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");

		link.href = url;
		link.download = filename;

		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);

		URL.revokeObjectURL(url);
	}

	function export_all_by_app() {
		frappe.call({
			method: "wlh_translate.api.export_all_by_app",
			args: { language: LANGUAGE },
			freeze: true,
			callback(response) {
				const result = response.message || {};

				if (!result.rows) {
					frappe.show_alert({
						message: __("Nothing to export"),
						indicator: "orange",
					});
					return;
				}

				download_base64(result.filename, result.content);

				frappe.show_alert({
					message: __("{0} source texts across {1} apps exported to {2}", [
						result.rows,
						result.apps.length,
						result.filename,
					]),
					indicator: "green",
				});
			},
		});
	}

	function import_translated_csv(listview) {
		const picker = document.createElement("input");

		picker.type = "file";
		picker.accept = ".csv,text/csv";

		picker.addEventListener("change", () => {
			const file = picker.files && picker.files[0];

			if (!file) {
				return;
			}

			const reader = new FileReader();

			reader.addEventListener("load", () => {
				frappe.call({
					method: "wlh_translate.api.import_translated_csv_file",
					args: { language: LANGUAGE, content: reader.result },
					freeze: true,
					callback(response) {
						const result = response.message || {};

						frappe.msgprint({
							title: __("Import Translated CSV"),
							indicator: "green",
							message: __(
								"{0} updated, {1} source texts not found, {2} already translated",
								[result.updated, result.unknown, result.skipped]
							),
						});

						listview.refresh();
					},
				});
			});

			reader.readAsText(file, "UTF-8");
		});

		picker.click();
	}

	function reset_stuck_jobs(listview) {
		frappe.confirm(
			__(
				"Clear the records of any queued or running job? Only do this when a job is stuck."
			),
			() => {
				frappe.call({
					method: "wlh_translate.api.reset_stuck_jobs",
					freeze: true,
					callback(response) {
						const removed = (response.message || {}).removed || [];

						frappe.show_alert({
							message: removed.length
								? __("Cleared: {0}", [removed.join(", ")])
								: __("No stuck job"),
							indicator: "green",
						});

						listview.refresh();
					},
				});
			}
		);
	}
})();