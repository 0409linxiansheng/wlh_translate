/*
 * 框架里有一批界面文案没有用 __() 包裹。它们的译文其实已经存在于
 * "Translation" 表（或 .po），但代码从不调用 __()，所以永远不生效。
 *
 * 这里在界面外壳容器里为这些已知文案补上 __()，译文仍以 "Translation"
 * 表为准，不在这里硬编码中文，避免两套译法不一致。
 */
(function () {
	// 语义明确、不会与业务数据混淆的文案，任意位置都补 __()。
	const ALWAYS = [
		"Invalid Transition",
		"Custom Block Name",
		"Session Defaults",
		"Assigned To",
		"Created By",
	];

	// 短词、通用词，只在界面外壳容器内补 __()。
	const SCOPED = [
		"Workspaces",
		"Display",
		"Reload",
		"Help",
		"Logout",
		"ID",
		"Tags",
		"Label",
		"Icon",
		"Upgrade",
	];

	// 界面外壳容器；业务数据区（表格、表单正文）不在其中。
	const SCOPES = [
		".sidebar-header-menu",
		".dropdown-menu",
		".modal",
		".filter-area",
		".list-filters",
		".page-form",
		".page-head",
	];

	function is_candidate(text, scoped) {
		if (ALWAYS.includes(text)) return true;
		return scoped && SCOPED.includes(text);
	}

	function translate_scope(root, scoped) {
		if (!root || root.nodeType !== 1) return;

		const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
			acceptNode(node) {
				return is_candidate((node.nodeValue || "").trim(), scoped)
					? NodeFilter.FILTER_ACCEPT
					: NodeFilter.FILTER_REJECT;
			},
		});

		const nodes = [];
		while (walker.nextNode()) nodes.push(walker.currentNode);

		nodes.forEach((node) => {
			const raw = node.nodeValue;
			const text = raw.trim();
			if (!is_candidate(text, scoped)) return;

			// __() 找不到译文时原样返回，因此没有译文就保持英文。
			const translated = __(text);
			if (translated && translated !== text) {
				node.nodeValue = raw.replace(text, translated);
			}
		});
	}

	function in_scope(el) {
		return el && SCOPES.some((s) => el.matches(s) || el.closest(s));
	}

	function handle(node) {
		const el = node.nodeType === 1 ? node : node.parentElement;
		if (!el) return;

		translate_scope(el, false);

		if (in_scope(el)) {
			translate_scope(el, true);
		}
	}

	function sweep() {
		// 全局只处理语义明确的那些。
		translate_scope(document.body, false);

		// 短词限制在界面外壳里。
		SCOPES.forEach((selector) => {
			document.querySelectorAll(selector).forEach((el) => translate_scope(el, true));
		});
	}

	function start() {
		sweep();

		// 侧边栏下拉、弹窗、过滤器都是懒渲染的，后续新增节点也要处理。
		new MutationObserver((mutations) => {
			mutations.forEach((mutation) => {
				mutation.addedNodes &&
					mutation.addedNodes.forEach((node) => handle(node));
			});
		}).observe(document.body, { childList: true, subtree: true });
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}
})();