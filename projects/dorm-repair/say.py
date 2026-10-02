"""say.py —— 给 run.bat 打印中文提示。

为什么要有这个文件：cmd 读批处理是按**字节偏移**续读的，正文里一旦有多字节字符，
就可能从一行的中间接着读，把半句中文当命令执行——报 "not recognized"，而**退出码照旧 0**。
实测过两种形态：`chcp` 之前的中文注释会触发，长中文 `echo` 行也会（本轮 run.bat 的最后一行就被切了）。
把中文放进 Python 文件里打印，批处理只留 ASCII，就完全不赌 cmd 的多字节处理了。

用法：`python say.py <key>`，key 全是 ASCII，中文只活在这个 UTF-8 文件里。
"""
from __future__ import annotations

import sys

MESSAGES = {
    "step1": "[1/8] 环境检查",
    "step2": "[2/8] 需求文档与可执行模型的一致性检查（含追踪矩阵是否过期）",
    "step3": "[3/8] 架构核对：依赖图（实测）、契约与判定表/走查期望表是否过期、ADR 完整性、Java 分层",
    "step4": "[4/8] 核对需求模型、原型、架构与跨语言对拍的测试",
    "step5": "[5/8] 演示：追踪旅程、状态机、权限、可见性、检查器有没有牙齿、原型四态、架构指标",
    "step6": "[6/8] Java 平台层：离线构建 + 测试 + 1680 格跨语言对拍（由 tools/java_build.py 定位 Maven）",
    "step7": "[7/8] 分层流水线补跑五层：管理台账、QA 口径与走查对齐、序列收缩、后果测量、变异自检",
    "step8": "[8/8] 启动 B16 走查原型（浏览器打开后按清单逐条走）",
    "skip8": "已按 no-web 跳过启动原型。要人工走查界面就直接跑：run.bat",
    "pipeline": "分层流水线：一条命令按顺序跑完 11 层，每层报耗时、读数与『什么改动会让它红』",
    "gate": "质量门禁：读 docs/12 的口径判定放不放行（blocking 层全绿才 PASS；advisory 层红了点名但放行）",
    "ledger": "项目台账：管理文档里的数字全部现算，过期即红（docs/13 第 8 节是键一览）",
    "done1": "全部完成。本轮交付的是需求、可执行模型、走查原型、架构决策与 Java 平台层，不是可上线的系统。",
    "done2": "Java 层已实跑：计数由 mvn 自己的总计行与逐类相加**互相核对**，不一致就判失败（见 tools/java_build.py）。",
    "done4": "界面的观感、键盘与读屏的真实表现我没有验过，也不会替你勾——见 docs/07-walkthrough.md。",
    "walk": "走查清单：docs/07-walkthrough.md（20 步，每行结果留空等你填）",
    "nopython": "[!] 找不到 python，请先准备 Python 3.11 或更高（本项目只用标准库）",
}


def main(argv):
    if len(argv) < 2 or argv[1] not in MESSAGES:
        print(f"用法：python say.py <{'|'.join(sorted(MESSAGES))}>", file=sys.stderr)
        return 2
    print(MESSAGES[argv[1]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
