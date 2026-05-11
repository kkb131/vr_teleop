"""UR10e arm DDS controller.

G1_29_ArmController 패턴 복제 + single-arm 으로 단순화. sim docker
(unitree_sim_isaaclab fork) 의 `rt/lowcmd` / `rt/lowstate` 인터페이스로 UR10e 6
joint 만 publish / subscribe. mode/kp/kd 는 sim 이 무시하지만 일관성 위해
채움 (보고서 §4.7).

API 는 G1_29_ArmController 와 호환:
  ctrl_dual_arm(q_target, tauff_target)  -- q_target 6-vec, tauff 6-vec
  get_current_dual_arm_q()  -- 6-vec
  get_current_dual_arm_dq() -- 6-vec
  ctrl_dual_arm_go_home()
  speed_gradual_max(t)
"""
from __future__ import annotations

import threading
import time
from enum import IntEnum

import numpy as np

# DDS (CycloneDDS via unitree_sdk2py)
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_ as hg_LowCmd
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as hg_LowState
from unitree_sdk2py.utils.crc import CRC

# Topics — sim 보고서 §1.1 G1 과 동일 (sim 측이 rt/lowstate motor[0:6] 만 채움)
kTopicLowCommand_Debug = "rt/lowcmd"
kTopicLowState = "rt/lowstate"

# UR10e: 6 motor (DDS index 0..5)
UR10E_Num_Motors = 6
# sim 보고서 §1.2 init pose
UR10E_INIT_POSE = np.array([0.0, -1.57, +1.57, -1.57, -1.57, 0.0], dtype=np.float64)


class UR10e_JointIndex(IntEnum):
    """sim 보고서 §1.2 DDS index 0..5 ↔ UR10e joint name."""
    kShoulderPan = 0
    kShoulderLift = 1
    kElbow = 2
    kWrist1 = 3
    kWrist2 = 4
    kWrist3 = 5


class _DataBuffer:
    """thread-safe single-slot buffer (G1 패턴)."""
    def __init__(self):
        self._lock = threading.Lock()
        self._data = None

    def SetData(self, data):
        with self._lock:
            self._data = data

    def GetData(self):
        with self._lock:
            return self._data


class _UR10eLowState:
    """LowState 의 motor[0:6] subset only."""
    def __init__(self):
        self.motor_state = [type("ms", (), {"q": 0.0, "dq": 0.0})() for _ in range(UR10E_Num_Motors)]


