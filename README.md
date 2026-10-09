# Wlh Translate

面向 Frappe / ERPNext 的中文翻译扫描与管理工具。

把散落在各个 app 源码里的可翻译文案扫出来、集中到一张表里翻译，再一次性发布到站点。
全程只写站点自己的 `Translation` 表，**不改 frappe / erpnext 源码**，`bench update` 升级不受影响。

还有一类文案**根本进不了这张表**：它们硬编码在前端组件里、由 Vue 原样渲染，翻译表说什么都没用。
遇到这种，本 app 的办法是把改动做成**可复放的补丁**留在自己的补丁库里，重装依赖后一键重放并重新构建前端，
同时用**漏译体检**把这类文案先找出来。详见 [翻不出来的文案怎么办](#翻不出来的文案怎么办)。

- **适用版本**：Frappe Framework v16（`version-16` 分支）
- **默认目标语言**：`zh`（简体中文）
- **许可**：MIT

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [主要能力](#主要能力)
- [工作流程](#工作流程)
- [翻不出来的文案怎么办](#翻不出来的文案怎么办)
- [安装](#安装)
- [快速上手](#快速上手)
- [界面说明](#界面说明)
- [怎么搜索条目](#怎么搜索条目)
- [数据模型](#数据模型)
- [翻译从哪来](#翻译从哪来)
- [设计取舍](#设计取舍)
- [目录结构](#目录结构)
- [开发](#开发)
- [许可](#许可)

---

## 它解决什么问题

ERPNext / Frappe 的中文覆盖并不完整，界面上经常中英混杂。想做到"完全中文化"会遇到几件事：

1. **文案找不全**：散落在 `.py` / `.js` / `.html` / DocType `.json` / `.po` 里，靠人工翻代码一定会漏。
2. **没有待办清单**：官方 `locale/zh.po` 已经翻了一部分，但"哪些还没翻"没有任何现成清单。
3. **改源码会被覆盖**：直接把中文写进 frappe / erpnext 的源码或语言文件，下次升级就没了。
4. **没法分工**：翻译需要多人协作，但没有统一的表单，也没有导入导出的通道。

Wlh Translate 把「找文案 → 分配翻译 → 发布上线」做成一条可重复执行的流水线。

## 主要能力

| 能力 | 说明 |
| --- | --- |
| 源码扫描 | 扫描已安装 app **仓库根目录**下的 `.py` `.js` `.mjs` `.cjs` `.jsx` `.ts` `.tsx` `.vue` `.html` `.htm` `.jinja`，识别 `_()` / `__()` / `frappe._()` 调用。Vue 3 app 的文案大多在 `desk/`、`frontend/` 这类与 Python 包平级的目录里，必须扫仓库根目录才拿得到 |
| 元数据扫描 | DocType / Workspace / Report / Print Format 等 `.json` 里的 `label`、`description`、`options`、`title`、`message` 等文案字段 |
| 官方清单对齐 | 读取 `<app>/<app>/locale/zh.po` 的**全部 msgid（含未翻译项）**，保证不漏 |
| 种子数据扫描 | `setup_wizard/data/*.json` 里面向用户的文案（如 `Litre`、`Cubic Yard`） |
| 自动去噪 | 过滤 CSS class、纯符号/数字、字段名等"看起来是文案其实不是"的串；跳过测试夹具（`test_records.json`、`test_data_*.json`）和国别科目表种子（`country_wise_tax.json`） |
| 词典翻译 | 内置业务术语词典 + 通用词典，带质量校验（无中文、残留大量英文、中英粘连会被拒绝入库） |
| CSV 往返 | 导出待翻译清单 → 分工翻译 → 导回；导出带 BOM，Excel 直接打开不乱码 |
| 按 app 导出 | 一个 app 一个 CSV，打包成 zip，方便按模块分工 |
| 发布到站点 | 写入站点 `Translation` 表并清缓存，**立即生效**，不动任何 app 的 git 工作区 |
| 自动发布 | 不需要手动搬运：列表里改一条存一条就发布一条，批量任务跑完自动统一发布一次；**`Translation Entry` 是译文的唯一事实来源，与站点已有译文不同时直接覆盖** |
| 后台任务 | 耗时操作走 RQ `long` 队列，前端轮询进度；`job_id` + `deduplicate` 防重复提交，另有 `Reset Stuck Job` 兜底 |
| 单应用执行 | 四个批量任务点下去先弹选择框，可选「所有应用」或某一个 app；单扫刚装的应用几秒就能跑完 |
| 实时进度 | 任务运行期间列表页标题旁显示常驻状态胶囊（如 `扫描中 · helpdesk · 340/1347 25%`），不挡页面操作 |
| 变更跟踪 | `New / Unchanged / Changed / Suspected Deleted / Restored`，源码改文案或删文案都能看出来 |
| 译文回查 | 筛选行提供「翻译文本」输入框，支持模糊匹配，方便按已有译文把单条拎出来修改 |
| 漏译体检 | 扫一个 app 的 `.vue` 模板，列出**任何翻译表都够不到**的文案：标签之间的纯文本、`{{ '字面量' }}`、`:label="'字面量'"`，给出 `文件:行号`，可直接照着写补丁 |
| 上游补丁 | 把「给依赖包里的组件套上 `__()`」这类改动存成补丁库里的 `*.patch`，一键应用/撤销并自动重建前端；重装依赖后重放一次即可 |
| 默认只看待办 | 列表默认只显示 `is_translatable = 1` 的条目，噪声数据不占屏；筛选行里可随时去掉 |
| 自带中文界面 | 随 app 打包 `wlh_translate/translations/zh.csv`，本 app 的界面本身就是中文 |

## 工作流程

```
  源码 / DocType JSON / setup wizard 数据 / zh.po
                     │
                     │  ① Scan All Apps
                     ▼
            Translation Entry (Pending)
                     │
                     │  ② Import From Catalogue（官方 .po 已有译文，只填空缺）
                     │  ③ Translate Pending （词典翻译 + 质量校验）
                     │  ④ 人工 / CSV 往返
                     ▼
        Translation Entry (Translated / Reviewed)
                     │
                     │  ⑤ 自动发布
                     ▼
             站点 Translation 表 ──► 界面立刻显示中文
```

第 ⑤ 步不用点按钮：在列表里改一条、存一条就发布一条；②③④ 三个批量任务跑完各自
自动统一发布一次。`Translation Entry` 是译文的唯一事实来源，站点上已有但内容不同的
译文会被覆盖。**Bulk Jobs → Force Re-sync** 只是兜底手段，用来在数据被别的途径改动过、
或想从头重发一遍时全量重同步。

`Source Type` 会记录文案的来源（`DocField` / `Label` / `Message` / `JS` / `Python` / `HTML` / `Workspace` / `Report` / `Other`），`Source Path` + `Line Number` 保留出处，方便回查。

## 翻不出来的文案怎么办

上面的流程只对**走了 `_()` 的文案**有效。还有一类文案进不了任何翻译表，翻译表里就算写好了中文，界面上也还是英文：

```vue
{{ 'Getting started' }}          <!-- 模板里的字面量，Vue 原样渲染 -->
:label="'Skip all'"              <!-- 传给组件的字面量属性 -->
<div>Stock Level</div>           <!-- 标签之间的纯文本 -->
```

这类文案往往藏在**依赖包**里（比如 `frappe-ui` 这个共享 UI 库），app 作者自己也没法改。所以本 app 的办法分两步，**发现**和**处置**各管一半：

### 第一步：漏译体检（发现）

**Source Patch → Audit Untranslated**，选一个 app 跑一次。它读该 app 仓库里所有 `.vue` 的 `<template>`，只报**确定够不到翻译表**的三类：标签之间的纯文本、`{{ ... }}` 里的字面量、绑定属性里的字面量；`__()` 包住的会跳过，所以补过的条目不会再来烦你。可选「Include shared UI packages」把 `node_modules/frappe-ui` 也一起读——那正是问题最常见的地方。

结果是一张 `文件:行号 → 文本` 的表格（最多 500 行，超出会提示）。已经做了技术串去噪（CSS class、style、模板 id、日期格式这些引用起来像文案其实不是的会滤掉），剩下的基本可以直接照着写补丁。

### 第二步：上游补丁（处置）

改动不直接写在 `node_modules` 里，而是存成补丁库中的 `*.patch`：

```
wlh_translate/patcher/library/<app_name>/<patch_name>.patch
```

补丁就是普通的 unified diff（`git diff` 产出的那种），用 GNU `patch -p1` 从 app 仓库根目录应用，可读、可 review、不依赖任何包管理器。列表页 **Source Patch → Upstream Patch** 会列出补丁库里的补丁及其当前状态：

| 状态 | 含义 |
| --- | --- |
| `Applied` | 改动已在文件里 |
| `Available` | 可以干净地应用 |
| `Conflict` | 反正反两个方向都打不上，文件已经变样了，需要重做补丁 |

选一个补丁 + `Apply and Rebuild` / `Revert and Rebuild`，后台跑完会**自动重新构建该 app 的前端**——只改源码不重新编译，浏览器加载的还是旧 bundle。**Rebuild Frontend** 是单独重跑构建的兜底入口（构建被中断、或源码在别处改过时用）。

补丁本身只解决"改动会被 `yarn install` 冲掉"的问题：升级或重装依赖后回到列表页点一次 `Apply and Rebuild` 就恢复。

### 补丁引入了新文案怎么办

应用补丁时会自动把改动新增的字符串注册成普通的 `Translation Entry`（`Source Type = JS`），和扫出来的条目一样走"翻译 → 发布"。所以补丁和翻译是两条独立的链路：**补丁负责让文案能被翻译，翻译表负责给它中文**。

### 为什么不用 `patch-package` 或直接改源码

- 直接改 `node_modules` / 依赖源码：下次 `yarn install`、`bench update` 就没了，而且没人知道曾经改过什么。
- `patch-package`：需要在目标 app 的 `desk/package.json` 里注册 `postinstall` 钩子，等于改别人仓库的配置；而且它的补丁是 npm 生态的产物，跟"哪个 app、什么状态、点了没点"无关。
- 本项目的方式：补丁存在**本 app 自己的目录**里，应用/撤销/状态判断/构建全在列表页一键完成，不碰目标 app 的任何配置文件。

## 安装

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/0409linxiansheng/wlh_translate --branch version-16
bench install-app wlh_translate
```

安装完成后 `after_install` 会自动把站点语言、全局默认语言以及现有用户的语言切成中文
（Frappe 取语言有优先级：`User.language` → `System Settings.language` → 站点配置 → `en`，只改站点默认值会被用户自己的设置盖掉）。

## 快速上手

1. 进入 `/desk`，首页 **Framework** 图标 → **Wlh Translate**。
2. 打开 **Translation Entry**，右上角 **Bulk Jobs** → **Scan All Apps**，在弹出的选择框里选「所有应用」或某一个 app，等任务跑完（标题旁会实时显示进度，结束后自动提示结果）。
   刚装完某个 app 想单独补扫，就只选那个 app，几秒即可完成，不会重扫其他应用。
3. **Import From Catalogue**：把 frappe / erpnext 官方 `.po` 里已有的译文灌进来，Pending 数量会大幅下降。
4. **Translate Pending**：跑一遍词典翻译，剩余的需要人工处理。
5. **Export Pending CSV**（全部）或 **Export All By App**（按 app 拆分成 zip）导出，分工翻译后用 **Import Translated CSV** 导回。导回后会自动发布，界面立刻变中文。
6. 之后在列表里随手改哪条译文，保存即生效，不需要再点任何发布按钮。真要全量重发一遍时才用 **Bulk Jobs → Force Re-sync**。
7. 如果某个 app 的界面上还有英文，而那串文案在列表里明明已经翻好了 —— 它多半**根本没走翻译表**。用 **Source Patch → Audit Untranslated** 找出来，再按 [翻不出来的文案怎么办](#翻不出来的文案怎么办) 打成补丁。

> 任务在 `long` 队列上执行，超时 6 小时。需要 `bench start` 或 `bench worker`（RQ worker）在跑。
> 队列顺序是 `short → default → long`，只有一个 worker 时，一个卡住的 scheduled job 就会让所有按钮停在「排队」上——先看 `bench worker` 日志再排查别的。
> 补丁的应用与重建跑在 **worker 进程**里，它写入 `apps/<app>/<app>/public/`，所以那个目录必须对该 worker 的运行用户可写（`bench` 通常以同一个用户运行，手动用别的账号跑过一次构建就会留下权限不一致的产物）。

## 界面说明

**Translation Entry** 列表页右上角的按钮：

| 按钮 | 作用 |
| --- | --- |
| Bulk Jobs → **Scan All Apps** | 扫描所选 app（或全部已安装 app）的仓库根目录，把新文案写进 Translation Entry，并标记已消失的文案为 `Suspected Deleted` |
| Bulk Jobs → **Translate Pending** | 对所选 app（或全部）的 Pending 条目跑词典翻译，过不了质量校验的保持 Pending；`is_translatable = 0` 的条目直接跳过 |
| Bulk Jobs → **Import From Catalogue** | 从各 app 的 `locale/zh.po` 填充所选 app（或全部）的空缺译文，**不覆盖**已有译文 |
| Bulk Jobs → **Force Re-sync** | 兜底：全量重扫一遍 `Translated` / `Reviewed` 条目并发布到站点 `Translation` 表，清缓存。正常流程用不到它 |
| Source Patch → **Audit Untranslated** | 漏译体检：列出所选 app 的 `.vue` 里**够不到翻译表**的文案，给 `文件:行号`；可选连 `node_modules/frappe-ui` 一起读 |
| Source Patch → **Upstream Patch** | 列出补丁库里的补丁（含 `Applied` / `Available` / `Conflict` 状态），选一个执行「应用并重建」或「撤销并重建」 |
| Source Patch → **Rebuild Frontend** | 单独重跑所选 app 的前端构建，不碰源码 |
| **Export Pending CSV** | 导出待翻译清单（按 `source_text` 去重，一行一个原文） |
| **Export All By App** | 按 app 分组导出成 zip，每个 app 一个 CSV |
| **Import Translated CSV** | 导回翻译好的 CSV，只填空缺、不改写 `source_text`、不覆盖已有译文 |
| **Reset Stuck Job** | 清理卡在 queued / running 的任务记录（仅在真的卡住时使用） |

首页还有三张数字卡片——**总条目数 / 待翻译 / 已翻译**。它们和列表用的是同一个 `is_translatable = 1` 条件，噪声数据不会被算进去。

## 怎么搜索条目

筛选行有三个输入框：**编号**、**翻译文本**、**源文本**，直接输入关键字即可，**不需要自己加 `%`**。

- **翻译文本**：按译文回查。列表里看得到译文但看不到出处时，用这个框把单条拎出来修改。
- **源文本**：按原文回查。
- 每个框左侧的切换按钮显示 **`≈`** 时是模糊匹配（等价于 `like %关键字%`）；显示 **`=`** 时是精确相等，点一下即可切换，选择会被记住。

列表默认只显示 `is_translatable = 1` 的条目。要连噪声数据一起看，在筛选行里删掉这条条件即可。

> 实现细节：`source_text` 故意用 `Text` 而不是 `Long Text`。Frappe 只会把 `Text / Small Text / Data` 这类字段渲染成「单行输入 + 模糊匹配」的筛选框，`Long Text` 会退化成只能精确匹配的大文本框——这正是"搜不到"的常见原因。`translated_text` 是 `Long Text`（译文可能很长含 HTML，不能压成 `Text`），所以它的搜索框是在列表页 JS 里用 `custom_filter_configs` 单独声明并显式指定 `like` 的，不需要改字段类型。

## 数据模型

**Translation Entry**（主要字段）

| 字段 | 说明 |
| --- | --- |
| `source_text` | 原文，**必须与运行时 msgid 逐字节一致**（含 HTML 实体与转义） |
| `translated_text` | 译文 |
| `language` | 目标语言，默认 `zh` |
| `app_name` / `module_name` | 来源 app / 模块 |
| `source_type` / `source_path` / `line_number` | 来源类型与出处 |
| `context` | 上下文（过长会截断并追加 hash 后缀） |
| `status` | `Pending` / `Translated` / `Reviewed` |
| `translation_source` | `Manual` / `AI` / `Dictionary` / `Imported` |
| `change_status` | `New` / `Unchanged` / `Changed` / `Suspected Deleted` / `Restored` |
| `is_translatable` / `ignore_reason` | 被判定为无需翻译的串不会删除，只打标记，保证可追溯 |
| `resource_key` / `hash_key` | 用于跨扫描匹配同一条资源 |

**Translation Project**：把一个目标语言下的一批条目组织成项目。字段有 `Status`（`Draft / Scanning / Translating / Completed`）和三个计数 `total_count / translated_count / pending_count`。计数在**保存时重新计算**：按目标语言对应的 `language` 别名，统计 `is_translatable = 1` 的条目总数、已译（`Translated` + `Reviewed`）和待译（`Pending`）。`Status` 目前只是可选值，扫描和翻译流程不会自动改它。

## 翻译从哪来

1. **官方目录**：`<app>/<app>/locale/<lang>.po`（编译为 `.mo`）。这些是 frappe / erpnext 自带的译文，直接用，不重复翻译。
2. **内置词典**：`translator/dictionary.py` 的通用词条 + `translator/business_dictionary.py` 的业务术语（采购、销售、库存、财务等），翻译结果要过 `is_good_translation()` 才会入库。
3. **人工 / CSV**：导出 → 翻译 → 导回。

Frappe 渲染页面时会依次读三个来源：`<app>/translations/<lang>.csv`、`<app>/locale/<lang>.po`、站点 `Translation` 表（最后应用）。
本 app 写的是**站点 `Translation` 表**——立即生效、按站点隔离、不碰任何 app 的工作区。

## 设计取舍

- **只写站点 `Translation` 表**：升级安全，`bench update` 不会覆盖你的翻译。
- **不改写 `source_text`**：它必须和运行时传给 `_()` 的消息完全一致，所以导入 CSV 时只认原文、只更新译文。
- **导入不覆盖已有译文**：`Import Translated CSV` 和 `Import From Catalogue` 都只填空缺，避免误伤已经人工校对过的内容。
- **`is_translatable = 0` 而不是删除**：噪声数据保留标记，扫描可重复执行且幂等。
- **单文件错误用 savepoint 回滚**：扫到坏文件不会把整次扫描的数据一起丢掉。
- **扫描仓库根目录而不是 Python 包目录**：`frappe.get_app_path()` 只指向 `<app>/<app>`，Vue / 现代前端的文案在平级的 `desk/`、`frontend/` 里；`os.walk` 不跟随软链，顺带把 `node_modules` 里的 vendored 包排除在外。
- **进度值放 Redis 且读取时 `expires=True`**：worker 与轮询请求不在同一进程，只能走 `frappe.cache`；必须绕过进程本地缓存，否则第一次轮询（worker 还没上报）会把 `None` 缓存下来，之后一直读到 `None`。
- **非 ASCII 单条 Redis 锁 → RQ 原生去重**：自定义锁在 worker 崩溃时会泄漏，导致按钮长时间无响应；改用 `job_id` + `deduplicate=True` 后由 RQ 自己管生命周期。
- **导出 CSV 带 BOM**：避免 Excel 打开中文乱码。
- **写一条发一条，批量结束再统一发一次**：发布是 `Translation Entry` → 站点 `Translation` 表那一步，原先要用户手动点。现在列表里保存走 `on_update` 钩子立即发布；批量任务用裸 SQL / `doc.save()` 写几千条，逐条发布等于每条清一次翻译缓存，所以任务里跳过钩子、结束时统一发布一次（`frappe.local.job` 用来区分这两者）。
- **`Translation Entry` 覆盖站点已有译文**：它是译文的唯一事实来源。`export_to_site(overwrite=False)` 会把「站点已有且内容不同」的条目记成冲突后丢弃——而用户在这个界面里改的恰恰就是这些条目，静默丢弃等于按钮点了白点。所以默认改为 `overwrite=True`。
- **补丁存成 `*.patch` 而不是脚本**：`patch` 是操作系统本来就有的东西，diff 可读可 review，应用/撤销/状态判断都能靠 `patch --dry-run` 的返回码直接得出，不需要自建一套版本记录。
- **补丁状态判断必须先试正向**：一个从没被改过的文件，正向和反向 dry-run 都会成功；顺序反了会把「还没打上」误判成「已打上」。
- **补丁引入的字符串用 `patch_name + 文本` 做 context**：`Translation Entry` 的 `resource_key` 由「路径 + 行号 + context」组成、不含文本，同一行出现多个 msgid 时会被折成一行互相覆写。把补丁名和文本写进 context 既区分了同行的多个串，也说明了这串是从哪来的。
- **单条 upsert 必须在 Python 侧比大小写**（`exporter.publish_one`）：MySQL 的排序规则大小写不敏感，`WHERE source_text = %s` 会把 `'Getting started'` 匹配到已有的 `'Getting Started'` 上，两边值一样就被判成「无需改动」而永远不落地——而前端是大小写敏感的 JS 对象查找，于是怎么点都不显示中文。改成取回真实 `source_text` 在 Python 侧逐字节比较后才正确插入。
- **漏译体检用「有没有大写字母」区分文案与标记**：模板里的 class 串、style 值、模板 id 全是小写，写给用户看的文案几乎都带大写；去噪后 2,191 条候选降到 993 条，前几十行基本都是能直接行动的文案。这条判据是启发式的，纯小写的短标签（如 `disabled`）会被漏掉，属于有意为之的取舍。

## 目录结构

```
wlh_translate/
├── api.py                    # 白名单接口：任务入队、进度查询、统计
├── install.py                # after_install：把站点/用户语言切成中文
├── hooks.py                  # 资源注册、列表页 JS、保存即发布（doc_events）
├── scanner/scanner.py        # 源码 / JSON / .po 扫描与去噪
├── importer/
│   ├── po_importer.py        # 读官方 .po 目录，填充空缺译文
│   └── csv_importer.py       # 导回翻译好的 CSV
├── exporter/exporter.py      # 导出待翻译 CSV / 按 app 打包 / 发布到站点
├── translator/
│   ├── base.py               # Translator 抽象基类
│   ├── dictionary.py         # 通用词典
│   ├── business_dictionary.py# 业务术语词典
│   └── translator.py         # 翻译入口与质量校验
├── patcher/
│   ├── patcher.py            # 上游补丁：列表/状态/应用/撤销/重建
│   └── library/              # 补丁库：<app_name>/<patch_name>.patch
├── auditor/auditor.py        # 漏译体检：找出够不到翻译表的模板文案
├── cleaner/cleaner.py        # 存量数据清理
├── utils/language.py         # 语言代码归一化（zh-CN → zh）
├── utils/progress.py         # 后台任务进度上报（Redis，带 TTL）
├── patches/v1_0/             # 数据迁移补丁
├── public/js/                # 列表页按钮、应用选择框与进度状态条
├── translations/zh.csv       # 本 app 自带的中文界面翻译
└── wlh_translate/            # DocType / Workspace / Number Card
```

## 开发

本 app 使用 `pre-commit` 做代码格式化与检查，请先安装并启用：

```bash
cd apps/wlh_translate
pre-commit install
```

pre-commit 配置了以下工具：

- ruff（`--select=I` 排序 import、lint、format）
- prettier
- eslint
- 以及 `check-ast` / `check-json` / `check-toml` / `check-yaml` / `debug-statements` 等基础钩子

> 注意：`.py` 的缩进风格由 `pyproject.toml` 的 `[tool.ruff.format] indent-style = "tab"` 和 `.editorconfig` 规定为 **Tab**。

## 许可

MIT
## Changelog
- 2026-10-09: 首次同步到 GitHub
