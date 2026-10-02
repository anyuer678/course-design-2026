# 11 测试与验证工程（B20）

前面几轮我一直在加"检查"：文档↔模型一致性、契约新鲜度、依赖图实测、跨语言对拍。
这一轮问的是另一个问题——**这些检查自己会不会失效，失效了谁会响？**

答不出来就等于没做。B18 那次 `BUILD SUCCESS` 但一个测试都没跑、B19 那次 XXE 加固
其实没生效，都是"检查在，牙齿没了"。所以本轮四件产物全围绕这件事。

## 1. 四件产物：命令、实测读数、能被什么弄红

| 产物 | 命令 | 本轮实测读数 | 什么改动会让它红 |
|---|---|---|---|
| 序列收缩器 | `python tools/shrink.py` | 7 个状态，ddmin 与 BFS 最短**全等**，且每个见证单步不可删 | 见证比暴力最短长，或见证里有一步可以删掉 |
| 后果测量 | `python tools/consequences.py` | AQ-10 循环 6 步、时限全程冻结、痕迹 6→12→21；AQ-11 4 档 × 3 配比 = 12 格 | 测量对它声称度量的东西失去响应 |
| 变异自检台 | `python tools/mutation_check.py` | **12/12** 条变异把对应核对器弄红；阴性对照 1 条保持绿 | 任何一条变异没能把核对器弄红 |
| 分层流水线 | `python tools/pipeline.py` | 9 层、41.94 s 全绿（见下） | 任一层的命令退非 0，**或退出码 0 却读不到数** |

收缩表里的长度是实测，不是推算：

```
状态        种子长  ddmin  BFS最短  单步不可删  达到最优
DRAFT             3      0       0       True      True
SUBMITTED         4      1       1       True      True
ASSIGNED          5      2       2       True      True
IN_PROGRESS       3      3       3       True      True
RESOLVED          7      4       4       True      True
CLOSED            8      5       5       True      True
CANCELLED         5      1       1       True      True
```

`DRAFT` 的 ddmin=0 是实测出来的：草稿态**空序列就满足**谓词，所以最短见证是 0 步。
第一版收缩器停在长度 1 就宣布"已最小"，把这个事实盖住了——现在 `ddmin` 与 BFS
都会先单独试一次空序列。

## 2. 分层流水线：一条命令，九层，不 fail-fast

`run.bat pipeline` 或直接 `python tools/pipeline.py`。

> **B21 起流水线是 10 层**（新增 `qa`：门禁口径与走查对齐）。下面这张表是 **B20 收尾那次实测**（9 层、41.94 s），保留作历史基线；最新的每层耗时见 `docs/12-qa.md` 第 6 节。

2026-10-01 实测：

| 层 | 命令 | 读数 | 耗时 |
|---|---|---|---|
| docs | `checks/check_docs.py` | FR 15 / BR 11 / NFR 7 / IF 4 / UC 6 / US 13 / AC 40 / 转换 15 / 待决 12 | 0.12 s |
| contract | `tools/export_contract.py --check` | schema_version 2、转换 15、角色 12、前置条件 8 | 0.13 s |
| verdict | `tools/export_verdict_table.py --check` | 1680 格 | 0.10 s |
| arch | `checks/check_arch.py` | 8 个组件、20 条真实依赖边 | 0.46 s |
| pytests | `python -m unittest discover -s tests` | 155 个测试、跳过 0 | 10.53 s |
| javatests | `tools/java_build.py --require` | 37 个测试、失败 0、错误 0 | 23.53 s |
| shrink | `tools/shrink.py --json` | 7 状态全部达到暴力最短 | 0.16 s |
| consequences | `tools/consequences.py --json` | 循环 6 步、4 档 12 格 | 0.11 s |
| mutation | `tools/mutation_check.py` | 12 条变异全部变红 | 6.80 s |

三个设计决定，都不是顺手写的：

* **不 fail-fast**。第一层红就退出，这轮就拿不到其余八层的状况；全跑完再汇总。
* **读数失败＝红**。`--require` 让"本机没 Maven"算**失败**而不是"跳过且绿"；
  退出码 0 但输出里解析不到数字，同样判红。实测过：把 `check_docs.py` 的计数行改个写法，
  这层就报"退出码 0 但读不到数：文档计数行没匹配上"。
* **每层写清"什么改动会让它红"**。写不出这句话的层就是在烧时间——报告里直接把这句话
  打出来，逼着它一直可回答。

耗时是同一次跑出来的，别处的数字过期了别看：整套 9 层 **41.94 s**，
最慢的两层是 javatests 23.53 s 与 pytests 10.53 s，其余七层加起来不到 1.2 s。
全程本地离线，没有安装或下载任何东西。

## 3. 变异登记表（12 条 + 1 条阴性对照）

`python tools/mutation_check.py --list` 是当前登记表的权威来源，这里只按"它在防哪类事故"归类：

| 类别 | 变异 id | 期望变红的核对器 |
|---|---|---|
| 文档与模型的数不一致 | `sla-hours-model`、`grace-model-only`、`field-limits-doc`、`visibility-doc-only` | `checks/check_docs.py` |
| 生成物过期 | `stale-contract`、`stale-verdict-table`、`matrix-stale` | `check_arch` / `export_verdict_table --check` / `check_docs` |
| Java 侧写了第二份规则 | `java-second-rule`、`java-layer-violation`、`adr-section-dropped` | `checks/check_arch.py` |
| 工具链假绿 | `java-build-zero-tests` | `tools/java_build.py` 的解析器 |
| 收缩器被削弱 | `shrink-alphabet-cut` | `tests/test_shrink.py` |

