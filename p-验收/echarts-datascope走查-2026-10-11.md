# 轮十五走查：DataScope 报告 ECharts 化（2026-10-11）

## 改动

- `datascope/server.py`：新增 `POST /api/report_data`（JSON 报告数据，与 SVG 同源）；
  `/api/report` 与新端点的 `mining` 校验放宽为 `(dict, type(None))`——修掉
  "不跑挖掘直接点报告就 400" 的潜伏 bug。
- `datascope/web/index.html`：报告区改三图容器（chart-steps / chart-profile /
  chart-mining），引入 `assets/echarts.min.js`；按钮改「生成报告」+「下载 SVG 版」。
- `datascope/web/app.js`：报告渲染重写——清洗行数变化（柱顶数值）、画像缺失去重
  双序列、Apriori 三系列 / K-means 簇大小；SVG 下载改按需 POST 重取。
- `datascope/tests/test_datascope.py`：新增 TestReportDataApi（形状 / 含挖掘 / 坏配方 400）。
- `datascope/server.py` SAMPLE_CSV：补一行精确重复（原样本号称"含重复"实则无），
  drop_duplicates 演示从 23→23 平线变为 24→23。

## 验证

- pytest：datascope 37 + sensorhub 25 + cachekv 19 = **81 全绿**
- 无头 Edge（playwright-core + msedge）全链自动走查：加载示例 → 组配方（去重/去空格/
  填充金额）→ 清洗（24→23）→ 生成报告
- 三 canvas 真渲染（929×240/240/280），**零 console 错误**
- 截图目检：echarts-datascope.png（全页）、echarts-datascope-steps.png、
  echarts-datascope-mining.png

## 截图清单

| 文件 | 内容 |
|---|---|
| echarts-datascope.png | 全页终态（四步工作流 + 三图） |
| echarts-datascope-steps.png | 清洗行数变化特写（24→23 台阶） |
| echarts-datascope-mining.png | Apriori 规则三系列特写 |

## 遗留

- 走查脚本 `scripts/walk_datascope.js` 可复用（下次报告改动直接重跑）。
- SVG 下载链路已由 TestReportDataApi + 既有 test_mining SVG 用例覆盖，浏览器内未重复点下载。