class UR10e_ArmController:
    """UR10e single-arm DDS controller — sim 보고서 §1.1, §1.2 인터페이스."""

    def __init__(self, motion_mode: bool = False, simulation_mode: bool = True,
                 control_dt: float = 1.0 / 250.0):
        """
        Parameters
        ----------
        motion_mode : G1 호환 인자 (UR10e 는 의미 없음, 무시)
        simulation_mode : sim docker 운용 모드 — clip 비활성 (sim 이 받는 그대로)
        control_dt : publish 주기 (default 250Hz)
        """
        print("[UR10e_ArmController] init...")
        self.q_target = UR10E_INIT_POSE.copy()
        self.tauff_target = np.zeros(UR10E_Num_Motors)
        self.simulation_mode = simulation_mode
        self.control_dt = control_dt

        # G1 default arm gains — sim 이 무시하지만 일관성 위해 채움 (보고서 §4.7)
        self.kp = 80.0
        self.kd = 3.0

        self.arm_velocity_limit = 20.0
        self._speed_gradual_max = False
        self._gradual_start_time = None

        # DDS publisher / subscriber
        self.lowcmd_publisher = ChannelPublisher(kTopicLowCommand_Debug, hg_LowCmd)
        self.lowcmd_publisher.Init()
        self.lowstate_subscriber = ChannelSubscriber(kTopicLowState, hg_LowState)
        self.lowstate_subscriber.Init()
        self.lowstate_buffer = _DataBuffer()

        # subscribe thread
        self._subscribe_thread = threading.Thread(target=self._subscribe_motor_state)
        self._subscribe_thread.daemon = True
        self._subscribe_thread.start()

        # wait for first rt/lowstate
        wait_t0 = time.time()
        while not self.lowstate_buffer.GetData():
            time.sleep(0.1)
            if time.time() - wait_t0 > 10.0:
                print("[UR10e_ArmController] WARN: 10s 동안 rt/lowstate 미수신 — sim docker 부팅 확인")
                wait_t0 = time.time()  # 계속 대기

        print("[UR10e_ArmController] subscribed rt/lowstate.")

        # cmd msg 초기화
        self.crc = CRC()
        self.msg = unitree_hg_msg_dds__LowCmd_()
        self.msg.mode_pr = 0
        self.msg.mode_machine = 0  # sim 무시

        # motor_cmd[0..5] 만 mode=1, kp/kd 설정. 나머지 [6..34] mode=0.
        current_q = self.get_current_dual_arm_q()
        for i in range(35):  # LowCmd_ 는 35 motor slot
            if i < UR10E_Num_Motors:
                self.msg.motor_cmd[i].mode = 1
                self.msg.motor_cmd[i].kp = self.kp
                self.msg.motor_cmd[i].kd = self.kd
                self.msg.motor_cmd[i].q = current_q[i]  # 안전: 시작 시 현재값
            else:
                self.msg.motor_cmd[i].mode = 0
                self.msg.motor_cmd[i].kp = 0.0
                self.msg.motor_cmd[i].kd = 0.0
                self.msg.motor_cmd[i].q = 0.0

        # publish thread
        self.ctrl_lock = threading.Lock()
        self._publish_thread = threading.Thread(target=self._ctrl_motor_state)
        self._publish_thread.daemon = True
        self._publish_thread.start()

        print("[UR10e_ArmController] init OK.")

    def _subscribe_motor_state(self):
        while True:
            msg = self.lowstate_subscriber.Read()
            if msg is not None:
                ls = _UR10eLowState()
                for i in range(UR10E_Num_Motors):
                    ls.motor_state[i].q = msg.motor_state[i].q
                    ls.motor_state[i].dq = msg.motor_state[i].dq
                self.lowstate_buffer.SetData(ls)
            time.sleep(0.002)

    def clip_arm_q_target(self, target_q: np.ndarray, velocity_limit: float) -> np.ndarray:
        current_q = self.get_current_dual_arm_q()
        delta = target_q - current_q
        motion_scale = np.max(np.abs(delta)) / (velocity_limit * self.control_dt)
        return current_q + delta / max(motion_scale, 1.0)

    def _ctrl_motor_state(self):
        while True:
            start_time = time.time()

            with self.ctrl_lock:
                arm_q_target = self.q_target.copy()
                arm_tauff_target = self.tauff_target.copy()

            if self.simulation_mode:
                cliped_q = arm_q_target
            else:
                cliped_q = self.clip_arm_q_target(arm_q_target, velocity_limit=self.arm_velocity_limit)

            for i in range(UR10E_Num_Motors):
                self.msg.motor_cmd[i].q = float(cliped_q[i])
                self.msg.motor_cmd[i].dq = 0.0
                self.msg.motor_cmd[i].tau = float(arm_tauff_target[i])

            # CRC sim 은 검증 안 함 (보고서 §1.1)
            self.msg.crc = self.crc.Crc(self.msg)
            self.lowcmd_publisher.Write(self.msg)

            if self._speed_gradual_max:
                t_elapsed = start_time - self._gradual_start_time
                self.arm_velocity_limit = 20.0 + (10.0 * min(1.0, t_elapsed / 5.0))

            elapsed = time.time() - start_time
            time.sleep(max(0, self.control_dt - elapsed))

    # ── 공개 API (G1_29_ArmController 호환) ──────────────────────────────────

    def ctrl_dual_arm(self, q_target, tauff_target):
        """q_target/tauff_target 둘 다 6-vec (UR10e). G1 dual-arm 14-vec 시그니처 호환."""
        q_target = np.asarray(q_target, dtype=np.float64).flatten()
        tauff_target = np.asarray(tauff_target, dtype=np.float64).flatten()
        # G1 호환: dual-arm 14-vec 받았으면 첫 6개 또는 마지막 6개? UR10e는 right side가
        # 의미 있는 입력이지만 IK에서 이미 6-vec 반환하므로 안전.
        if len(q_target) == 14:
            # left=q[0:7], right=q[7:14] — right 만 사용. UR10e 6-vec.
            q_target = q_target[7:13]
        if len(tauff_target) == 14:
            tauff_target = tauff_target[7:13]
        if len(q_target) != UR10E_Num_Motors:
            raise ValueError(
                f"ctrl_dual_arm: q_target len={len(q_target)} != {UR10E_Num_Motors}"
            )
        with self.ctrl_lock:
            self.q_target = q_target
            self.tauff_target = tauff_target

    def get_current_motor_q(self):
        """G1 호환 alias — UR10e 는 motor_q == dual_arm_q."""
        return self.get_current_dual_arm_q()

    def get_current_dual_arm_q(self) -> np.ndarray:
        """현재 motor[0:6].q (6-vec)."""
        data = self.lowstate_buffer.GetData()
        if data is None:
            return UR10E_INIT_POSE.copy()
        return np.array([data.motor_state[i].q for i in range(UR10E_Num_Motors)])

    def get_current_dual_arm_dq(self) -> np.ndarray:
        data = self.lowstate_buffer.GetData()
        if data is None:
            return np.zeros(UR10E_Num_Motors)
        return np.array([data.motor_state[i].dq for i in range(UR10E_Num_Motors)])

    def ctrl_dual_arm_go_home(self):
        """UR10e 의 init pose 로 (zero 가 아닌 T-pose). G1 의 zeros 와 다름."""
        print("[UR10e_ArmController] go to init pose...")
        with self.ctrl_lock:
            self.q_target = UR10E_INIT_POSE.copy()
            self.tauff_target = np.zeros(UR10E_Num_Motors)
        tol = 0.05
        for _ in range(100):
            current_q = self.get_current_dual_arm_q()
            if np.all(np.abs(current_q - UR10E_INIT_POSE) < tol):
                print("[UR10e_ArmController] init pose reached.")
                return
            time.sleep(0.05)
        print("[UR10e_ArmController] init pose 도달 시간 초과 (tolerance ±0.05 rad)")

    def speed_gradual_max(self, t: float = 5.0):
        self._gradual_start_time = time.time()
        self._speed_gradual_max = True

    def speed_instant_max(self):
        self.arm_velocity_limit = 30.0
