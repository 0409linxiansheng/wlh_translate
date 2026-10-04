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

		// The list doubles as the translation worklist, so the entries we have
		// already decided not to translate (technical strings, seed and test
		// data) stay out of it. They would otherwise sit here as "Suspected
		// Deleted" noise forever: the scanner skips the files they come from,
		// never sees them again and re-flags them on every run. The number
		// cards count with the same filter, so the list and the counters agree.
		// Removing the filter from the filter row still shows everything.
		filters: [["is_translatable", "=", 1]],

		// The list is read through the translation, so finding one entry to fix
		// means searching by what is already written into it. The field is Long
		// Text, and those would only ever be compared with "=" if left to the
		// standard filters, so the box is declared here with a like condition.
		// It lands next to the ID and source text boxes.
		custom_filter_configs: [
			{
				fieldtype: "Data",
				label: __("Translated Text"),
				fieldname: "translated_text",
				condition: "like",
				is_filter: 1,
			},
		],

		formatters: {
			// A column renders whatever the formatter returns as markup, so
			// this has to be HTML rather than bare text: the list view measures
			// every column with $(column_html).text(), and jQuery parses a
			// plain string as a CSS selector. Translations that contain
			// ( ) % ' & or a leading "<" are invalid selectors, the row loop
			// then aborts and the list shows a header over an empty body.
			translated_text(value) {
				return `<span class="ellipsis">${frappe.utils.escape_html(shorten(value))}</span>`;
			},
		},

		// The translation status wins: a translated entry must stay one click
		// away from "show me everything that is already translated", which is
		// how single entries are reviewed and fixed up later. The change flags
		// only ride on the rows that are still pending, where they are the
		// actionable signal.
		get_indicator(doc) {
			if (doc.status === "Reviewed") {
				return [__("Reviewed"), "green", "status,=,Reviewed"];
			}

			if (doc.status === "Translated") {
				return [__("Translated"), "blue", "status,=,Translated"];
			}

			if (doc.change_status === "Suspected Deleted") {
				return [__("Suspected Deleted"), "red", "change_status,=,Suspected Deleted"];
			}

			if (doc.change_status === "Changed") {
				return [__("Changed"), "orange", "change_status,=,Changed"];
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
					verb: __("Scanning"),
					job: "scan_all_apps",
					method: "wlh_translate.api.scan_all_apps",
				},
				{
					label: __("Translate Pending"),
					verb: __("Translating"),
					job: "translate_pending_entries",
					method: "wlh_translate.api.translate_pending_entries",
				},
				{
					label: __("Import From Catalogue"),
					verb: __("Importing"),
					job: "import_existing_translations",
					method: "wlh_translate.api.import_existing_translations",
					args: { language: LANGUAGE },
				},
				// Translations are published when they are written: an entry
				// saved in the desk goes out immediately, and the bulk jobs
				// publish once they finish. This button is the fallback, for
				// when something was written outside those paths or the
				// publication itself needs to be redone from scratch.
				{
					label: __("Force Re-sync"),
					verb: __("Re-syncing"),
					job: "export_translations_to_site",
					method: "wlh_translate.api.export_translations_to_site",
					args: { language: LANGUAGE },
				},
			];

			// Every batch job can be narrowed down to one app. Scanning a single
			// app is what makes it quick to pick up whatever an app installed a
			// moment ago declares; the picker always offers "All Apps" as well.
			for (const action of jobs) {
				listview.page.add_inner_button(
					action.label,
					() => {
						open_app_picker(listview, action);
					},
					__("Bulk Jobs")
				);
			}

			// Some text never reaches this table at all: it is hard coded in a
			// frontend component and rendered verbatim. The scan cannot see a
			// problem there, because there is nothing to translate; these three
			// buttons are the way to find that text and to fix it upstream.
			listview.page.add_inner_button(
				__("Audit Untranslated"),
				() => {
					open_app_picker(
						listview,
						{
							label: __("Audit Untranslated"),
							verb: __("Auditing"),
							job: "audit_app",
							method: "wlh_translate.api.audit_app",
							args_from_values: (values) => ({
								include_dependencies: values.include_dependencies ? 1 : 0,
							}),
						},
						{
							required: true,
							extra_fields: [
								{
									fieldtype: "Check",
									fieldname: "include_dependencies",
									label: __("Include shared UI packages"),
									default: 1,
								},
							],
						}
					);
				},
				__("Source Patch")
			);

			listview.page.add_inner_button(
				__("Upstream Patch"),
				() => {
					open_patch_dialog(listview);
				},
				__("Source Patch")
			);

			listview.page.add_inner_button(
				__("Rebuild Frontend"),
				() => {
					open_app_picker(
						listview,
						{
							label: __("Rebuild Frontend"),
							verb: __("Building"),
							job: "patch_app",
							method: "wlh_translate.api.rebuild_frontend",
						},
						{ required: true }
					);
				},
				__("Source Patch")
			);

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

	// Ask which app the job should apply to before queueing it. The list has
	// to come from the server: the installed apps are not part of frappe.boot,
	// and an app installed a moment ago has no entries yet to be noticed by.
	//
	// A rebuild and an audit only mean something for one app at a time, so
	// they pass required = true: the "All Apps" entry is dropped and a choice
	// is demanded. extra_fields adds prompt rows of the caller's own, and
	// args_from_values turns those answers into job arguments.
	function open_app_picker(
		listview,
		action,
		{ required = false, extra_fields = [] } = {}
	) {
		frappe.call({
			method: "wlh_translate.api.get_installed_apps",
			freeze: true,
			callback(response) {
				const apps = response.message || [];

				if (!apps.length) {
					frappe.show_alert({
						message: __("No app is installed"),
						indicator: "orange",
					});
					return;
				}

				const app_options = apps.map((row) => ({
					label: `${row.app_name} (${Number(row.entries || 0).toLocaleString()})`,
					value: row.app_name,
				}));

				const fields = [
					{
						fieldtype: "Select",
						fieldname: "app_name",
						label: __("App"),
						options: required
							? app_options
							: [{ label: __("All Apps"), value: "" }, ...app_options],
						// "All Apps" is the empty value, and a required field
						// rejects an empty string, so nothing is required there.
						reqd: required ? 1 : 0,
						default: required ? apps[0].app_name : "",
					},
					...extra_fields,
				];

				frappe.prompt(
					fields,
					(values) => {
						queue_job(listview, action, values.app_name || null, values);
					},
					__("Choose an App"),
					__("Start")
				);
			},
		});
	}

	// Upstream patches are replayed by hand: the list shows what the library
	// holds and how each patch relates to the files on disk, and one is picked
	// together with what to do to it. Applying and reverting both end with a
	// rebuild, because the bundle in public/ is what the browser loads.
	function open_patch_dialog(listview) {
		frappe.call({
			method: "wlh_translate.api.list_upstream_patches",
			freeze: true,
			callback(response) {
				const patches = response.message || [];

				if (!patches.length) {
					frappe.show_alert({
						message: __("No upstream patch is registered"),
						indicator: "orange",
					});
					return;
				}

				const options = patches.map((row) => ({
					label: `${row.app_name} · ${row.patch_name} (${patch_status_label(
						row.status
					)})`,
					value: `${row.app_name}::${row.patch_name}`,
				}));

				frappe.prompt(
					[
						{
							fieldtype: "Select",
							fieldname: "patch",
							label: __("Patch"),
							options,
							default: options[0].value,
							reqd: 1,
						},
						{
							fieldtype: "Select",
							fieldname: "action",
							label: __("Action"),
							options: [
								{ label: __("Apply and Rebuild"), value: "apply" },
								{ label: __("Revert and Rebuild"), value: "revert" },
							],
							default: "apply",
							reqd: 1,
						},
					],
					(values) => {
						const [app_name, patch_name] = values.patch.split("::");
						const applying = values.action === "apply";

						queue_job(
							listview,
							{
								label: `${app_name} · ${patch_name}`,
								verb: applying ? __("Patching") : __("Reverting"),
								job: "patch_app",
								method: applying
									? "wlh_translate.api.apply_upstream_patch"
									: "wlh_translate.api.revert_upstream_patch",
								args: { patch_name },
							},
							app_name
						);
					},
					__("Upstream Patch"),
					__("Start")
				);
			},
		});
	}

	// The state a patch is in relative to the files on disk, said in the words
	// the list uses rather than the ones the patcher returns.
	function patch_status_label(status) {
		const labels = {
			applied: __("Applied"),
			available: __("Available"),
			conflict: __("Conflict"),
			missing: __("Missing"),
		};

		return labels[status] || status;
	}

	function queue_job(listview, action, app_name, values = {}) {
		const args = { ...(action.args || {}) };

		if (app_name) {
			args.app_name = app_name;
		}

		if (action.args_from_values) {
			Object.assign(args, action.args_from_values(values) || {});
		}

		frappe.call({
			method: action.method,
			args,
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

				listview.page.set_indicator(
					`${action.label} · ${__("Queued")}`,
					"blue"
				);

				watch_job(listview, action);
			},
		});
	}

	// The status pill next to the page title is the progress display. A modal
	// progress bar would block the page, and the run takes long enough that the
	// user wants to keep working while it goes.
	function progress_label(action, progress) {
		const parts = [action.verb || __("Running")];

		if (progress.app_name) {
			if (progress.app_total > 1) {
				parts.push(
					`${progress.app_name} ${progress.app_index}/${progress.app_total}`
				);
			} else {
				parts.push(progress.app_name);
			}
		}

		if (progress.total) {
			const percent = Math.floor((progress.done / progress.total) * 100);

			parts.push(`${progress.done}/${progress.total} ${percent}%`);
		}

		return parts.join(" · ");
	}

	function watch_job(listview, action) {
		let polls = 0;

		const timer = setInterval(() => {
			polls += 1;

			if (polls > MAX_POLLS) {
				clearInterval(timer);
				listview.page.clear_indicator();
				return;
			}

			frappe.call({
				method: "wlh_translate.api.get_job_state",
				args: { name: action.job },
				callback(response) {
					const state = response.message || {};

					if (
						state.status === "queued" ||
						state.status === "deferred" ||
						state.status === "scheduled"
					) {
						// accepted by the queue but no worker has picked it up
						// yet. On a busy queue that can last a while, and
						// without this the pill would show nothing at all.
						listview.page.set_indicator(
							`${action.label} · ${__("Queued")}`,
							"blue"
						);
					} else if (state.progress) {
						// the worker publishes the numbers once it starts
						listview.page.set_indicator(
							progress_label(action, state.progress),
							"blue"
						);
					}

					if (state.status === "finished") {
						clearInterval(timer);
						listview.page.clear_indicator();

						if (action.job === "audit_app") {
							// the answer is a list, not a number, so it cannot
							// be a one line alert
							show_audit_report(state.result);
						} else {
							frappe.show_alert({
								message: describe_result(action, state.result),
								indicator: "green",
							});
						}

						listview.refresh();
					} else if (state.status === "failed") {
						clearInterval(timer);
						listview.page.clear_indicator();
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
						listview.page.clear_indicator();
						frappe.show_alert({
							message: __("{0}: stopped", [action.label]),
							indicator: "orange",
						});
					} else if (state.status === "idle" && polls >= 3) {
						// the job record expired before we could read it,
						// but the data has already been written
						clearInterval(timer);
						listview.page.clear_indicator();
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

		if (action.job === "patch_app") {
			if (result.applied) {
				return __("{0}: applied, {1} strings registered, frontend rebuilt", [
					action.label,
					(result.strings || []).length,
				]);
			}

			if (result.reverted) {
				return __("{0}: reverted, frontend rebuilt", [action.label]);
			}

			if (result.reverted === false) {
				// revert_patch() reports false when the patch was not in
				// place, so nothing was taken out; the build still ran.
				return __("{0}: was not applied, frontend rebuilt", [action.label]);
			}

			return __("{0}: frontend rebuilt", [action.label]);
		}

		return __("{0}: done", [action.label]);
	}

	// The audit result is a worklist: every row is a place where text is
	// rendered without ever reaching this table. It is shown as a table, not
	// as an alert, because that is what makes it usable - each line is a
	// candidate for an upstream patch, and the file and line point at it.
	function show_audit_report(result) {
		const findings = (result && result.findings) || [];

		if (!findings.length) {
			frappe.msgprint({
				title: __("Audit Untranslated Text"),
				indicator: "green",
				message: __("No unreachable text found in {0} files", [
					(result && result.files) || 0,
				]),
			});
			return;
		}

		const rows = findings
			.map(
				(row) =>
					`<tr><td>${frappe.utils.escape_html(row.file)}:${row.line}</td>` +
					`<td>${frappe.utils.escape_html(row.text)}</td></tr>`
			)
			.join("");

		const note = result.truncated
			? `<p class="text-muted">${__("Showing the first {0} findings", [
					findings.length,
				])}</p>`
			: "";

		const header =
			`<th>${__("Location")}</th><th>${__("Text")}</th>`;

		frappe.msgprint({
			title: __("Audit Untranslated Text"),
			indicator: "orange",
			message:
				`${note}<table class="table table-bordered">` +
				`<thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`,
		});
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