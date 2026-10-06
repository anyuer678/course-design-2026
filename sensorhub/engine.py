"""sensorhub/engine.py —— 编排层：把 B35 四件真件串成一条生产线 + 产品侧告警台账

零件库纪律（零重写，全部直接 import B35 mqttlite 的真实实现）：
    broker = mqttlite.broker.Broker            selectors 单线程事件循环，真套接字
    设备   = mqttlite.sensors.SensorSimulator  随机游走 + spike/freeze/dropout（带账本）
    入库   = mqttlite.recorder.Recorder        订阅 sensors/+/data → SQLite（幂等主键 + 对账口）
    曲线   = mqttlite.svgplot.line_chart       服务层现算自包含 SVG（见 server.py）
产品侧只补两件 B35 没有的：
    1) 阈值告警：对入库读数逐行评估 temp_max / vib_max，落 alerts 表——
       主键 (device, seq, rule) 幂等（重复评估不重复计数，重启后台账仍在），
       与 readings 可双向对账：每条告警必对应一条越限读数；
    2) 编排与观察面：节拍、inject 管理口注入（走 broker.route 的真实订阅表）、
       status 总账（设备账本 vs 入库实收，B35 的对账口径）。

线程模型（如实声明）：
    服务模式（interval 给秒数）：mqttlite 的 socket 与 sqlite 连接全部在 hub 线程里
    建立并只被它使用；外部调用（HTTP 处理器）经 _call 排队到 hub 线程执行。
    手动模式（interval=None）：不设线程，一切在调用线程就地执行（单线程使用约定，
    供测试与脚本确定性驱动）。
"""
from __future__ import annotations

import json
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path

from mqttlite.broker import Broker
from mqttlite.client import Client
from mqttlite.recorder import Recorder
from mqttlite.sensors import ReadingPlan, SensorSimulator

