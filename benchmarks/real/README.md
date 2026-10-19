# 真实历史回归任务 v1

这三个任务来自 [more-itertools](https://github.com/more-itertools/more-itertools) 的公开历史，原始代码使用 MIT 许可证，每份代码副本均保留 `LICENSE`。`manifest.json` 固定父提交、修复提交、链接及每个源码文件的 SHA-256。加载任务时校验原始文件，防止无意修改基线。

| 任务 | 上游修复 | 验证场景 |
|---|---|---|
| bucket-false-validator | [67fcf640](https://github.com/more-itertools/more-itertools/commit/67fcf640477c78605580f5ee703a54c73c1e7a8a) | 布尔值为假的合法 callable 不应被默认 validator 替换 |
| value-chain-typeerror | [7847d432](https://github.com/more-itertools/more-itertools/commit/7847d4324a581da8d0919734a8e50b2a6573b780) | 迭代器内部 TypeError 应传播，标量继续兼容 |
| split-empty-maxsplit | [ce676d24](https://github.com/more-itertools/more-itertools/commit/ce676d24136e6efa932df8a4f3bf4801b89e1dd0) | 三个 split 函数在 maxsplit=0 时的空输入行为 |

源码按对应父提交归档，保留 Python 包、原有 Python 测试、README、许可证与必要项目配置。这里不是完整上游仓库镜像。`reference.patch` 仅包含修复提交中的生产代码差异；独立测试由 RepoFix 根据公开问题重建，不是直接运行上游整个测试补丁。模型运行只获得代码副本和问题描述，无法从容器访问参考补丁或独立测试。

```bash
python3 -m repofix batch --manifest benchmarks/real/manifest.json --mode reference
python3 -m repofix batch --manifest benchmarks/real/manifest.json --mode model --task-budget 2 --total-budget 100
```

这些是公开的历史任务，并非 SWE-bench 或严格保密的留出集。三个任务都来自同一个库，样本很小；模型可能见过上游代码和修复。因此将来即使通过，也只能报告这三个固定历史回归任务上的结果，不能外推为通用仓库修复成功率。目前只验证了原始失败和参考补丁通过，没有真实模型结果。
