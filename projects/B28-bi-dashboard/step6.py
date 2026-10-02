"""step6.py —— `run.bat` 第 6 步的分流，由 Python 而不是 cmd 做判断。

为什么不让 cmd 判断：实测在这台机器上，含**多行括号块**（
`if /i "%~1"=="no-server" ( ... 四行 ... )`）的 .bat 每次执行都会先打印
`The process cannot access the file because it is being used by another process.`
——cmd 按字节偏移回读脚本去继续解析这个块，而它已经不在它以为的位置。
退出码照旧 0，正文照旧跑完，所以这条错误特别容易被当成"无关的噪声"漏掉。
PLAN §6 的规矩正是为此：脚本尾段不用分支跳转，中文提示交给 Python 文件。

两个分支：
    no-server  打印人工走查清单（`say.py` 的内容），不启动服务
    默认       打印清单，然后真起 127.0.0.1 上的服务，Ctrl+C 结束
"""
from __future__ import annotations

import sys

from bi import server
import say


def main(argv: list[str]) -> int:
    args = [a.lower() for a in argv]
    say.main()
    if "no-server" in args:
        print("\n[6/6] 已按 no-server 跳过启动服务。要在浏览器里走查，直接跑：run.bat")
        return 0
    port_arg = [a for a in argv if a.startswith("--port=")]
    port = int(port_arg[0].split("=", 1)[1]) if port_arg else 8010
    print(f"\n[6/6] 启动服务：http://127.0.0.1:{port}/  （只绑回环，Ctrl+C 结束）")
    return server.main(["--port", str(port)])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
