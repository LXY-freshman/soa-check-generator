# BCDA V1.3 覆盖基线

## 反向端口去重与曲线导出回归

2026-11-09 修复规则身份后，用原生 `soa_spe.mdl` 重新验证：1526 条解析规则全部进入导出选择；`n18_iso_ckt`、`n50_iso_ckt`、`nld12_iso_ckt` 的 Vds 条件曲线分别保留 7、8、6 段。合并 MIS 模型后，n18/n50 的体源电压检查均仅保留原生 `v(s,b)`，不再补出反向 `v(b,s)` 推断候选。以下全量统计保留为修复前的历史快照，冲突数不应视为当前判断结果。

本次只读验证使用远程 BCDA V1.3 已解压目录中的 17 个文件：器件列表、Spectre 原生 SOA 文件和 `models/spectre` 下全部 15 个 `.mdl/.ckt/.lib` 文件。原始文件只在临时目录中解析，没有进入 Git。

## 统计

- 器件：673
- 规则：2368
- 原生 Spectre SOA：1526
- 拓扑候选：62
- 推断候选：534
- 空值候选：246
- 模型有明确来源的器件：650
- 仅在器件列表中、尚未匹配模型文件的器件：23
- 物理检查矩阵状态：`source` 515、`inferred` 251、`conflict` 92、`missing` 2026、`not_applicable` 266
- 器件分类：MOS 74、LDMOS 184、DEMOS 7、二极管 87、BJT 212、电阻 71、Varactor 10、电容 10、未知 18

## 真实器件核对

| 器件 | 端口识别 | 档案状态 | 观察 |
|---|---|---|---|
| `nld12_iso_ckt` | `D/G/BS/NBL/PSUB` | enriched | `Vgs=5.5V` 来自原生 SOA；`NBL-PSUB`、`NBL-BS`、`NBL-D` 仍是推断候选 |
| `nld12_ls_ckt` | `D/G/BS` | enriched | 没有隔离端口；`BS` 被识别为体源端 |
| `nde12_iso_ckt` | `D/G/S/B/NBL/PSUB` | enriched | 原生 `Vgs/Vbd/Vgb` 已绑定；仍有完整值缺失和一处来源冲突 |
| `n50_iso_ckt` | 未从本轮模型文件补齐 | skeleton | 器件列表有名称，但端口档案需要更多模型文件或 CDF/OA 信息 |
| `n18_iso_ckt` | `D/G/S/B/NBL/PSUB` | enriched | 端口来自 MIS Spectre 模型；原生 `Vgs/Vbs/Vbd/Vgb` 已绑定；Vds 曲线留在原生表达式中；NBL 隔离值为空待确认 |
| `n50_iso_ckt` | `D/G/S/B/NBL/PSUB` | enriched | 端口来自 MIS Spectre 模型；原生 `Vgs/Vbs/Vbd/Vgb` 已绑定，Vbs 与标量模型候选有冲突；NBL 隔离值为空待确认 |

## 解释

原生 SOA 中的 Vds 曲线通常是带 Vgs 条件的表达式，没有单独的 `max/min`。覆盖解析现在把这类曲线保留为原生来源，同时不把模型推断的绝对端子值误报为同一来源冲突。剩余 62 个冲突表示多个完整数值来源确实给出了不同边界，需要用户或后续工艺规则选择。

`missing` 不是解析失败总数。它包含物理矩阵中适用但尚未获得可靠数值的检查，正是后续补模型端口、手册限值和工艺适配器的工作清单。

模型来源链已验证：`nld12_iso_ckt` 的端口档案记录了 HV MOS Spectre 模型文件和定义行号。只选 HV MOS 文件时匹配率为 193/409；加载完整 Spectre 模型目录后提升到 650/673。

加载整个 Spectre 模型目录后，覆盖升到 650/673。剩余 23 个器件包括 7 个 pocket helper，以及器件列表中的通用 NPN/PNP cell；模型文件中对应 BJT 实例通常带面积参数名（例如 `pnp18a100_mis_ckt`），通用 cell 到具体参数模型的映射需要 CDF/OA 信息，当前不自动猜测。该路径按项目约束继续暂停。

对只有 `iso` 拓扑、没有隔离等级数字的器件，不再把 MOS 族电压当隔离耐压。矩阵保留 `NBL-PSUB/NBL-B/NBL-D` 空值检查，直到手册、原生 SOA 或用户提供独立隔离等级。该保护现已在真实 n18/n50/nld12/nde12 档案中验证。
