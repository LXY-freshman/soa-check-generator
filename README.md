# SOA 检查语句生成器

本项目是一个本地浏览器工具，用于导入用户选择的模型文件，查看 SOA（安全工作区）规则和来源证据，编辑派生检查，并导出 Spectre 或 JSON 结果。

公开仓库只包含源码、合成测试夹具和通用适配器示例，不包含工艺库、模型文件、设计手册、凭据、截图或个人路径。

## 本地运行

兼容支线需要 Python 3.6.6 或更高版本，主要面向 Linux/RHEL7.9：

```bash
python3.6 -m soa_generator.service --port 8765
```

然后打开 `http://127.0.0.1:8765/`。服务只读取用户主动选择的文件和目录，支持本机路径以及只读 SSH 路径。压缩包和未解压的工艺包不在处理范围内。

Python 3.6.6 需要先安装 `requirements-py36.txt` 中的 `dataclasses`。需要 PDF 手册解析时，再安装其中的 `pypdf`。内网环境可以使用准备好的 wheel 目录离线安装：

```bash
python3.6 -m pip install --no-index --find-links /path/to/wheels -r requirements-py36.txt
```

## 命令行

```bash
python3.6 -m soa_generator.cli scan /path/to/models
python3.6 -m soa_generator.cli parse /path/to/soa-source.scs
python3.6 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs --formats spectre json
python3.6 -m soa_generator.cli export /path/to/soa-source.scs /tmp/soa-generated.scs \
  --adapter-config adapters/example.json
```

导入器支持 Spectre `assert`、模型内 SOA 线索、器件和子电路定义、端口拓扑以及用户选择的手册证据。推断值在用户确认前保持关闭；来源、机制和可信度会保存在派生项目 JSON 中，原始输入不会被修改。

## 工艺适配器

适配器是 `soa-adapter/v1` JSON 文件，用于映射用户自己的命名规则、器件族、端口角色、拓扑标记和有出处的检查值。仓库中的 `adapters/example.json` 是合成示例。实际工艺适配器和原始资料应保存在私有环境，不要提交到公开仓库。

## 测试

```bash
./run_py36_tests.sh
node -e "const fs=require('fs');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(s);console.log('web script syntax ok')"
```

`run_py36_tests.sh` 会执行 Python 编译检查和完整单元测试。该支线不要求独立可执行包，源码服务和 CLI 是主要交付方式。

## 隐私边界

请将工艺输入、模型文件、手册、SSH 凭据、私钥、截图、日志和生成归档保存在 Git 之外。公开 Issue 和 Pull Request 应使用合成复现，不要上传专有模型内容。
