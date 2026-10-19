# 运行与演示手册

## 环境准备

从源码仓库根目录执行，使用 Python 3.11+、Git 和已启动的 Docker：

```bash
make setup
docker pull python:3.11-slim
make serve
```

浏览器打开 `http://127.0.0.1:8765`。前端不需要构建。开发格式检查另执行 `make setup-ui`、`make lint`；Python 测试使用 `make test`。

## 零费用演示

选择默认的平均值修复任务，运行方式保持“固定脚本演示”。点击开始，观察先失败的原有测试、源码修改和后续测试。切换“代码补丁”和“独立验证”，查看干净副本中的三个独立用例和原有回归结果。演示不调用模型，也不证明模型修复能力。

窄窗口下的验收截图见 [工作台运行结果](images/workbench-mobile.png)。

任务集页面分别标记人工题与公开历史题；实验记录保留失败批次。预算查询：

```bash
PYTHONPATH=src .venv/bin/python -m repofix budget
```

## 真实 DeepSeek 首次验收

在本机将 `.env.example` 复制为 `.env`，填写 Key、模型名称、当前人民币每百万 token 单价。已导出的环境变量优先，配置错误不会回显原值。修改已经加载的配置后重启服务；不要把 Key 发到聊天或提交到 Git。

先运行一个任务：

```bash
PYTHONPATH=src .venv/bin/python -m repofix run \
  --repo examples/tinybug/repo --issue examples/tinybug/issue.md \
  --verification examples/tinybug/verification \
  --tool-mode structured --context-mode compact --task-budget 1
```

检查 provider、evidence_type、request_reservations、usage、diff、独立测试及原有回归。这个任务与公开演示相同，只适合检查真实连接与协议。之后按 [实验协议](experiment-protocol.md) 运行历史任务及四组对照。

## 常见诊断

| 状态 / 原因 | 处理 |
|---|---|
| Docker daemon unavailable | 启动 Docker Desktop，确认 `doctor` 可用 |
| Docker image unavailable | 提前拉取或构建镜像；任务容器不联网安装依赖 |
| preflight_failed / collection_error | 检查依赖与测试入口；此阶段不调用模型 |
| model_output_limit | 输出被截断，未执行残缺工具调用；审查轨迹后调整方案 |
| policy_violation | 查看被修改的已有测试或配置路径 |
| new_regression_failures | 独立 Bug 用例可能通过，但补丁破坏了原有功能 |
| budget_limit | 查看已结算估算及保留预留；不要通过换输出目录绕过总预算 |
| resume_refused / in_flight | 执行状态不明确，先审查轨迹；程序不会自动重复命令或请求 |

## 断点恢复演示

```bash
PYTHONPATH=src .venv/bin/python scripts/resume_smoke.py
```

脚本在第一轮后停止，再使用同一任务继续，验证没有重复执行已经完成的命令。它仍是固定脚本验收。

## 录屏建议

两分钟即可：20 秒说明问题与证据来源；50 秒展示执行反馈和 diff；30 秒展示独立测试、回归与费用；20 秒说明失败案例和当前实验局限。真实模型尚未运行时，录屏中应保留“固定脚本演示”的标记。
