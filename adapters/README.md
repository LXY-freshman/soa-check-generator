# 工艺适配器

适配器是独立的 `soa-adapter/v1` JSON 文件。它只覆盖器件分类和工艺命名线索，不修改原始 PDK。

复制 `example.json` 后修改 `id`、`version` 和 `device_rules`，再通过网页适配器文件入口或 API 的 `adapter_config` 字段导入。

`pattern` 使用 Python 正则表达式；匹配后可设置 `category`、`family`、`scope`、`family_voltage`、`gate_voltage`、`isolation_voltage` 和 `topology`。没有匹配的器件继续使用内置规则。

适配器也可以提供 `check_rules` 作为手册/工艺表证据。每条规则必须有 `pattern` 和 Spectre `expr`，可填写 `limit_kind`、`maximum`、`minimum`、`terminal_pair`、`source_path`、`page` 和 `note`。这些规则会以 `documented` 置信度进入来源解析，原始 PDK 不会被修改。
