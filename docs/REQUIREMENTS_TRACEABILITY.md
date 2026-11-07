# 需求追踪

这份表把前几轮讨论中的主要需求和当前实现状态对应起来，区分“已经记录”和“已经实现”。

## 已记录并已实现

| 需求 | 记录位置 | 实现状态 |
|---|---|---|
| PDK 版本明确、原始资料只读、用户覆盖写入派生文件 | ADR 0001、GLOSSARY | 已实现 |
| 本机/SSH 路径、密码输入、禁止私钥输入、脱敏错误 | ADR 0002/0004、DEVELOPMENT | 已实现 |
| Spectre `sub/subs`、min/max 合并、来源证据 | ADR 0003、PROJECT_PLAN | 已实现 |
| 模型内 `gsoa/bsource` 与外部 assert 分开 | ADR 0003、PROJECT_PLAN | 已实现 |
| 端口、隔离环、NBL/PSUB/PEPI、组合器件 | ADR 0006/0007、GLOSSARY | 已实现基础版 |
| MOS 和非 MOS 模型参数/命名推断候选 | ADR 0005、PROJECT_PLAN | 已实现基础版 |
| 用户规则复制、删除、恢复、覆盖和导出 | PROJECT_PLAN、GLOSSARY | 已实现 |
| 父器件/子器件依赖导出 | ADR 0006、GLOSSARY | 已实现基础版 |
| Spectre 快速检查 | PROJECT_PLAN、README | 已实现 |
| `soa-project/v1`、`soa-adapter/v1`、AGENTS.md | M4 计划、适配器文档 | 已实现 |

## 已记录但尚未实现

| 需求 | 记录位置 | 当前状态 |
|---|---|---|
| 按物理结构生成完整检查矩阵和 `not_applicable` | ADR 0007、PROJECT_PLAN | 基础候选已实现，完整适用性矩阵待实现 |
| 解析来源类别优先级拖动 | ADR 0007、GLOSSARY | UI 和项目保存已实现 |
| 冲突项目单独选择来源路线 | ADR 0007、GLOSSARY | 待实现 |
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
