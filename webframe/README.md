# webframe —— 自研微框架（PRODUCTS.md 共享地基 #1）

**定位**：站在本仓库 B11 netlab 协议层之上的微框架——路由装饰器、静态文件、
Cookie 签名会话、JSON 体校验、模板片段。**零依赖**（标准库 + netlab，不引 Flask）。
netlab 管"字节进字节出"（解析/复用/硬上限/HEAD 发送），本框架管"URL 进对象出"。

## 用法（30 秒）

```python
from webframe import MicroApp, MicroServer, HttpFail, validate

app = MicroApp(session_secret=b"至少32字节")

@app.get("/api/items/<item_id>")
def get_item(ctx):
    return ctx.json({"id": ctx.params["item_id"]})

@app.post("/api/items")
def create(ctx):
    body = ctx.json_body({"name": (str, True), "qty": (int, False)})  # 缺字段/错类型/未知字段 → 400
    if body["qty"] < 0:
        raise HttpFail(400, "qty 不能为负")
    return ctx.json({"ok": True}, status=201)

app.static("/static", "./web")          # 类型白名单 + resolve 守卫
server = MicroServer(app, port=0)
```

## 能力清单（对应 PRODUCTS.md §四.1 五项）

| 能力 | 说明 | 关键语义 |
|---|---|---|
| 路由装饰器 | `@app.get/post/put/delete/route`；`<name>` 命名参数、`<name:path>` 子路径 | 405 带 Allow；404/错误 JSON |
| 静态文件 | `app.static(prefix, dir)` | 类型白名单；resolve 后必须留在根里（B31 守卫原样搬）；no-cache |
| Cookie 会话 | `ctx.session` 读写，脏检测自动回写 | HMAC-SHA256 签名 JSON、恒时比较、带过期；伪造/垃圾 token 一律当未登录 |
| JSON 体校验 | `ctx.json_body(schema)` | schema = `{字段: (类型, 必填)}`；**bool 不算 int**；未知字段默认拒；错误一次报全 |
| 模板片段 | `render(tpl, **vals)`、`esc()`、`Raw()` | `${name}` 默认转义（XSS 防线）；缺键/多余键报错 |

另有：`HttpFail(status, msg)` 处理器主动喊停；B31 三元组 `(status, headers, body)`
照收（兼容旧代码）；处理器异常 → 500 JSON 且不带走事件循环（netlab 再兜一层）。

## 明确不做（教学边界，如实声明）

- 无 ORM、无中间件栈、无信号量——产品要的是"够用且每一行都讲得出为什么"；
- 会话是签名 cookie（无服务端存储）：改密钥即全体下线，密钥不落盘则重启失效
  ——门户场景够用；要持久会话等 P0 后续轮次；
- 不做异步框架那套：单线程 select 多路复用是 netlab 的教学选择，产品量级远够。

## 测试策略（30 项，双入口）

路由/参数、404/405 语义、HEAD 映射 GET、OPTIONS 501、三元组兼容；
JSON：415/400 语法/缺字段/未知字段/**bool 冒充 int**；Cookie/会话：往返、
**伪造签名拒收**、垃圾 token 忽略；静态：类型表、404、**穿越守卫**；
模板：默认转义、Raw、缺键/多余键。真套接字四条：GET/405/静态/会话。

## 运行

```
run.bat                    # 双入口测试（30 项）
```

**首个使用方**：[studio](../studio/README.md)（P0 门户）——门户本身就跑在本框架上。
