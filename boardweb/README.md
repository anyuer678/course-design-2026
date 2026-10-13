# boardweb —— 画板 Web 版（P7 的网页形态，2026-10-07 起交付）

![BoardWeb 截图](../screenshots/boardweb.png)

**这个产品解决什么**：不装桌面软件也能画——浏览器里画笔/图形/选择微调、
贴图粘贴、撤销重做，自动保存 + 轮转备份，与桌面 Swing 版并存。
**协同白板（2026-10-11）**：开多个窗口即互见笔画——`/ws/board` 广播枢纽
（复用轮十八手写 RFC 6455），增量 add/clear + 结构性变更全量 sync，服务端
不回显发送方，徽标实时显示在线人数；断线 3s 重连退回本地模式。协同与持久化
的边界：实时层只管互见，落盘仍是各端自动保存（last-save-wins + version 单调），
不引入 OT/CRDT——课设口径的如实简化。双页面无头走查证据：
`p-验收/ws-BoardWeb协同-2026-10-11/`。

**Docker**（仓库根为构建上下文）：

```bash
docker build -f boardweb/Dockerfile -t kcsuite-boardweb .
docker run -p 8025:8025 kcsuite-boardweb
# 或一键全家桶：docker compose up -d --build
```

**定位**：浏览器里的画板，内嵌 Studio 门户（第九个 managed 产品）——回应
"画板要内嵌网页、要图形工具、要微调、要贴图"。桌面 Swing 版（`board/`，:8023）
保留并存，两者备份纪律同源（原子写 + 轮转留底）。

## 运行

```
run.bat                       # 双入口测试（8 项：文档/备份轮转/贴图/安全）
python server.py --port 8025  # 启动画板服务（Studio 门户可一键启停）
```

## 功能（对应四项诉求）

| 诉求 | 落地 |
|---|---|
| 各种图案 | 画笔 / 直线 / **箭头** / 矩形 / 椭圆 / **三角 / 菱形** 五种描边工具 + **文字**（点击落字、双击改）+ **便利贴**（黄底圆角、自动折行、双击改）+ 颜色与线宽（文字形状即字号） |
| 内嵌网页 | HTML5 Canvas 网页版，门户一键启停、浏览器直开 :8025 |
| 微调 | 选择工具点选对象 → 拖动移动 / 方向键微调 1px（Shift 10px）/ 属性面板 X/Y/W/H/颜色/线宽数字微调 / Delete 删除 / Ctrl+Z·Y 撤销重做 |
| 贴图 | 文件上传（png/jpg/gif/webp ≤8MiB）+ **Ctrl+V 直接粘贴截图**，插入后可拖动缩放 |

持久化：改动 1 秒防抖自动保存 `data/doc.json`（原子写），每次保存轮转留底
`data/backups/`（keep=10）；贴图落 `data/img/`。导出 PNG 一键下载。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/doc | 读文档 {version, shapes} |
| PUT | /api/doc | 保存（≤4MiB，版本 +1，轮转备份） |
| GET | /api/backups | 备份清单 |
| POST | /api/img?name=x.png | 上传贴图（≤8MiB）→ {url} |
| GET | /img/<file> | 读贴图（文件名白名单防穿越） |

## 测试策略（15 项）

文档往返与版本递增、**图形库五类新形状逐字段往返**（arrow/triangle/diamond/
text/sticky）、坏体 400、备份轮转 keep=10（同秒连存不互覆——时戳掺随机）、
贴图上传取回、扩展名白名单 400、8MiB 上限 413、路径穿越 404、页面可达；
WS 协同五段链路（握手→peers→增量不回显→sync/clear→坏消息不断连）+
**新形状原样广播**、超限 sync 拒播不断连。

## 已知边界

- 贴图为整对象缩放（拖动/属性微调），不做像素级编辑；
- 协同为互见式（无 OT/CRDT 冲突合并，后写覆盖）；只绑 127.0.0.1。
