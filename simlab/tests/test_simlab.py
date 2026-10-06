"""simlab 自测：记录格式正负例 + 三引擎对拍 + 确定性 + CLI。

对拍口径（不引用凭印象的值）：
    - 引擎适配层的 metrics 与**直接调用原项目引擎**的返回值同源一致
      （dijkstra 的 dist/path、knapsack 的 best/chosen、astar 的 cost/expanded）；
    - 确定性：同参数两次运行，剔除 created_at 后逐字节一致（B34 纪律的延伸）；
    - 负例：格式错/帧 t 错/缺字段/负权边/越界障碍，全部一次性报全或如实抛错。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import simlab
from simlab.record import RecordError, load, save, validate

from algo.dp import knapsack
from algo.graph import dijkstra as raw_dijkstra, path_of, undirected
from planner.grid import Grid
from planner.heuristics import manhattan
from planner.search import astar as raw_astar

DIJKSTRA_PARAMS = {"n": 4, "edges": [[0, 1, 2], [1, 2, 1], [0, 2, 5], [2, 3, 3]],
                   "src": 0, "dst": 3}
KNAPSACK_PARAMS = {"weights": [2, 3, 4], "values": [3, 4, 5], "capacity": 6}
ASTAR_PARAMS = {"width": 5, "height": 4, "walls": [[1, 1], [2, 1], [2, 2]],
                "start": [0, 0], "goal": [4, 3], "heuristic": "manhattan"}


def strip_time(record: dict) -> str:
    copy = dict(record)
    copy.pop("created_at", None)
    return json.dumps(copy, sort_keys=True, allow_nan=False)


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.base = simlab.run_experiment("b12-knapsack", KNAPSACK_PARAMS)

    def test_build_validate_roundtrip(self):
        record = simlab.build(experiment=self.base["experiment"],
                              title=self.base["title"],
                              engine=self.base["engine"],
                              params=self.base["params"],
                              frames=self.base["frames"],
                              metrics=self.base["metrics"])
        self.assertEqual(record["format"], "simlab-run/v1")
        self.assertIs(validate(record), record)

    def test_save_load_roundtrip(self):
        record = simlab.build(experiment=self.base["experiment"],
                              title="t", engine=self.base["engine"],
                              params=self.base["params"],
                              frames=self.base["frames"],
                              metrics=self.base["metrics"])
        with tempfile.TemporaryDirectory() as td:
            path = save(record, Path(td) / "runs" / "a.json")
            loaded = load(path)
        self.assertEqual(strip_time(loaded), strip_time(record))

    def test_problems_reported_all_at_once(self):
        bad = {"format": "wrong"}            # 其余五个必填字段全缺
        with self.assertRaises(RecordError) as ctx:
            validate(bad)
        text = "；".join(ctx.exception.problems)
        for needle in ("format", "experiment", "engine", "params",
                       "metrics", "frames"):
            self.assertIn(needle, text)          # 一次报全，不挤牙膏

    def test_frame_t_must_match_index(self):
        frames = [{"t": 1, "caption": "x", "state": {}}]
        with self.assertRaises(RecordError) as ctx:
            validate({"format": "simlab-run/v1", "experiment": "e", "title": "t",
                      "engine": "g", "params": {}, "frames": frames,
                      "metrics": {}})
        self.assertIn("t", "；".join(ctx.exception.problems))

    def test_frame_needs_caption_and_state(self):
        frames = [{"t": 0, "state": {}}]
        with self.assertRaises(RecordError) as ctx:
            validate({"format": "simlab-run/v1", "experiment": "e", "title": "t",
                      "engine": "g", "params": {}, "frames": frames,
                      "metrics": {}})
        self.assertIn("caption", "；".join(ctx.exception.problems))

    def test_save_rejects_non_finite_floats(self):
        """JSON 没有无穷大：Infinity 在落盘那一刻就得炸，不许流到播放器。"""
        record = {"format": "simlab-run/v1", "experiment": "e", "title": "t",
                  "engine": "g", "params": {},
                  "frames": [{"t": 0, "caption": "c", "state": {}}],
                  "metrics": {"d": float("inf")}}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                save(record, Path(td) / "bad.json")

    def test_load_bad_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.json"
            path.write_text("{oops", encoding="utf-8")
            with self.assertRaises(RecordError):
                load(path)


class TestDijkstraEngine(unittest.TestCase):
    def setUp(self):
        self.record = simlab.run_experiment("b12-dijkstra", DIJKSTRA_PARAMS)

    def test_metrics_match_direct_engine_call(self):
        """适配层不改语义：metrics 必须与直接调用 B12 引擎一致。"""
        edges = undirected([tuple(e) for e in DIJKSTRA_PARAMS["edges"]])
        dist, prev = raw_dijkstra(4, edges, 0)
        path = path_of(prev, 0, 3)
        self.assertEqual(self.record["metrics"]["dist"],
                         {v: d for v, d in enumerate(dist)})
        self.assertEqual(self.record["metrics"]["path"], list(path))

    def test_frames_are_settle_snapshots(self):
        frames = self.record["frames"]
        self.assertEqual(len(frames), self.record["metrics"]["settled_count"])
        for i, frame in enumerate(frames):
            self.assertEqual(frame["t"], i)
            self.assertEqual(frame["state"]["settled"][-1], frame["state"]["current"])
        self.assertEqual(frames[-1]["state"]["settled"],
                         sorted(s for s in frames[-1]["state"]["settled"]))

    def test_deterministic(self):
        again = simlab.run_experiment("b12-dijkstra", DIJKSTRA_PARAMS)
        self.assertEqual(strip_time(self.record), strip_time(again))

    def test_engine_guard_negative_weight(self):
        """负权边由 B12 引擎自己的守卫拒绝（不重写守卫，也不放行）。"""
        with self.assertRaises(ValueError):
            simlab.run_experiment(
                "b12-dijkstra", {"n": 2, "edges": [[0, 1, -5]], "src": 0})


class TestKnapsackEngine(unittest.TestCase):
    def setUp(self):
        self.record = simlab.run_experiment("b12-knapsack", KNAPSACK_PARAMS)

    def test_metrics_match_direct_engine_call(self):
        best, chosen = knapsack([2, 3, 4], [3, 4, 5], 6)
        self.assertEqual(self.record["metrics"]["best"], best)
        self.assertEqual(self.record["metrics"]["chosen"], list(chosen))

    def test_frames_are_table_rows_plus_recall(self):
        frames = self.record["frames"]
        # 0 行 + 每件物品一行 + 回溯帧
        self.assertEqual(len(frames), 1 + len(KNAPSACK_PARAMS["weights"]) + 1)
        self.assertEqual(frames[1]["state"]["row"], [0, 0, 3, 3, 3, 3, 3])
        self.assertEqual(frames[-1]["state"]["chosen"],
                         self.record["metrics"]["chosen"])

    def test_deterministic(self):
        again = simlab.run_experiment("b12-knapsack", KNAPSACK_PARAMS)
        self.assertEqual(strip_time(self.record), strip_time(again))

    def test_engine_guard_length_mismatch(self):
        with self.assertRaises(ValueError):
            simlab.run_experiment(
                "b12-knapsack", {"weights": [1], "values": [1, 2], "capacity": 5})


class TestAstarEngine(unittest.TestCase):
    def setUp(self):
        self.record = simlab.run_experiment("b34-astar", ASTAR_PARAMS)

    def test_metrics_match_direct_engine_call(self):
        grid = Grid(width=5, height=4,
                    obstacles={tuple(c) for c in ASTAR_PARAMS["walls"]})
        result = raw_astar(grid, (0, 0), (4, 3), manhattan)
        self.assertEqual(self.record["metrics"]["found"], result.found)
        self.assertEqual(self.record["metrics"]["cost"], result.cost)
        self.assertEqual(self.record["metrics"]["expanded_count"],
                         result.expanded_count)
        self.assertEqual(self.record["metrics"]["path"],
                         [list(c) for c in result.path])

    def test_frames_are_expanded_prefixes(self):
        frames = self.record["frames"]
        self.assertEqual(len(frames), self.record["metrics"]["expanded_count"])
        self.assertEqual(frames[-1]["state"]["current"],
                         frames[-1]["highlights"][0])
        self.assertEqual([f["state"]["current"] for f in frames],
                         [list(c) for c in frames[-1]["state"]["expanded"]])

    def test_admissible_heuristic_never_expands_more(self):
        """B34 核心教学点：可采纳的 h 扩展数 ≤ h=0（Dijkstra）。"""
        zero_run = simlab.run_experiment(
            "b34-astar", {**ASTAR_PARAMS, "heuristic": "zero"})
        self.assertLessEqual(self.record["metrics"]["expanded_count"],
                             zero_run["metrics"]["expanded_count"])

    def test_engine_guard_blocked_endpoint(self):
        """起点在障碍里：由 B34 的 require_free 守卫拒绝。"""
        with self.assertRaises(ValueError):
            simlab.run_experiment(
                "b34-astar", {**ASTAR_PARAMS, "start": [1, 1]})

    def test_deterministic(self):
        again = simlab.run_experiment("b34-astar", ASTAR_PARAMS)
        self.assertEqual(strip_time(self.record), strip_time(again))


class TestRegistryAndCli(unittest.TestCase):
    def test_unknown_experiment_lists_available(self):
        with self.assertRaises(ValueError) as ctx:
            simlab.run_experiment("nope", {})
        self.assertIn("b12-dijkstra", str(ctx.exception))

    def test_cli_writes_valid_record(self):
        with tempfile.TemporaryDirectory() as td:
            params_path = Path(td) / "params.json"
            params_path.write_text(json.dumps(KNAPSACK_PARAMS), encoding="utf-8")
            out = Path(td) / "run.json"
            proc = subprocess.run(
                [sys.executable, str(Path(simlab.__file__).parents[1] / "simlab" / "run.py"),
                 "b12-knapsack", "--params-file", str(params_path),
                 "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            record = load(out)               # 落盘的记录要过自家校验器
            self.assertEqual(record["experiment"], "b12-knapsack")

    def test_cli_unknown_experiment_exit_2(self):
        proc = subprocess.run(
            [sys.executable, str(Path(simlab.__file__).parents[1] / "simlab" / "run.py"),
             "nope"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("b12-knapsack", proc.stderr)

    def test_cli_bad_params_exit_2(self):
        proc = subprocess.run(
            [sys.executable, str(Path(simlab.__file__).parents[1] / "simlab" / "run.py"),
             "b12-knapsack", "--params", "{oops"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
