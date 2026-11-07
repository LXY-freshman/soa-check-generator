# 开发与版本管理

本项目使用 Git 管理。源码、测试、文档和可复现的项目配置进入版本库；工艺原始文件、SSH 凭据、密码、临时输出、日志和本地截图不进入版本库。

## 日常流程

1. 从 `main` 创建短生命周期分支，例如 `feature/model-parser` 或 `fix/rule-grouping`。
2. 每次提交只完成一个可描述的变更，提交信息使用动词开头，例如 `Add BCDA model metadata parser`。
3. 提交前运行：

   ```bash
   python3 -m compileall -q soa_generator
   python3 -m unittest discover -s tests -v
   node -e "const fs=require('fs');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(s);console.log('web script syntax ok')"
   ```

4. 检查 `git diff --check` 和 `git status`，确认没有工艺文件、凭据或临时输出。
5. 功能完成后合并回 `main`，同时更新 `docs/PROJECT_PLAN.md` 和必要的 ADR/词汇表。

## 数据与隐私边界

- PDK 原始目录只读，不复制进仓库。
- 项目 JSON 可以保存规则来源和用户覆盖，但不得保存 SSH 密码或私钥内容。
- `human/` 截图只用于本地界面调试，默认被 Git 忽略。
- 远程调查结果只记录脱敏后的路径模式、版本和规则事实。

## 提交前检查

- 新增解析器必须有最小真实样例或单元测试。
- 规则合并、推断和导出变更必须验证来源与输出内容。
- UI 变更需要检查窄窗口、长路径、长表达式和空状态。
