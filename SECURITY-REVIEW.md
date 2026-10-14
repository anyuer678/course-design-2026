# 安全与隐私审查报告（2026-10-14，轮五十九）

> 范围：九产品 + 门户 + webframe/netlab 框架 + 脚本。方法：静态扫描（危险调用/SQL 拼接/
> innerHTML/凭据落盘/追踪状态）+ 定向代码审查（认证/上传/会话/路径）。

## 结论

**P0：无。P1 两项已当场修复。P2 四项记录在案（有意取舍或低风险）。整体安全姿态良好**——
零第三方依赖（无供应链面）、密码 pbkdf2 哈希、SQL 全参数化、全 DOM textContent、
上传路径与文件名元数据分离、凭据全部 gitignore。

## P1（已当场修复）

1. **CourseLab 会话 token 明文落库**（`sessions.token` 存明文 token_urlsafe）——
   库文件泄露 = 全部会话可被劫持。修复：只落 SHA-256 哈希（create/校验/登出/改密
   保留四处同步）；旧明文会话随之失效（重新登录即可）。自检 154 项 PASS。
2. **LinkBox SVG inline 预览 = 同源存储型 XSS 面**（SVG 可嵌 `<script>`，`--lan`
   演示时他人可投毒）。修复：SVG 从 inline 预览白名单移除（仍可 attachment 下载）。

## P2（记录在案，不修/暂不修）

| 项 | 说明 | 取舍理由 |
|---|---|---|
| Cookie 无 Secure 属性 | 纯 http 部署（含 --lan）下 Secure 无法生效 | 本机/局域网 http 定位使然 |
| PBKDF2 10 万迭代 | OWASP 2023 建议 60 万 | 性能取舍（演示机可感），课设可接受 |
| courselab 记录登录 ip/ua | 属个人数据 | 本机部署无第三方，数据不出机器 |
| --lan 模式无认证 | 局域网任何人可读写画板/互传 | 已在启动横幅加 ⚠ 警示"仅限可信网络演示" |

## 做得好的（审查确认）

- **零依赖**：无 requirements.txt 之外的包——无供应链投毒面
- **密码**：pbkdf2_hmac + 16B 盐；owner 口令哈希落 owner.json；password.txt 恢复口令
  登录后设密码即作废（信封语义）
- **SQL**：全参数化（5 处 f-string 均为代码内部迁移列名，非用户输入）
- **XSS**：全项目 DOM 一律 textContent（唯一 innerHTML 的值为服务端 IP）
- **上传**：linkbox 文件名仅作展示元数据（去路径/控制符/Windows 保留字），取件路径
  永远是 `<code>.bin`（40bit 密码学随机）；boardweb 贴图扩展名白名单 + 文件名白名单
- **路径**：courselab /repo 白名单 + 目录穿越用例（自检钉住）
- **权限**：studio 权限矩阵测试逐格钉住；游客权限最小化（可体验不计分）
- **凭据**：studio/data/（owner.json、password.txt、users.json）gitignore 且未追踪

## 遗留建议（不阻塞）

- `--lan` 若长期使用，考虑给 boardweb 加简单房间口令（同 linkbox 暂存口令模式）
- PBKDF2 迭代数在非演示部署时可上调至 30 万+
