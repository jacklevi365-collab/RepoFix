# 开发与验证

Python 3.11+；Docker 用于执行目标代码。前端是静态 HTML/CSS/JavaScript，无运行时构建步骤。Node.js 仅用于源码格式检查。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.lock
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
npm ci --ignore-scripts
npm run lint
npm test
```

Docker 验收命令见 CI 工作流：固定脚本演示、人工任务与上游历史任务的参考补丁验证、结构化工具验收、断点恢复验收。所有 CI 检查都不调用付费模型。

提交格式统一为 `类型: 中文改动描述`，每个提交聚焦一个模块。常用类型包括 feat、fix、test、docs、refactor、ci、chore。先确认检查结果，再提交推送。

不要提交 `.env`、`runs/`、密钥或本机虚拟环境。不要格式化 `benchmarks/real/*/repo/`：它们是固定上游版本，源文件哈希与许可证用于保证任务来源。参考补丁文件保留合法 unified diff 空行，Git 属性只对这些 `.patch` 文件关闭空白检查。

新增指标时必须同时保留数据来源、任务清单、配置、失败项和原始证据。脚本演示与参考补丁验证不能计入模型成功率。无实际模型运行时，相关指标标为待验证。
