# 真实模型实验协议

当前没有真实 DeepSeek 实验结果。下面是可直接执行的计划，而非成绩表。

## 固定条件

- `benchmarks/dev/manifest.json`：5 个人工开发任务，用于调试和策略选择。
- `benchmarks/real/manifest.json`：3 个公开上游历史回归任务，源码、原始版本、参考补丁和验证范围已固定。
- 每个任务：最多 12 轮，输出上限由模型适配器固定，thinking 关闭；使用同一模型与计费设置。
- 所有批次共用 `runs/budget.sqlite`。任务失败、预算终止、配置错误都保留在结果中。
- 原始版本必须复现失败；候选补丁必须通过独立测试，并不得让固定的原有测试出现新增失败。

## 2×2 对照

| Profile | 工具 | 上下文 |
|---|---|---|
| baseline | shell | full |
| context | shell | compact |
| tools | structured + shell | full |
| combined | structured + shell | compact |

```bash
# 只打印计划，不需要 Key，也不运行 Docker
python3 -m repofix matrix
# 本机配置 Key 和价格后才执行真实实验
python3 -m repofix matrix --execute --task-budget 2
# 如需先在开发集做同样实验
python3 -m repofix matrix --manifest benchmarks/dev/manifest.json --execute --task-budget 2
```

历史任务：3 × 4 × 2 = 24 元的本地任务上限合计。开发集：5 × 4 × 2 = 40 元。两组合计 64 元，100 元预算留有调试余量。实际扣费取决于 usage、配置价格和账户规则；本地预留不是供应商账单硬上限。

真实执行前会校验配置、预算以及原始失败和原有测试的可收集性。每完成一个策略批次，`runs/matrix-*/comparison.json` 原子保存结果；全部完成生成 `comparison.md`。每行都链接到对应批次的本地输出目录，原始逐任务报告、diff 和轨迹仍在 `runs/`。中断后不会自动重跑整组实验，避免无意重复计费；单个任务可按安全检查点恢复。

## 报告要求

记录精确的 X/N 通过数、所有失败原因、估算费用、耗时、token 与模型返回标识。别只挑成功任务展示。只有实际发生请求预留的批次才计算模型模式通过率；这仍是系统任务通过率，不是模型本身能力的独立测量。

三个历史任务来自同一库，样本小且公开，模型可能已经见过修复。它们不是 SWE-bench。一次对照结果不能证明普遍提升；上下文策略若未触发压缩，也不能据此声称压缩有效。费用还受缓存命中和执行顺序影响，耗时包含 Docker 启动和本机负载。

如要在简历中写百分比改善，应增加独立任务、重复运行，并保留对照结果；在此之前只写已经实现并验证的工程能力。