阴性对照不是"另一条变异"：它在任何改动之前把四个核对器在未变异副本上跑一遍，
要求**全绿**。对照要的是不变红，所以最后那行统计写成"12 条变异弄红 + 1 条对照通过"，
而不是笼统的 13/13——第一版写成 13/13 就把这件事说混了。

## 4. 本轮我自己骗自己的三次，以及修法

这部分比产物更值得记，因为骗我的不是被测代码，是我的验证工具。

1. **共用一份副本，变异"在盘上但不在行为里"**。所有变异挤在同一份临时副本里、跑完还原；
   `stale-contract` 单独跑变红、连跑就绿。机制：核对器 `import spec.workorder` 把 `.pyc` 写进了
   **副本**，而 CPython 判缓存有效只看 pyc 头部那两个字段——源码 mtime 的**整数秒**与源码**字节数**，
   **不比源码内容**。`copytree` 保留 mtime、还原后字节数复原、两次写又落在同一整秒，三个条件一起成立。
   本机实测：pyc 头部 mtime 字段是 `int(st_mtime)`；把源码换成同长度的另一份内容再把 mtime 复原，
   `import` 读到的仍是旧值。
   修法：每个变异独享一份副本（947 KB，代价可忽略）+ 子进程 `PYTHONDONTWRITEBYTECODE=1`。
   常驻测试：`tests/test_mutation_check.py` 的"每条变异各一份副本""副本里不许出现字节码缓存"。
2. **我的探针脚本没直读退出码**。它一边打出 pytest 的 `1 failed`，一边把结论判成"没红"。
   这是 B19 那条"读退出码必须直连被检进程"的老坑换了个地方——这次在我自己的验证脚本里。
   修法：探针一律打印原始 `returncode`，结论从它推出来，不从输出文字猜。
3. **把"删掉断言"当成反向验证**。第一条探针是去测试文件里把断言替换成 `assertEqual(1, 1)`，
   那当然绿，什么也没证明。有效探针是**改坏数据或被测代码**（把登记表里的锚点改过时、
   把核对器路径写错、把隔离改回共用副本），看对应测试是否变红。
4. 另外 `matrix-stale` 第一版选错了变异：加一条占位 AC 确实让 `check_docs` 红了，
   但红的原因是"AC 没有测试引用"，不是"矩阵过期"——**红要红在预期的那个原因上**，
   否则等于没测到这条。改成只违反矩阵新鲜度的一处改动。

本轮一共跑了 **14 条反向探针**，逐条实测都能把对应的东西弄红：

| 探针（改坏哪里） | 变红的对象 |
|---|---|
| 变异改成共用一份副本 | `test_each_mutation_runs_in_its_own_copy` |
| 去掉 `PYTHONDONTWRITEBYTECODE` | `test_child_checkers_leave_no_bytecode_in_the_copy` |
| 副本里预置旧字节码（copytree 不忽略 `__pycache__`） | 同上 |
| 取消锚点命中数校验 | `test_stale_anchor_raises_instead_of_silently_skipping` |
| 登记表里的锚点过时 | `test_every_anchor_still_hits_the_current_tree_exactly_once` |
| 登记一个不存在的核对器 | `test_registered_checkers_are_real_scripts` |
| 去掉"未知 id"守卫 | `test_unknown_id_is_a_failure_not_an_empty_green` |
| 废掉 ddmin 的空序列检查 | `test_empty_sequence_is_tried_before_any_deletion`（老的"全等"断言也红，"长度表"绿） |
| 废掉 BFS 的深度 0 | 三条全红 |
| 两条同时废掉 | 三条全红 |
| 改坏 `spec`（宽限期 168→24） | 流水线 docs 层 + arch 层红、整体退出码 1 |
| 把 `check_docs` 的计数行改写法 | 流水线 docs 层报"退出码 0 但读不到数" |
| 把 Maven 藏起来（空 HOME） | 流水线 javatests 层红（`--require` 生效） |
| `--only <拼错的层>` | 流水线退出码 1 并列出可选层 |

最后一类是"空绿"守卫：选到 0 层 / 0 条变异时必须算失败，不能报"0 条失败"。

## 5. 这一层不覆盖什么

* 浏览器里的人工走查（`docs/07-walkthrough.md` 的 20 步）——只有你眼睛能验，我不会替你勾。
* 变异登记表是**纯文本锚点**：重构改动那几行文本，锚点命中数就变，自检台会拒绝跑并报错。
  这是有意的硬失败，但也意味着它需要随重构维护。
* AQ-11 的参数（到达间隔、工时、配比）是我拟的假设，不是调研数据；
  所以它给的是"在这些假设下会这样"，不是"实际会发生"。AQ-10 的循环长度则不同，
  它是模型性质的闭式测量。
* 收缩器的字母表只到 36 步动作，BFS 上限深度 6；更长的反例序列不在它的覆盖内。
* 流水线不并发、不带缓存、没有分诊；每次 40 s 全跑。

## 6. 复现

```
python tools/pipeline.py                    # 9 层全跑（约 40 秒）
python tools/pipeline.py --only docs        # 单层
python tools/pipeline.py --list             # 层清单
python tools/mutation_check.py --verbose    # 逐条变异：diff、副本指纹、核对器完整输出
python -m pytest tests/test_shrink.py tests/test_consequences.py \
    tests/test_mutation_check.py tests/test_pipeline.py -q
```

`--verbose` 会把每条变异施加的 unified diff、副本文件的前后指纹、核对器的完整输出打出来。
临时目录退出即删，要手工进副本复现就用 `--only <id> --verbose`。
