# CourseLab 前端设计规范 v2.1（调研提炼版）

> 2026-10-05。来源：Vercel Geist 设计系统（vercel.com/geist）、Vercel Web Interface
> Guidelines（vercel-labs/web-interface-guidelines）、2025 admin dashboard 趋势调研
> （shadcn/Linear 风格：克制、低饱和强调色、深色优先、密排字体）、LMS 课程卡模式
> （角色分区视图 + 进度条 + CTA）。本文件是 CourseLab 前端的**规范性依据**——
> app.css v2.1 的每条规则都能在这里找到出处。
>
> **v2.1 决策记录（用户裁定）**：不做深浅色切换，**浅色单主题**交付。原 v2 的深色
> token 与 `data-theme` 机制已从 app.css / app.js 全部移除；深色取值保留在本文件
> 第二节作为备查，仅供将来重启多主题时引用。

## 一、设计方向：克制工程风（Geist/Linear 系）

2025 年公认最好的仪表盘界面收敛于"克制的工程美学"：
- 低饱和中性色打底，单一强调色（蓝），高对比文本
- 密排但不拥挤的排版，等宽数字用于数据对比
- 细边框（1px）+ 半透明阴影分层（模拟环境光 + 直射光）
- 克制的动效：只在"澄清因果"时动画，全部可被打断
- ~~深色优先考虑，浅色为默认态~~ → **v2.1：浅色单主题**（决策见文件头）

## 二、设计 Token（app.css v2 的 ：root 替换依据）

### 颜色（浅色）
| Token | 值 | 用途 |
|---|---|---|
| --bg | #fafafa | 页面底（Geist Paper White） |
| --card | #ffffff | 卡片/面板 |
| --ink | #171717 | 主文本 |
| --muted | #525252 | 次要文本 |
| --faint | #a3a3a3 | 弱提示 |
| --line | #e5e5e5 | 边框 |
| --line-strong | #d4d4d4 | 悬停边框 |
| --accent | #2563eb | 强调/主按钮 |
| --accent-hover | #1d4ed8 | 按钮悬停 |
| --accent-soft | #eff6ff | 强调浅底 |

### 颜色（深色——v2.1 未采用，备查）
| Token | 值 |
|---|---|
| --bg | #0a0a0a |
| --card | #141414 |
| --ink | #ededed |
| --muted | #a1a1aa |
| --faint | #71717a |
| --line | #262626 |
| --line-strong | #404040 |
| --accent | #3b82f6 |
| --accent-hover | #60a5fa |
| --accent-soft | #172554 |

### 语义色（浅色版即唯一版本）
ok #16a34a / warn #d97706 / err #dc2626。

### 排版
- 字体栈：system-ui → "Segoe UI" → "PingFang SC" → "Microsoft YaHei"
- 字号阶：12.5（辅助）/ 13.5（次要）/ 15（正文）/ 17（页面标题）/ 22（大标题）
- 行高：正文 1.65，代码/数据 1.5
- **tabular-nums 用于所有数字对比场景**（表格计数、成绩、统计卡）
- 页面标题 font-weight 600，letter-spacing -0.01em

### 间距与圆角
- 间距 8px 基准：4/8/12/16/24/32
- 圆角：卡片 10px、按钮 8px、输入 8px、胶囊 999px
- **嵌套圆角**：子元素圆角 = 父圆角 − 内边距（Geist 规则）

### 阴影（两层：环境 + 直射）
- 卡片静止：`0 1px 2px rgb(0 0 0/.04), 0 0 0 1px rgb(0 0 0/.03)`
- 卡片悬停：`0 4px 8px rgb(0 0 0/.06), 0 0 0 1px rgb(0 0 0/.04)`

## 三、组件规则（Vercel Guidelines 对应实现）

### 表单
- Enter 提交（唯一控件聚焦时）；⌘/Ctrl+Enter 在 textarea 中提交
- 提交开始才禁用按钮 + spinner **保留原文案**
- **不要预禁用提交按钮**——让校验错误自己浮出来
- 错误显示在字段旁边；提交时聚焦第一个错误字段
- autocomplete/name/inputtype 全部正确设置；邮箱/代码关 spellcheck
- placeholder 用"…"结尾表示占位；永不禁用粘贴
- select 显式设置 background-color/color（不依赖系统表单控件继承）

