"""fault/config.py —— 全部可调参数集中在唯一一处（测试/演示引用同一份口径）。

课程要点（行业软件）：实验的"口径"必须是显式的、可引用的对象——
窗口多长、预测提前多久、哪些窗口排除、按设备还是按随机切分，
写散在各处的默认参数就是让两个报告说两套话。种子基座固定，
整条时间线（读数、异常、故障、切分）逐字可复现。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Config:
    # ---------------------------------------------------------------- 车队与时间
    n_devices: int = 10
    steps: int = 480
    seed_base: int = 70                # 设备 d 的种子 = seed_base + d
    base_temp: float = 70.0
    base_temp_jitter: float = 6.0      # 各设备安装点基线不同（±6°C）：没有它，
    #                                    "按设备切分"就是假问题（见 README 实测对照）

    # ---------------------------------------------------------------- 基线信号（OU）
    temp_reversion: float = 0.05       # 向基线回复比例：σ ≈ noise/√(2·θ) ≈ 2.2°C
    temp_noise: float = 1.2
    vib_reversion: float = 0.08        # 振动基线 0.5，σ ≈ 0.15
    vib_noise: float = 0.06

    # ---------------------------------------------------------------- 传感器账本
    spike_p: float = 0.03              # B35 的三类异常：spike 与 freeze 保留，
    freeze_p: float = 0.03             # dropout 归零——"断数"B35 已讲透，且
    dropout_p: float = 0.0             # 缺行会让窗口与账本对不齐（见 README 口径）
    spike_delta: float = 35.0          # 单点尖峰幅度（B35 的 40°C 是持久偏移，见 README）

    # ---------------------------------------------------------------- 故障注入
    failures_per_device: int = 3
    first_failure_min: int = 60
    min_gap: int = 120                 # 两次故障的最小间隔（避免窗口重叠）
    ramp: int = 24                     # 退化斜坡长度：故障前 ramp 步开始恶化
    decay: int = 5                     # 故障后的恢复暂态（这段窗口排除出评估）
    overheat_rate: float = 1.6         # 过热型：每步 +rate°C
    wear_rate: float = 0.09            # 磨损型：每步 +rate 振动

    # ---------------------------------------------------------------- 特征与标签
    window: int = 8                    # 滑窗长度（读数个数）
    stride: int = 6                    # 窗口步进
    horizon: int = 24                  # 标签：未来 horizon 步内会发生故障则标 1

    # ---------------------------------------------------------------- 切分
    test_devices: tuple = (8, 9)       # 按设备切：训练 0..7，测试 8..9（不见过的设备）
    random_split_seed: int = 11        # 对照臂：全窗口随机切分（用于展示泄漏）

    # ---------------------------------------------------------------- 模型
    tree_max_depth: int = 4
    tree_min_samples: int = 12
    gd_epochs: int = 800
    gd_lr: float = 0.5
    l2: float = 0.01                   # L2 惩罚：可分方向上 MLE 权重会发散，
    newt_iters: int = 40               # 无惩罚时 GD 与 Newton 落在发散路径的不同点（见 README 坑记）
    newt_tol: float = 1e-10

    # ---------------------------------------------------------------- 评估
    sweep_step: float = 0.02           # 阈值扫描步长


DEFAULT = Config()
