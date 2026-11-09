# 工艺适配器

适配器是独立的 `soa-adapter/v1` JSON 文件。它只覆盖器件分类和工艺命名线索，不修改原始 PDK。

复制 `example.json` 后修改 `id`、`version` 和 `device_rules`，再通过网页适配器文件入口或 API 的 `adapter_config` 字段导入。

`pattern` 使用 Python 正则表达式；匹配后可设置 `category`、`family`、`scope`、`family_voltage`、`gate_voltage`、`isolation_voltage` 和 `topology`。没有匹配的器件继续使用内置规则。

适配器也可以提供 `check_rules` 作为手册/工艺表证据。每条规则必须有 `pattern` 和 Spectre `expr`，可填写 `limit_kind`、`maximum`、`minimum`、`terminal_pair`、`source_path`、`page` 和 `note`。这些规则会以 `documented` 置信度进入来源解析，原始 PDK 不会被修改。

`device_rules` 可声明 `isolation_type`（`unknown/junction/dielectric`）、`port_roles` 和 `isolation_junctions`。每个结使用 `p_port`、`n_port` 指定模型实际可访问的 P/N 端口，并可附 `source` 路径、页码、说明。只有模型或手册明确支持时才声明；引擎按 `V(N,P)` 生成反向耐压候选，按 `V(P,N)` 生成独立正向导通候选。所有自动候选默认关闭，缺值留空；不把 pocket 等级复制为内侧耐压，不预置统一 VF。标记 `dielectric` 时不生成衬底 PN 结检查。

例如不同端口命名的三层结构可以配置：

```json
{
  "pattern": "^custom_isolated_",
  "isolation_type": "junction",
  "port_roles": {"deep_well": "isolation_well", "substrate": "bulk_substrate"},
  "isolation_junctions": [
    {"p_port": "substrate", "n_port": "deep_well", "source": {"path": "manual.pdf", "page": 42}},
    {"p_port": "inner_pwell", "n_port": "deep_well", "source": {"path": "manual.pdf", "page": 43}}
  ]
}
```

具体器件若要求同电位，可用 `check_rules` 明确提供 `limit_kind: isolation_constraint`、`expr: v(body,deep_well)`、`maximum: "0"`、`minimum: "0"` 及来源，不能将此规则泛化到所有 PMOS。复合寄生路径、电流注入、温度和持续时间限制也应来自独立规则证据，不能声称几个静态电压检查已完整验证闩锁安全。
