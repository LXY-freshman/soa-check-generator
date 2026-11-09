# BCDA V1.3 覆盖基线

本次只读验证使用远程 BCDA V1.3 已解压目录中的三类文件：器件列表、Spectre 原生 SOA 文件和 HV MOS Spectre 模型。原始文件只在临时目录中解析，没有进入 Git。

## 统计

- 器件：409
- 规则：1913
- 原生 Spectre SOA：1526
- 拓扑候选：99
- 推断候选：288
- 物理检查矩阵状态：`source` 428、`inferred` 212、`conflict` 62、`missing` 1272、`not_applicable` 143
- 器件分类：MOS 54、LDMOS 184、DEMOS 7、二极管 63、BJT 33、电阻 47、Varactor 10、电容 4、未知 7

## 真实器件核对

| 器件 | 端口识别 | 档案状态 | 观察 |
|---|---|---|---|
| `nld12_iso_ckt` | `D/G/BS/NBL/PSUB` | enriched | `Vgs=5.5V` 来自原生 SOA；`NBL-PSUB`、`NBL-BS`、`NBL-D` 仍是推断候选 |
| `nld12_ls_ckt` | `D/G/BS` | enriched | 没有隔离端口；`BS` 被识别为体源端 |
| `nde12_iso_ckt` | `D/G/S/B/NBL/PSUB` | enriched | 原生 `Vgs/Vbd/Vgb` 已绑定；仍有完整值缺失和一处来源冲突 |
| `n50_iso_ckt` | 未从本轮模型文件补齐 | skeleton | 器件列表有名称，但端口档案需要更多模型文件或 CDF/OA 信息 |
| `n18_iso_ckt` | 未从本轮模型文件补齐 | skeleton | 原生 `Vgs` 已绑定，其他物理检查仍需端口证据 |

## 解释

原生 SOA 中的 Vds 曲线通常是带 Vgs 条件的表达式，没有单独的 `max/min`。覆盖解析现在把这类曲线保留为原生来源，同时不把模型推断的绝对端子值误报为同一来源冲突。剩余 62 个冲突表示多个完整数值来源确实给出了不同边界，需要用户或后续工艺规则选择。

`missing` 不是解析失败总数。它包含物理矩阵中适用但尚未获得可靠数值的检查，正是后续补模型端口、手册限值和工艺适配器的工作清单。
