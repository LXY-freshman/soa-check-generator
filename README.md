# SOA 检查语句生成器

当前版本已包含第一条可运行链路：扫描工艺路径、发现器件/SOA 源文件、解析 Spectre `assert`、选择规则并导出派生 `.scs` 和 `soa-project.json`。

## 启动本地浏览器工具

```bash
python3 -m soa_generator.service --port 8765
```

打开 `http://127.0.0.1:8765/`。来源可以是本机路径，也可以是 SSH 主机别名加远程路径。远程读取使用现有 SSH 配置和 BatchMode，只读访问。

## 命令行

```bash
python3 -m soa_generator.cli scan /path/to/pdk
python3 -m soa_generator.cli parse /path/to/soa_spe.mdl
python3 -m soa_generator.cli export /path/to/soa_spe.mdl /tmp/soa_generated.scs --formats spectre json
# 模型内 SOA 默认保留原生引用；也可以选择只记录或近似输出
python3 -m soa_generator.cli export /path/to/soa_spe.mdl /tmp/soa_generated.scs \
  --model-source /path/to/hvmos_spe.mdl --model-soa-mode native
```

解析器已经用远程 BCDA V1.3 的 `soa_spe.mdl` 做过真实验证：1,981 条规则、152 个 subckt 目标均可读取。

模型内 `gsoa/bsource` 文件支持四种导出模式：保留原生模型引用、只记录来源、只使用已启用外部规则的近似输出，以及原生模型加外部规则的双输出。近似输出不会重建模型曲线，双输出可能产生重复告警，项目 JSON 会保留警告。手册表格推断、复杂组合器件依赖和 Spectre 快速检查属于后续里程碑，详见 [项目计划](docs/PROJECT_PLAN.md)。
