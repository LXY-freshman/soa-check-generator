# 工艺适配器

适配器是独立的 `soa-adapter/v1` JSON 文件。它只覆盖器件分类和工艺命名线索，不修改原始 PDK。

复制 `example.json` 后修改 `id`、`version` 和 `device_rules`，再通过网页适配器文件入口或 API 的 `adapter_config` 字段导入。

`pattern` 使用 Python 正则表达式；匹配后可设置 `category`、`family`、`scope`、`family_voltage`、`isolation_voltage` 和 `topology`。没有匹配的器件继续使用内置规则。
