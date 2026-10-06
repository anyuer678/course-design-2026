# 参考文献草稿（GB/T 7714 风格示例）

> 状态：**草稿**——条目按 GB/T 7714-2015 著录格式书写；学校若指定其他格式
> （如 APA/编号上标规则）再整体调整。**每条都应在正文中真实引用**，成文时
> 逐条核对访问日期与版本号；不凑数——正文没引到的条目删除。

## 外部文献与标准

[1] ONGARO D, OUSTERHOUT J. In search of an understandable consensus algorithm
    (Raft)[C]//Proceedings of the 2014 USENIX Annual Technical Conference
    (USENIX ATC 14). Philadelphia: USENIX Association, 2014: 305-319.
    （对应候选③ B30 Raft 完整化的算法出处）

[2] PYTHON SOFTWARE FOUNDATION. The Python standard library documentation
    [EB/OL]. (2026 访问). https://docs.python.org/3/library/.
    （http.server / sqlite3 / subprocess / selectors 等全平台底座）

[3] SQLITE CONSORTIUM. SQLite documentation [EB/OL]. (2026 访问).
    https://www.sqlite.org/docs.html. （参数绑定 / VACUUM INTO / 单文件形态）

[4] IETF. PKCS #5: Password-Based Cryptography Specification Version 2.1:
    RFC 8018 [S/OL]. (2017-01). https://www.rfc-editor.org/rfc/rfc8018.
    （PBKDF2-HMAC-SHA256 口令存储，120000 迭代口径）

[5] WHATWG. HTML Living Standard: Server-sent events [S/OL]. (2026 访问).
    https://html.spec.whatwg.org/multipage/server-sent-events.html.
    （实验日志流的 event/data 帧格式）

[6] REDIS LTD. Redis replication documentation [EB/OL]. (2026-10-06 验证可达).
    https://redis.io/docs/latest/operate/oss_and_stack/management/replication/.
    （B38 主从复制子集的语义参照——原 redis.io/docs/replication/ 因文档改版失效）

[7] SCIKIT-LEARN DEVELOPERS. scikit-learn User Guide [EB/OL]. (2026 访问).
    https://scikit-learn.org/stable/user_guide.html.
    （候选⑤ B23 的对拍参照实现——口径先写纸上、同参对照）

## 本仓库资料（按学校口径决定是否著录为"资料"或并入正文脚注）

- 课设仓库 `PLAN.md`（课程项目路线与纪律）、`PRODUCTS.md`（产品矩阵）、
  `scripts/check_all.py`（全仓体检 15 项，2026-10-06 全过）；
- `projects/B41-thesis-seeds/data/seeds.json`（5 个候选题的三维可行性，
  候选清零收官态，全部带机验锚点）；
- CourseLab `docs/PLAN.md · DESIGN.md · SECURITY.md · DEPLOY.md`
  （方案书 / 开工规格 F1-F18 / 安全边界 / 部署运维）。

## 教材补引候选（2026-10-06 预起草——版次/年份须按学校图书馆馆藏核对后定稿；学校书目清单到手后取舍）

- 王珊, 萨师煊. 数据库系统概论[M]. 5版. 北京: 高等教育出版社, 2014.
  （对应第 3 章数据库设计：关系模型/主键/参数化查询）
- 谢希仁. 计算机网络[M]. 8版. 北京: 电子工业出版社, 2021.
  （对应第 3 章接口设计与第 2 章场景：HTTP 语义/状态码/Cookie 会话）
- 张海藩, 牟永敏. 软件工程导论[M]. 6版. 北京: 清华大学出版社, 2013.
  （对应第 2 章需求分析：功能点编号/验收口径/里程碑）
- SOMMERVILLE I. Software engineering[M]. 10th ed. Boston: Pearson, 2016.
  （对应第 1/2 章：需求工程与演进式开发——英文文献候选，是否满足英文文献
  最低数量待学校口径）

## 待用户确认

- 学校要求的参考文献数量与构成（教材/论文/标准/网络资源的比例、英文文献
  最低数量）——正文各章可能需要补引教材与文献（如《计算机网络》《数据库
  系统概论》对应第 3 章内容），拿到书目清单后我来补引；
- 访问日期统一补成定稿日。