### 加载与反馈
- spinner 延迟 150–300ms 出现、至少停留 300–500ms（防闪烁）
- 骨架屏**精确镜像最终布局**（防布局偏移）
- 破坏性操作确认或提供 Undo
- 设计空态/稀疏态/密集态/错误态四种
- 状态持久化到 URL（可分享、刷新安全、前进后退可用）

### 交互细节
- 命中目标 ≥24px，移动端 ≥44px
- 移动端输入字号 ≥16px（防 iOS 自动放大）
- `touch-action: manipulation` 防双击缩放
- 导航必须用真 `<a>`（Cmd/Ctrl+点击、中键必须可用）
- 模态/抽屉 `overscroll-behavior: contain`
- 没有死区：看起来可点的东西必须可点

### 动效
- 只动画 `transform` 和 `opacity`；永不 `transition: all`
- 尊重 `prefers-reduced-motion`
- 动画可被用户输入打断

### 排版与内容
- 优先行内帮助而非 tooltip
- 没有死胡同：每个页面都有下一步或恢复路径
- 用 `…` 字符而非三个句点
- 数字对比用 `font-variant-numeric: tabular-nums`
- 单位与快捷键用不换行空格（`10&nbsp;MB`）
- 标题设 `scroll-margin-top`（锚点跳转不贴顶）
- 处理短/中/超长三种用户生成内容
- 错误文案积极且给出修复路径（"在账号设置中生成新密钥"）

### 颜色
- 状态提示不依赖颜色单独表达——加文字标签
- 嵌套圆角对齐（子 ≤ 父，同心）
- 悬停/激活/聚焦态对比度高于静止态
- `<meta name="viewport">` 与 `<meta name="theme-color" content="#fafafa">` 全部页面必备
  （v2.1 落地：10 页补齐——没有 viewport，移动端响应式形同虚设）

## 四、LMS 页面模式（课程平台特有）

- **角色分区视图**：学生（进度/下一课/课程卡）与教师（班级管理/批阅/统计）分开
- **课程卡**：封面/进度条/教师/下一步/CTA（"继续学习"）
- **KPI 统计条**、任务时间线、通知面板
- 批阅工作流：提交列表 → 内联评分 → 评语 → 已批标记

## 五、对照 CourseLab 现状的差距清单（v2 实施范围）

| # | 差距 | 规范出处 | 状态 |
|---|---|---|---|
| 1 | 无 tabular-nums（统计/表格数字不对齐） | 排版 | ✅ v2 |
| 2 | 单层阴影、无描边分层 | 颜色·阴影 | ✅ v2 |
| 3 | index 统计数字重复 | 内容·数字 | ✅ v2 |
| 4 | 加载只有文字无骨架屏镜像 | 加载状态 | ✅ v2 |
| 5 | 登录按钮提交中不禁用 | 表单 | ✅ v2 |
| 6 | 无空态（纯文字） | 加载·空态 | ✅ v2.1（.empty + 清除筛选入口） |
| 7 | `.chip` 缺 aria-pressed | 无障碍 | ✅ v2.1（index/tasks） |
| 8 | 页面标题无 scroll-margin-top | 排版 | ✅ v2 |
| 9 | 深色模式阴影/边框对比不足 | 颜色 | ⛔ 决策不做深色（v2.1） |
| 10 | 表格数字未对齐、无悬停行高亮 | 排版·表格 | ✅ v2 |

## 五·补、v2.1 细节落地清单（本轮）

| 项 | 实现 |
|---|---|
| viewport + theme-color | 10 个页面全部补齐（此前缺 viewport，移动端响应式不生效） |
| `touch-action: manipulation` | 全局交互元素，消除移动端双击缩放延迟 |
| 按钮在途状态 | `aria-busy` + 省略号动画，配 app.js `CL.busy` |
| 键盘跳转正文 | `.skip` 链接（聚焦可见）+ app.js 自动给 main 补 id |
| select / placeholder 显式样式 | 不依赖系统控件默认色 |
| 空态 `.empty` | 虚线边界 + 指引 + 恢复动作（"清除筛选"） |
| 表格数字列 `td.num/th.num` | 右对齐 + tabular-nums |
| 深色机制移除 | app.css 三个 `data-theme` 块、app.js 主题函数与顶栏按钮全删 |

## 六、参考来源

- Geist 设计系统：vercel.com/geist（颜色/文本/概念）
- Vercel Web Interface Guidelines：github.com/vercel-labs/web-interface-guidelines
- 2025 dashboard 趋势：shadcn/ui + Tailwind + Linear/Vercel 风格收敛
  （调研记录见会话，2026-10-05）
