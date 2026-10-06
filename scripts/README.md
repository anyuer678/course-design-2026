# scripts —— 仓库级脚本统一入口

> 2026-10-05 归位：原根目录与 p-验收 的脚本全部收拢到本目录。
> 每个 .py 都有**同名 .bat 双击入口**（纯 ASCII + CRLF，`cd %~dp0..` 锚定仓库根，
> 任意位置可跑；尾部 pause 让双击者看得到输出，退出码如实传递）。
> 产品自身的 server.py / tests/ / run.bat 不在本目录——它们是产品本体，在各产品目录。

## 双击即用（.bat 入口）

| 入口 | 作用 | 引擎 |
|---|---|---|
| `check_all.bat` | 全仓体检 15 步（只读；`deep` 追加 33 项目展示页套件） | check_all.py |
| `lab.bat` | 实验台 :7788（讲解层 33 项目控制台；`no-open`/`lan`/`selftest`） | showcase/lab.py |
| `start_all.bat` | 起门户 :8017 并经门户拉起全部八产品（真子进程） | start_all.py |
| `stop_all.bat` | 经门户停全部产品 + 停门户，核对端口全关 | stop_all.py |
| `walkthrough_day1.bat` | P-验收 Day-1 预演（21 个机器故事；证据落 `p-验收/`） | walkthrough_day1.py |
| `scan_refs.bat` | 交付齐全性扫描（run.bat 引用核对 + 缺件探测） | scan_refs.py |

## 直接调 Python（脚本化场景）

```bash
python scripts/check_all.py --deep     # 体检（--deep/--selftest）
python scripts/scan_refs.py projects
python scripts/start_all.py
python scripts/stop_all.py
python scripts/walkthrough_day1.py     # 端口 8017-8024 必须空闲，否则退出 1
```

## 典型组合

- **日常开关**：`start_all.bat`（八产品在线，浏览器管理）→ 用完 `stop_all.bat`；
- **发布前**：`check_all.bat`（全绿才交付）→ `walkthrough_day1.bat`（干净环境真启停 + 故事走查）；
- **证据口径**：walkthrough 的带日期证据落 `p-验收/`，历史快照不覆盖。

## 已知边界

- `start_all.bat` 在门户已运行时直接复用（不重复拉起）；`walkthrough_day1.bat` 相反，
  要求 8017–8024 **全部空闲**（预演必须从干净状态起步），占用即退出 1；
- .bat 的 `pause` 在管道/无人值守下需喂一个换行（自动化场景请直接调 .py）；
- check_all 产品层步骤的标签若声明"（N 项"，会与 pytest 实跑 passed 数**对拍**：
  不一致即红（防加测试后忘改标签——webframe 30→31 / cachekv 15→17 均实测漂移过）。
