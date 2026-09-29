# Wlh Translate

面向 Frappe / ERPNext 的中文翻译扫描与管理工具。

把散落在各个 app 源码里的可翻译文案扫出来、集中到一张表里翻译，再一次性发布到站点。
全程只写站点自己的 `Translation` 表，**不改 frappe / erpnext 源码**，`bench update` 升级不受影响。

- **适用版本**：Frappe Framework v16（`version-16` 分支）
- **默认目标语言**：`zh`（简体中文）
- **许可**：MIT

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [主要能力](#主要能力)
- [工作流程](#工作流程)
- [安装](#安装)
- [快速上手](#快速上手)
- [界面说明](#界面说明)
- [怎么搜索源文本](#怎么搜索源文本)
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
| 源码扫描 | 递归扫描已安装 app 的 `.py` `.js` `.html` `.htm` `.jinja`，识别 `_()` / `__()` / `frappe._()` 调用 |
| 元数据扫描 | DocType / Workspace / Report / Print Format 等 `.json` 里的 `label`、`description`、`options`、`title`、`message` 等文案字段 |
| 官方清单对齐 | 读取 `<app>/<app>/locale/zh.po` 的**全部 msgid（含未翻译项）**，保证不漏 |
| 种子数据扫描 | `setup_wizard/data/*.json` 里面向用户的文案（如 `Litre`、`Cubic Yard`） |
| 自动去噪 | 过滤 CSS class、纯符号/数字、字段名等"看起来是文案其实不是"的串；跳过测试夹具（`test_records.json`、`test_data_*.json`）和国别科目表种子（`country_wise_tax.json`） |
| 词典翻译 | 内置业务术语词典 + 通用词典，带质量校验（无中文、残留大量英文、中英粘连会被拒绝入库） |
| CSV 往返 | 导出待翻译清单 → 分工翻译 → 导回；导出带 BOM，Excel 直接打开不乱码 |
| 按 app 导出 | 一个 app 一个 CSV，打包成 zip，方便按模块分工 |
| 发布到站点 | 写入站点 `Translation` 表并清缓存，**立即生效**，不动任何 app 的 git 工作区 |
| 后台任务 | 耗时操作走 RQ `long` 队列，前端轮询进度；`job_id` + `deduplicate` 防重复提交，另有 `Reset Stuck Job` 兜底 |
| 变更跟踪 | `New / Unchanged / Changed / Suspected Deleted / Restored`，源码改文案或删文案都能看出来 |
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
                     │  ⑤ Export To Site
                     ▼
             站点 Translation 表 ──► 界面立刻显示中文
```

`Source Type` 会记录文案的来源（`DocField` / `Label` / `Message` / `JS` / `Python` / `HTML` / `Workspace` / `Report` / `Other`），`Source Path` + `Line Number` 保留出处，方便回查。

## 安装

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/<你的用户名>/wlh_translate --branch version-16
bench install-app wlh_translate
```

安装完成后 `after_install` 会自动把站点语言、全局默认语言以及现有用户的语言切成中文
（Frappe 取语言有优先级：`User.language` → `System Settings.language` → 站点配置 → `en`，只改站点默认值会被用户自己的设置盖掉）。

## 快速上手

1. 进入 `/desk`，首页 **Framework** 图标 → **Wlh Translate**。
2. 打开 **Translation Entry**，右上角 **Bulk Jobs** → **Scan All Apps**，等任务跑完（页面会自动轮询并提示结果）。
3. **Import From Catalogue**：把 frappe / erpnext 官方 `.po` 里已有的译文灌进来，Pending 数量会大幅下降。
4. **Translate Pending**：跑一遍词典翻译，剩余的需要人工处理。
5. **Export Pending CSV**（全部）或 **Export All By App**（按 app 拆分成 zip）导出，分工翻译后用 **Import Translated CSV** 导回。
6. **Export To Site**：发布，界面立刻变中文。

> 任务在 `long` 队列上执行，超时 6 小时。需要 `bench start` 或 `bench worker`（RQ worker）在跑。

## 界面说明

**Translation Entry** 列表页右上角的按钮：

| 按钮 | 作用 |
| --- | --- |
| Bulk Jobs → **Scan All Apps** | 扫描所有已安装 app，把新文案写进 Translation Entry，并标记已消失的文案为 `Suspected Deleted` |
| Bulk Jobs → **Translate Pending** | 对所有 Pending 条目跑词典翻译，过不了质量校验的保持 Pending |
| Bulk Jobs → **Import From Catalogue** | 从各 app 的 `locale/zh.po` 填充空缺译文，**不覆盖**已有译文 |
| Bulk Jobs → **Export To Site** | 把 `Translated` / `Reviewed` 的条目发布到站点 `Translation` 表并清缓存 |
| **Export Pending CSV** | 导出待翻译清单（按 `source_text` 去重，一行一个原文） |
| **Export All By App** | 按 app 分组导出成 zip，每个 app 一个 CSV |
| **Import Translated CSV** | 导回翻译好的 CSV，只填空缺、不改写 `source_text`、不覆盖已有译文 |
| **Reset Stuck Job** | 清理卡在 queued / running 的任务记录（仅在真的卡住时使用） |

首页还有三张数字卡片：总条目数 / 待翻译 / 已翻译。

## 怎么搜索源文本

列表页筛选行里的 **源文本** 输入框就是搜索框，直接输入关键字即可，**不需要自己加 `%`**。

- 框左侧的切换按钮显示 **`≈`** 时是模糊匹配（等价于 `like %关键字%`）；
- 显示 **`=`** 时是精确相等，点一下按钮可以切换。

> 实现细节：`source_text` 故意用 `Text` 而不是 `Long Text`。Frappe 只会把 `Text / Small Text / Data` 这类字段渲染成「单行输入 + 模糊匹配」的筛选框，`Long Text` 会退化成只能精确匹配的大文本框——这正是"搜不到"的常见原因。

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

**Translation Project**：把一个目标语言下的一批条目组织成项目，带 `Draft / Scanning / Translating / Completed` 状态与总数 / 已译 / 待译统计。

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
- **非 ASCII 单条 Redis 锁 → RQ 原生去重**：自定义锁在 worker 崩溃时会泄漏，导致按钮长时间无响应；改用 `job_id` + `deduplicate=True` 后由 RQ 自己管生命周期。
- **导出 CSV 带 BOM**：避免 Excel 打开中文乱码。

## 目录结构

```
wlh_translate/
├── api.py                    # 白名单接口：任务入队、进度查询、统计
├── install.py                # after_install：把站点/用户语言切成中文
├── hooks.py                  # 资源注册、列表页 JS、全局搜索
├── scanner/scanner.py        # 源码 / JSON / .po 扫描与去噪
├── importer/
│   ├── po_importer.py        # 读官方 .po 目录，填充空缺译文
│   └── csv_importer.py       # 导回翻译好的 CSV
├── exporter/exporter.py      # 导出待翻译 CSV / 按 app 打包 / 发布到站点
├── translator/
│   ├── dictionary.py         # 通用词典
│   ├── business_dictionary.py# 业务术语词典
│   └── translator.py         # 翻译入口与质量校验
├── cleaner/cleaner.py        # 存量数据清理
├── utils/language.py         # 语言代码归一化（zh-CN → zh）
├── patches/v1_0/             # 数据迁移补丁
├── public/js/                # 列表页按钮与进度轮询
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

- ruff
- eslint
- prettier
- pyupgrade

## 许可

MIT