# CourseLab 部署与运维手册

平台是**单进程 + SQLite**：一台机器上 `python server.py` 就是全部后端；数据都在 `data/`。
三种典型场景：

## 场景 A：本机自用（默认）

```
双击 run.bat            # 起在 127.0.0.1:7900 并打开浏览器
python server.py        # 同上（不开浏览器）
```
- 只绑回环（`bind=127.0.0.1`）：同一台机器外的设备访问不到；
- 数据：`data/app.db`；日志打在控制台。

## 场景 B：课堂局域网（学生浏览器访问）

1. 复制 `config.example.json` 为 `config.json`，改两项：
   ```json
   { "bind": "0.0.0.0", "registration": "approval", "max_labs": 2 }
   ```
   - `bind=0.0.0.0`：局域网可访问（启动横幅会打印本机入口地址）；
   - `registration=approval`：学生自助注册后处于**待审批**，你在管理端"通过"后才可登录
     （避免名单外的人进来）；
   - `max_labs`：在线实验并发上限——课堂齐跑时别开大（2-4 稳）。
2. 启动：`python server.py`（或双击 `run.bat`）。学生访问 `http://<你的IP>:7900/`；
3. 管理员：先注册一个自己的账号，然后
   `python server.py --promote 你的用户名 admin`；
4. 绑定课程给任课教师：管理端 → 课程治理 → 选教师 → 保存（教师只能管绑定给自己的课）。

## 场景 C：开机自启（Windows 计划任务）

```
tools\install_autostart.bat check    # 先看要注册的命令（不改系统）
tools\install_autostart.bat          # 注册（若提示"拒绝访问"，请以管理员身份运行）
tools\uninstall_autostart.bat       # 卸载
```
- 任务名 `CourseLab`，登录时启动 `run.bat no-open`（不起浏览器）；
- 说明：本仓库开发机上注册被系统拒绝（非管理员）——脚本会如实报错并提示提权；
  归你在真实部署机上执行。

## 配置项（config.json，全部可选；不写就用默认）

| 键 | 默认 | 说明 |
|---|---|---|
| `bind` | `127.0.0.1` | 改 `0.0.0.0` 即对局域网/公网开放 |
| `port` | `7900` | 端口 |
| `data_dir` | `data` | 数据目录（相对 courselab/ 或绝对路径）；库= `<data_dir>/app.db` |
| `max_labs` | `2` | 在线实验并发上限 |
| `task_timeout` | `600` | 单实验超时（秒），到点整树杀 |
| `session_hours` | `12` | 登录会话时长 |
| `registration` | `open` | `open` 注册即用；`approval` 注册后待审批 |
| `public_mode` | `false` | 公网提醒开关（只在启动横幅多打一段建议） |

命令行可覆盖：`--host 0.0.0.0`、`--port 8000`、`--db D:\data\app.db`、`--config 路径`。
配置文件里出现**不认识的键会拒绝启动**（防手滑写错静默生效）。

## 备份 / 恢复 / 升级

```
python tools\backup.py                 # VACUUM INTO 到 backup/app-时间戳.db + 完整性校验
python tools\restore.py --from backup\app-XXXX.db      # 恢复（会先给现存库留 .before-restore 底）
```
- 建议：课堂场景**每天备份一次**（计划任务里追加一条即可）；
- 恢复前停服（Ctrl+C），恢复后跑一次 `python server.py --selftest` 确认；
- 升级=替换代码目录（`data/` 不动）；数据库结构升级由建表语句 `CREATE TABLE IF NOT EXISTS` 就地完成。

## 压测（部署前自检）

```
python tools\bench.py --url http://127.0.0.1:7900 --n 200 --c 8
```
本机实测（2026-10-04，正式服务器 200 请求 / 8 并发）：**458.4 req/s、p50 8.6ms、p95 32.3ms、
max 152.2ms、0 失败**（公开接口混合：目录/课程详情/健康检查）——课堂几十人规模绰绰有余。
（自检环境同时段复测为 122.6 req/s / p50 18.1ms，作为下限参考。）

## 常见问题

- **端口被占**：换 `port`；或先确认是不是已有一个实例在跑（健康检查 `/health` 返回带 `courselab` 的 JSON）。
- **学生登录提示"待审批"**：管理端 → 用户管理 → 该用户"通过"。
- **教师台没有课程**：管理端把课程绑定给该教师。
- **实验按钮报"并发上限已满"**：有实验在跑（项目页/管理端可见），等它结束或去管理端强停。
- **页面能开但接口 401**：会话过期（默认 12 小时）——重新登录。
