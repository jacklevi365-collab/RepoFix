# 本地任务服务

安装并运行（macOS / Linux）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/web.lock
PYTHONPATH=src .venv/bin/python -m repofix serve
```

可选使用 `pip install -e ".[web,test]"` 安装兼容范围依赖。锁文件保存开发时实际验证的依赖版本。服务默认只监听 `127.0.0.1:8765`，首页为修复工作台，API 文档位于 `/docs`。只支持一个进程和一个后台执行线程；同一输出目录通过进程锁防止重复服务误恢复活跃任务。

## 接口

| 方法与路径 | 行为 |
|---|---|
| GET `/api/health` | 服务状态与固定 100 元总预算 |
| GET `/api/catalog` | 允许提交的开发任务 |
| POST `/api/jobs` | 异步提交，返回 202 和任务 ID |
| GET `/api/jobs` | 最近 50 个任务 |
| GET `/api/jobs/{id}` | 当前状态与最终报告 |
| DELETE `/api/jobs/{id}` | 取消尚未开始的任务 |
| GET `/api/jobs/{id}/events` | SSE，支持 `Last-Event-ID` 或 `after` 断线续读 |
| GET `/api/jobs/{id}/artifacts/{name}` | 下载白名单内的补丁、报告、轨迹 |

```bash
curl -X POST http://127.0.0.1:8765/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-demo-001' \
  -d '{"task_id":"demo-tinybug","mode":"demo","context_mode":"compact"}'
```

`mode=demo` 仅支持 `demo-tinybug`，执行固定脚本，零模型请求。`mode=model` 才调用 DeepSeek，需要本机配置 Key 和价格。API 不接受任意仓库路径、shell 命令或密钥输入；只运行服务端允许的任务。单任务预算最大 5 元，所有真实任务与 CLI 使用同一 `runs/budget.sqlite` 总账本。

`Idempotency-Key` 相同且请求相同时复用原任务，避免重复提交带来重复调用；相同键不同请求返回 409。工作台在请求因网络异常未确认是否接受时，会保留并复用原键；明确接收后主动再次提交才生成新键。最多同时排队/执行 20 个任务。浏览器跨来源请求和未知 Host 会被拒绝。本服务没有互联网多用户认证，不应直接暴露公网。

SQLite 保存状态及事件。服务重启将未完成任务标记为 `interrupted`，不自动重复付费请求或未知执行状态的命令。队列不会自动恢复，但可以通过 CLI `resume --run-dir ...` 继续安全的完整轮次检查点；在途指令未知时仍拒绝自动重放。运行中的任务不能通过取消接口强制停止；正常关闭会等待当前工作结束。