DEFAULT_DEVICES = ("dev-01", "dev-02", "dev-03")
METRICS = ("temp", "vib")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ALERTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    device    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    rule      TEXT NOT NULL,
    metric    TEXT NOT NULL,
    value     REAL NOT NULL,
    threshold REAL NOT NULL,
    raised_at REAL NOT NULL,
    PRIMARY KEY (device, seq, rule)
);
"""


class SensorHub:
    """传感器 → MQTT → SQLite → 告警：B35 真件编排，产品侧只补告警与账面。"""

    def __init__(self, db_path, *, devices=DEFAULT_DEVICES, seed=2026,
                 base_temp: float = 70.0, drift: float = 1.5,
                 plan: ReadingPlan | None = None,
                 interval: float | None = 1.0,
                 temp_max: float = 85.0, vib_max: float = 4.0,
                 topic_prefix: str = "sensors"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.devices = tuple(devices)
        if not self.devices:
            raise ValueError("至少要有一台设备")
        for dev in self.devices:
            if not _DEVICE_RE.match(dev):
                raise ValueError(f"设备名只允许字母/数字/下划线/短横线：{dev!r}")
        self.seed = int(seed)
        self.base_temp = float(base_temp)
        self.drift = float(drift)
        self.plan = plan
        self.interval = None if interval is None else float(interval)
        if self.interval is not None and self.interval <= 0:
            raise ValueError("interval 要是正秒数；手动模式请传 None")
        self.topic_prefix = topic_prefix
        # 规则表：规则名 → (指标, 阈值)；判定口径是严格大于（正好压线不算告警）
        self.rules = {"temp_max": ("temp", float(temp_max)),
                      "vib_max": ("vib", float(vib_max))}
        # ---- 运行态（start 之后才有内容；连接全部在 _setup 里建）
        self.broker: Broker | None = None
        self.recorder: Recorder | None = None
        self.rec_client: Client | None = None
        self.sims: dict[str, SensorSimulator] = {}
        self.sim_clients: dict[str, Client] = {}
        self._alert_conn: sqlite3.Connection | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._setup_error: BaseException | None = None
        self.ticks = 0
        self.tick_errors = 0
        self.started_at: float | None = None

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> None:
        """建件并开跑。服务模式起 hub 线程（等它建完件才返回）；手动模式就地建。"""
        if self.broker is not None or self._thread is not None:
            return                                 # 幂等：重复 start 不起第二套
        self._stop.clear()
        self._setup_error = None
        self._ready.clear()
        if self.interval is None:                  # 手动模式：调用线程自担
            self._setup()
            self._raise_setup_error()
            return
        self._thread = threading.Thread(target=self._main, name="sensorhub-hub",
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            raise TimeoutError("hub 线程 10s 未完成建件")
        self._raise_setup_error()

    def stop(self) -> None:
        """收摊（幂等；从未 start 过就是空操作）。服务模式等 hub 线程自己拆完。"""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            self._thread = None
        elif self.broker is not None:
            self._teardown()

    def _raise_setup_error(self) -> None:
        if self._setup_error is not None:
            err, self._setup_error = self._setup_error, None
            raise err

    def _setup(self) -> None:
        """建全部真件：broker → 告警库 → 入库端（真套接字订阅）→ 每设备一个真客户端。
        只在 hub 线程（服务模式）或 start 调用线程（手动模式）里执行一次。"""
        self.broker = Broker("127.0.0.1", 0).start()
        try:
            self._alert_conn = sqlite3.connect(str(self.db_path))
            self._alert_conn.execute("PRAGMA busy_timeout=3000")
            self._alert_conn.execute(ALERTS_SCHEMA)
            self._alert_conn.commit()
            self.rec_client = Client("sensorhub-recorder", port=self.broker.port)
            self.rec_client.connect()
            self.recorder = Recorder(self.db_path, self.rec_client,
                                     f"{self.topic_prefix}/+/data")
            for i, dev in enumerate(self.devices):
                sim = SensorSimulator(dev, seed=self.seed + i,
                                      base_temp=self.base_temp, drift=self.drift,
                                      plan=self.plan)
                client = Client(f"sensorhub-sim-{dev}", port=self.broker.port)
                client.connect()
                self.sims[dev] = sim
                self.sim_clients[dev] = client
            self.started_at = time.time()
        except BaseException as err:               # 建件失败：拆干净再上报，不留半套
            self._setup_error = err
            self._teardown()

    def _teardown(self) -> None:
        for client in self.sim_clients.values():
            client.disconnect()
        self.sim_clients.clear()
        self.sims.clear()
        if self.rec_client is not None:
            self.rec_client.disconnect()
            self.rec_client = None
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
        if self._alert_conn is not None:
            try:
                self._alert_conn.commit()
                self._alert_conn.close()
            except sqlite3.Error:
                pass
            self._alert_conn = None
        if self.broker is not None:
            self.broker.stop()
            self.broker = None
        self.started_at = None
        self.ticks = 0

    def _main(self) -> None:                       # hub 线程主体（服务模式）
        self._setup()
        self._ready.set()
        if self._setup_error is not None:
            return
        next_tick = time.monotonic() + self.interval
        while not self._stop.wait(min(0.05, self.interval)):
            self._drain_jobs()                     # 外部调用先伺候（/api/tick 等）
            if time.monotonic() >= next_tick:
                try:
                    self._tick_once()
                except Exception:
                    self.tick_errors += 1          # 一轮失败不许带走节拍（错误如实进 status）
                next_tick += self.interval
                if next_tick < time.monotonic() - self.interval:
                    next_tick = time.monotonic() + self.interval   # 落后太多就重新对表
        self._teardown()

    # ---------------------------------------------------------------- 跨线程汇入

    def _call(self, fn):
        """手动模式就地执行；服务模式排队给 hub 线程（连接只属于它，这是唯一通道）。"""
        if self._thread is None:
            if self.broker is None:
                raise RuntimeError("先 start() 再操作 SensorHub")
            return fn()
        done = threading.Event()
        box: dict = {}
        self._jobs.put((fn, box, done))
        if not done.wait(timeout=10.0):
            raise TimeoutError("hub 线程 10s 未响应")
        if "err" in box:
            raise box["err"]
        return box.get("ret")

    def _drain_jobs(self) -> None:
        while True:
            try:
                fn, box, done = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                box["ret"] = fn()
            except BaseException as err:           # 原样递交给提交方
                box["err"] = err
            finally:
                done.set()

    # ---------------------------------------------------------------- 节拍与告警

    def tick(self) -> dict:
        """推一拍：设备各发一条读数（dropout 不发）→ 排空入库端 → 评估告警。"""
        return self._call(self._tick_once)

    def _tick_once(self) -> dict:
        sent = dropped = 0
        for dev, sim in self.sims.items():
            if sim.publish(self.sim_clients[dev], self.topic_prefix):
                sent += 1
            else:
                dropped += 1
        received = self._drain()
        new_alerts = self._evaluate_alerts()
        self.ticks += 1
        return {"sent": sent, "dropped": dropped,
                "received": received, "new_alerts": new_alerts}

    def _drain(self) -> int:
        """把入库端当前可读的报文全部消化（poll 一次只 recv 一段，排空到静默为止）。"""
        total = 0
        while True:
            n = self.rec_client.poll(timeout=0.05)
            if n == 0:
                return total
            total += n

    def _evaluate_alerts(self) -> int:
        """阈值规则逐行评估；越限的落 alerts 表（幂等），返回本轮新增条数。
        台账纪律：每条告警必对应一条 readings 越限行；重复评估不重复计数。"""
        rows = self._alert_conn.execute(
            "SELECT device, seq, temp, vib FROM readings").fetchall()
        now = time.time()
        new = 0
        for device, seq, temp, vib in rows:
            for rule, (metric, threshold) in self.rules.items():
                value = temp if metric == "temp" else vib
                if value > threshold:
                    cur = self._alert_conn.execute(
                        "INSERT OR IGNORE INTO alerts (device, seq, rule, metric, "
                        "value, threshold, raised_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (device, seq, rule, metric, float(value), threshold, now))
                    new += cur.rowcount
        self._alert_conn.commit()
        return new

    def inject(self, device: str, seq: int, temp: float, vib: float,
               anomaly: str = "") -> None:
        """管理口注入：报文经 broker.route() 走真实订阅表发给真实订阅者。
        演示与测试用它送确定性样本，不等随机游走碰运气。"""

        def job():
            payload = json.dumps(
                {"device": str(device), "seq": int(seq), "ts": round(time.time(), 3),
                 "temp": float(temp), "vib": float(vib), "anomaly": str(anomaly)},
                ensure_ascii=False).encode("utf-8")
            self.broker.route(f"{self.topic_prefix}/{device}/data", payload)

        if not _DEVICE_RE.match(str(device)):
            raise ValueError(
                f"设备名只允许字母/数字/下划线/短横线（1..64 字符）：{device!r}")
        self._call(job)

    # ---------------------------------------------------------------- 观察面

    def status(self) -> dict:
        if self.broker is None and self._thread is None:
            return {"running": False, "devices": list(self.devices),
                    "rules": {name: spec[1] for name, spec in self.rules.items()},
                    "interval": self.interval, "db": str(self.db_path)}
        return self._call(self._status_view)

    def _status_view(self) -> dict:
        summary = self.recorder.summary()
        return {
            "running": True,
            "broker": {"host": self.broker.host, "port": self.broker.port,
                       "clients": self.broker.client_count(),
                       "subscriptions": self.broker.subscription_table(),
                       "stats": dict(self.broker.stats)},
            "sims": {dev: {"sent": sim.sent, "ledger": dict(sim.ledger)}
                     for dev, sim in self.sims.items()},
            "recorder": {**summary, "gaps": self.recorder.gaps()},
            "alerts": self._alert_summary(),
            "rules": {name: spec[1] for name, spec in self.rules.items()},
            "devices": list(self.devices),
            "interval": self.interval,
            "db": str(self.db_path),
            "ticks": self.ticks, "tick_errors": self.tick_errors,
            "uptime_s": round(time.time() - self.started_at, 3),
        }

    def known_devices(self) -> list[str]:
        """库里出现过的设备（含注入设备）——曲线与序列接口的合法名单。"""
        return self._call(self._known_devices)

    def _known_devices(self) -> list[str]:
        rows = self._alert_conn.execute(
            "SELECT DISTINCT device FROM readings").fetchall()
        return sorted({r[0] for r in rows} | set(self.devices))

    def series(self, device: str, metric: str = "temp") -> list[tuple[int, float]]:
        if metric not in METRICS:
            raise ValueError(f"metric 只支持 {'/'.join(METRICS)}")
        return self._call(lambda: self.recorder.series(device, metric))

    def anomaly_points(self, device: str) -> list[tuple[int, float, str]]:
        """B35 的异常点（seq, temp, 自报标签）——温度曲线的叠加层。"""
        return self._call(lambda: self.recorder.anomaly_points(device))

    def readings(self, device: str | None = None, limit: int = 5000) -> list[dict]:
        """读数明细（观察口；确定性测试用——剔除 ts 即可与另一次运行逐字比对）。"""
        return self._call(lambda: self._readings(device, int(limit)))

    def _readings(self, device: str | None, limit: int) -> list[dict]:
        sql = ("SELECT device, seq, ts, temp, vib, anomaly FROM readings "
               + ("WHERE device = ? " if device else "")
               + "ORDER BY device, seq LIMIT ?")
        params = (device, limit) if device else (limit,)
        keys = ("device", "seq", "ts", "temp", "vib", "anomaly")
        return [dict(zip(keys, row)) for row in self._alert_conn.execute(sql, params)]

    def alerts(self, limit: int = 100) -> list[dict]:
        return self._call(lambda: self._alerts(int(limit)))

    def _alerts(self, limit: int) -> list[dict]:
        rows = self._alert_conn.execute(
            "SELECT device, seq, rule, metric, value, threshold, raised_at "
            "FROM alerts ORDER BY raised_at DESC, device, seq LIMIT ?",
            (max(1, min(1000, limit)),)).fetchall()
        keys = ("device", "seq", "rule", "metric", "value", "threshold", "raised_at")
        return [dict(zip(keys, row)) for row in rows]

    def _alert_summary(self) -> dict:
        by_rule = {rule: n for rule, n in self._alert_conn.execute(
            "SELECT rule, COUNT(*) FROM alerts GROUP BY rule")}
        return {"total": sum(by_rule.values()), "by_rule": by_rule}
