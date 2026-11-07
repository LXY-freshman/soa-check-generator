# Changelog

## Unreleased

- 增加 Spectre `subckt`/`inline subckt` 端口解析，识别 `nbl`、`psub`、`pepi`、`iso` 等拓扑端口。
- 根据模型端口和器件命名生成隔离耐压候选规则；候选默认关闭，并在界面标记为推断、待确认。
- 识别常见 `nch2d5`、`nch3d3` 和 `nbl_7v`/`nbl_12v` 等工艺命名中的电压信息。
- 规则卡显示来源确认状态和推断说明，避免把候选规则误当成工艺原生规则。
- 规则保存并显示结构化端口对；原生隔离检查优先于推断候选。
- 增加脱敏模型端口 fixture 和解析测试。
- 区分普通 `bsource` 与 `gsoa`/`soa_*` 模型内 SOA，并在解析结果区显示每个文件的处理状态。
- 增加模型内 SOA 导出模式：原生引用、来源提示、近似输出、双输出；网页和 CLI 共用同一套模式。
- 增加电阻、二极管、BJT、Varactor、MIM/MOM、ESD 类别规则候选；三端电阻分别生成端子对衬底检查，所有非原生候选默认关闭。
- 增加本机/SSH Spectre 快速检查，解析临时主网表、SOA section 和 Spectre 日志，并将语法、目标器件和规则参数问题显示在界面中。

## Unreleased

- 建立本地浏览器 + Python 服务的 SOA 导入、编辑和导出基线。
- 支持 Spectre `assert` 的 `sub/subs` 解析、规则分组、min/max 合并和用户规则。
- 支持本机/SSH 路径扫描、器件树、来源证据和导出集总览。
- 记录 BCDA、A6217、TPS6282、UCC21750、UNT PDK 调查结果。
