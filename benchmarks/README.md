# 开发任务集与实验协议

`dev/manifest.json` 包含五个**人工构造**的 Python 开发任务：平均值、分页偏移、缓存失效边界、十进制金额、跨文件路由匹配。它们用于调试系统和验证评测流程，不代表真实 GitHub Issue 的难度，不能把参考补丁通过率写成 Agent 成功率。

每项任务分为 `repo/`、`issue.md`、`verification/`、`reference.patch`。模型只获得 repo 副本和 Issue 内容；独立测试与参考补丁不挂载到 Agent 容器。参考补丁仅供检查题目本身是否成立。

```bash
# 不调用模型：逐项确认原版本确实失败
python3 -m repofix batch --mode preflight
# 不调用模型：逐项验证参考补丁可以通过相同独立测试
python3 -m repofix batch --mode reference
# 配置 Key 和价格后才可使用：真实模型任务，所有任务共用 runs/budget.sqlite
python3 -m repofix batch --mode model --task-budget 2 --total-budget 100
# 可以选择单个/多个任务
python3 -m repofix batch --mode model --task pagination-offset
```

`runs/batch-*/summary.json` 保存逐任务结果与汇总，任务完成后立即落盘。`mode`、`provenance` 和 `split` 必须随结果一起报告。失败任务始终留在分母中；参考补丁验证没有 `model_success_rate`。模型模式的成功率是这组人工开发任务上的系统通过率，预检/配置/预算失败也算失败，报告时必须区分实际发起模型请求的任务与配置失败。当前尚未运行真实模型实验。

后续引入真实仓库任务时，记录来源、许可证、提交版本、环境镜像和独立验证方法；与开发集分开，固定模型、预算和工具策略再比较。不得根据评测集的参考补丁修改 Agent。

另有 [real/manifest.json](real/manifest.json) 三个公开历史回归任务，来源、版本和局限见 [real/README.md](real/README.md)。它们与人工开发集分开，尚未得到真实模型运行结果。
