# 需求追踪

这份表把前几轮讨论中的主要需求和当前实现状态对应起来，区分“已经记录”和“已经实现”。

## 已记录并已实现

| 需求 | 记录位置 | 实现状态 |
|---|---|---|
| PDK 版本明确、原始资料只读、用户覆盖写入派生文件 | ADR 0001、GLOSSARY | 已实现 |
| 本机/SSH 路径、密码输入、禁止私钥输入、脱敏错误 | ADR 0002/0004、DEVELOPMENT | 已实现 |
| Spectre `sub/subs`、min/max 合并、来源证据 | ADR 0003、PROJECT_PLAN | 已实现 |
| 模型内 `gsoa/bsource` 与外部 assert 分开 | ADR 0003、PROJECT_PLAN | 已实现 |
| 端口、隔离环、NBL/PSUB/PEPI、组合器件 | ADR 0006/0007、GLOSSARY | 已实现基础版；端口档案明确区分 `PSUB=bulk_substrate` 与 `NBL/PEPI/ISO=isolation_structure` |
| MOS 和非 MOS 模型参数/命名推断候选 | ADR 0005、PROJECT_PLAN | 已实现基础版 |
| 工艺手册限值作为独立证据参与规则选择 | ADR 0005/0007、适配器文档 | `soa-adapter/v1.check_rules` 已实现，保留路径、页码、备注和 `documented` 置信度 |
| 直接解析选中的手册文本/PDF | PROJECT_PLAN、GLOSSARY | 已实现行内限值和表头/器件行/续行表格提取；曲线、典型值和范围保留为未转换证据 |
| 真实 PDK 覆盖验证 | PROJECT_PLAN、远程 PDK 研究记录 | 已完成 BCDA V1.3 脱敏基线；页面和 `/api/coverage` 提供摘要，端口缺失、完整值缺失和来源冲突进入后续工作清单 |
| 用户规则复制、删除、恢复、覆盖和导出 | PROJECT_PLAN、GLOSSARY | 已实现 |
| 父器件/子器件依赖导出 | ADR 0006、GLOSSARY | 已实现基础版 |
| Spectre 快速检查 | PROJECT_PLAN、README | 已实现 |
| `soa-project/v1`、`soa-adapter/v1`、AGENTS.md | M4 计划、适配器文档 | 已实现 |

## 已记录但尚未实现

| 需求 | 记录位置 | 当前状态 |
|---|---|---|
| 按物理结构生成完整检查矩阵和 `not_applicable` | ADR 0007、PROJECT_PLAN | 已覆盖 MOS/LDMOS/DEMOS、二极管、BJT、电阻、无源和 ESD 的基础端子、体二极管、电流密度与隔离候选；仍需补充工艺手册适用性和更多特例 |
| 解析来源类别优先级拖动 | ADR 0007、GLOSSARY | UI、解析响应和项目保存已实现 |
| 冲突项目单独选择来源路线 | ADR 0007、GLOSSARY | 后端按优先级选出唯一候选，规则卡可停用同组其他候选并记录用户确认 |
| “生成推断值”按钮，填空但不自动启用 | ADR 0007、PROJECT_PLAN | 已实现 |
| 规则摘要显示边界、来源和颜色提示 | PROJECT_PLAN | 已实现基础版 |
| 导出前可信度检查、上下跳转、强制导出审计 | ADR 0007、GLOSSARY | 已实现基础版 |
| CDF/OA 终端顺序和参数表 | PROJECT_PLAN | 暂停，需 Virtuoso/OA API |

## 暂缓或有意不做

| 需求 | 决定 |
|---|---|
| Vds/Vgs 区域图 | 暂缓，当前收益不足 |
| 自动把模型内 gsoa 等价转换成 assert | 保留原生/近似/双输出选项，不声称等价 |
| 回写原始 PDK | 永久不做 |
