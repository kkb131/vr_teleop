"""DG-5F single-hand DDS controller + retargeting.

Dex3_1_Controller (xr_teleoperate/teleop/robot_control/robot_hand_unitree.py)
패턴 복제 + single-hand. sim docker (unitree_sim_isaaclab fork) 의 신규 topic
`rt/dg5f/cmd` / `rt/dg5f/state` 사용 (sim 보고서 §1.1).

dex_retargeting 의 vector retargeting 으로 6 target joint 풀이 후 20 joint
finger-major vector 로 확장 (Day 1 spike §확장 규칙):
  - DDS 0  ← rj_dg_1_1 (retarget)            thumb 외전
  - DDS 1  ← rj_dg_1_2 (retarget, negative)  thumb 굴곡
  - DDS 2  = 0.6 * DDS 1                    thumb 중 mimic
  - DDS 3  = 0.4 * DDS 1                    thumb tip mimic
  - DDS 4, 8, 12, 16 = 0.0                  finger 외전 fixed
  - DDS 5  ← rj_dg_2_2 (retarget)           index 굴곡
  - DDS 6  = 0.6 * DDS 5
  - DDS 7  = 0.4 * DDS 5
  - ... (middle, ring, pinky 동일)
"""
from __future__ import annotations

import os
import sys
import threading
import time
from multiprocessing import Array, Lock, Process
from pathlib import Path

import numpy as np
import yaml

from dex_retargeting import RetargetingConfig
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber
from unitree_sdk2py.idl.default import (
    unitree_hg_msg_dds__HandCmd_,
    unitree_hg_msg_dds__MotorCmd_,
)
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandCmd_, HandState_


# sim 보고서 §1.1 신규 topic
kTopicDG5FCommand = "rt/dg5f/cmd"
kTopicDG5FState = "rt/dg5f/state"
DG5F_Num_Motors = 20  # sim 보고서 §1.3 finger-major 20 joint

# 본 repo의 assets/dg5f_hand/
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YML_PATH = _REPO_ROOT / "assets" / "dg5f_hand" / "dg5f_right.yml"
DEFAULT_ASSETS_DIR = _REPO_ROOT / "assets"


# ─────────────────────────────────────────────────────────────────
# Wrist-local + palm-aligned frame transform for WebXR 25-keypoint hand.
#
# Why: televuer 의 right_hand_pos 는 arm-frame translation 만 정렬 — wrist
# orientation 미반영. dex_retargeting vector cost 는 magnitude only 라 두 vec
# 가 같은 frame 이어야 정확. 그대로 넘기면 사용자 손목 회전 시 손가락 자세가
# 잘못 풀이됨 ("잘못된 wrist pose 기준" — 사용자 보고).
#
# 처방: retarget_dev/sensing/core/mano_transform.py 의 apply_mano_transform
# 패턴 그대로. MANO 21-joint 가 아니라 WebXR 25-joint 인덱스로 적응.
# 검증: retarget_dev manus_debug.md — 같은 변환 누락 버그가 fist→spread
# inversion 의 90% 원인 (12 배 개선 측정).
# ─────────────────────────────────────────────────────────────────

# MediaPipe convention (retarget_dev 의 phone path 검증). WebXR HandLandmarker
# 가 image-derived MediaPipe 와 같은 chirality 인지 미확정 — 사용자 visual
# 확인 시 fist↔spread 가 반대면 MANUS variant 로 전환 (row 1 sign flip).
_OPERATOR2MANO_RIGHT = np.array(
    [[0, 0, -1],
     [-1, 0, 0],
     [0, 1, 0]],
    dtype=np.float64,
)


def _estimate_wrist_frame_webxr(kp_25: np.ndarray) -> np.ndarray:
    """WebXR 25-joint wrist frame estimation via palm-plane SVD.

    retarget_dev/sensing/core/mano_transform.py:estimate_wrist_frame
    의 WebXR 변형. palm-plane 정의의 3 점만 인덱스 변경:
      - MANO 21: [0, 5, 9]   = wrist, index_MCP, middle_MCP
      - WebXR 25: [0, 5, 10] = wrist, index-metacarpal, middle-metacarpal
    metacarpal 이 palm 안쪽이라 palm-plane fit 정확도 ↑.

    Returns
    -------
    (3, 3) rotation matrix — columns = x/y/z basis vectors of wrist frame.
    """
    points = kp_25[[0, 5, 10], :]
    # x: palm → middle finger base
    x_vector = points[0] - points[2]
    # SVD palm-plane normal
    centered = points - points.mean(axis=0, keepdims=True)
    _u, _s, v = np.linalg.svd(centered)
    normal = v[2, :]
    # Gram-Schmidt: x ⊥ normal
    x = x_vector - np.dot(x_vector, normal) * normal
    x = x / (np.linalg.norm(x) + 1e-10)
    z = np.cross(x, normal)
    # disambiguation: z 는 pinky → index 방향
    if np.dot(z, (points[1] - points[2])) < 0:
        normal = -normal
        z = -z
    return np.stack([x, normal, z], axis=1).astype(np.float64)


def webxr_to_wrist_local_mano(kp_25: np.ndarray) -> np.ndarray:
    """WebXR (25, 3) world frame → wrist-local + palm-aligned (25, 3).

    Pipeline (retarget_dev/sensing/core/mano_transform.py:apply_mano_transform
    그대로):
        1. wrist-center: pos - pos[0]
        2. SVD palm-plane fit → wrist rotation
        3. kp @ wrist_rot @ operator2mano

    사용자가 손목을 yaw/pitch/roll 회전해도 손가락 자세가 같으면 동일한
    출력 — retargeter 가 손가락 자세만 학습.
    """
    centered = kp_25 - kp_25[0]
    wrist_rot = _estimate_wrist_frame_webxr(centered)
    return centered @ wrist_rot @ _OPERATOR2MANO_RIGHT


def expand_retarget_to_dg5f_20(
    target_joint_names: list,
    q_target_dict: dict,
    mimic_mid: float = 0.6,
    mimic_tip: float = 0.4,
) -> np.ndarray:
    """retargeting 6 joint q → 20-vec DDS motor command.

    DG-5F finger-major: thumb(0..3), index(4..7), middle(8..11), ring(12..15),
    pinky(16..19). 각 finger 4 joint: _1 외전, _2 굴곡, _3 mid, _4 tip.

    Mimic rule:
      _3 = mimic_mid * _2
      _4 = mimic_tip * _2
      _1 (외전) = retargeting 결과 그대로 또는 0 (thumb 만 retarget, 나머지 0).

    Parameters
    ----------
    target_joint_names : retargeter.optimizer.target_joint_names 순서
    q_target_dict : {joint_name: q value}  — retarget 결과 6 joint
    mimic_mid, mimic_tip : human PIP/DIP 굽힘 비율 추정. Unit 5 sim test 에서 조정.

    Returns
    -------
    (20,) np.ndarray  -- DDS motor_cmd[0:20] 그대로 채울 수 있음
    """
    q = np.zeros(DG5F_Num_Motors, dtype=np.float64)

    # thumb (DDS 0..3)
    q[0] = q_target_dict.get("rj_dg_1_1", 0.0)
    q[1] = q_target_dict.get("rj_dg_1_2", 0.0)
    q[2] = mimic_mid * q[1]
    q[3] = mimic_tip * q[1]

    # index (DDS 4..7)
    q[4] = 0.0  # 외전 fixed
    q[5] = q_target_dict.get("rj_dg_2_2", 0.0)
    q[6] = mimic_mid * q[5]
    q[7] = mimic_tip * q[5]

    # middle (DDS 8..11)
    q[8] = 0.0
    q[9] = q_target_dict.get("rj_dg_3_2", 0.0)
    q[10] = mimic_mid * q[9]
    q[11] = mimic_tip * q[9]

    # ring (DDS 12..15)
    q[12] = 0.0
    q[13] = q_target_dict.get("rj_dg_4_2", 0.0)
    q[14] = mimic_mid * q[13]
    q[15] = mimic_tip * q[13]

    # pinky (DDS 16..19)
    q[16] = 0.0
    q[17] = q_target_dict.get("rj_dg_5_2", 0.0)
    q[18] = mimic_mid * q[17]
    q[19] = mimic_tip * q[17]

    return q


class DG5F_Controller:
    """DG-5F single-hand DDS controller — Dex3_1_Controller 패턴 + single-hand.

    Quest 3 hand keypoint (25, 3) 를 우측 손 only 로 받아 retargeting →
    20 joint expand → `rt/dg5f/cmd` publish.

    Parameters
    ----------
    right_hand_array_in : multiprocessing.Array (75 = 25*3)
        Quest 3 right hand keypoint. teleop_hand_and_arm.py 가 shared array
        에 write.
    hand_data_lock, hand_state_array_out, hand_action_array_out :
        Dex3 패턴과 동일 (state / action 출력 공유 — 녹화/디버깅).
    fps : control loop frequency.
    simulation_mode : sim 모드 (현재 cleanup 차이 없음, 호환성 위해).
    yml_path : retargeting yml 경로. 기본은 assets/dg5f_hand/dg5f_right.yml.
    """

    def __init__(
        self,
        right_hand_array_in,
        hand_data_lock=None,
        hand_state_array_out=None,
        hand_action_array_out=None,
        fps: float = 100.0,
        simulation_mode: bool = True,
        yml_path: Path = DEFAULT_YML_PATH,
        assets_dir: Path = DEFAULT_ASSETS_DIR,
    ):
        print("[DG5F_Controller] init...")
        self.fps = fps
        self.simulation_mode = simulation_mode

        # retargeter build
        with open(yml_path) as f:
            cfg = yaml.safe_load(f)
        right_cfg = cfg["right"]
        RetargetingConfig.set_default_urdf_dir(str(assets_dir))
        self.right_retargeting = RetargetingConfig.from_dict(right_cfg).build()
        self.right_indices = self.right_retargeting.optimizer.target_link_human_indices
        self.target_joint_names = list(self.right_retargeting.optimizer.target_joint_names)
        self.fixed_joint_names = list(self.right_retargeting.optimizer.fixed_joint_names)
        self.full_joint_names = list(self.right_retargeting.joint_names)
        print(f"[DG5F_Controller] retargeter: target={len(self.target_joint_names)} joints, "
              f"fixed={len(self.fixed_joint_names)}")

        # DDS pub/sub
        self.cmd_publisher = ChannelPublisher(kTopicDG5FCommand, HandCmd_)
        self.cmd_publisher.Init()
        self.state_subscriber = ChannelSubscriber(kTopicDG5FState, HandState_)
        self.state_subscriber.Init()

        # shared hand state array (multiprocessing)
        self.hand_state_array = Array("d", DG5F_Num_Motors, lock=True)

        # subscribe thread
        self._subscribe_thread = threading.Thread(target=self._subscribe_hand_state)
        self._subscribe_thread.daemon = True
        self._subscribe_thread.start()

        # wait for first state
        wait_t0 = time.time()
        while True:
            if any(self.hand_state_array):
                break
            time.sleep(0.01)
            if time.time() - wait_t0 > 10.0:
                print("[DG5F_Controller] WARN: rt/dg5f/state 10s 미수신 — sim docker 부팅 확인")
                wait_t0 = time.time()
        print("[DG5F_Controller] subscribed rt/dg5f/state.")

        # control process — Dex3 와 같은 multiprocessing.Process 분리
        self._hand_control_process = Process(
            target=self._control_process,
            args=(
                right_hand_array_in,
                self.hand_state_array,
                hand_data_lock,
                hand_state_array_out,
                hand_action_array_out,
            ),
            daemon=True,
        )
        self._hand_control_process.start()

        print("[DG5F_Controller] init OK.")

    def _subscribe_hand_state(self):
        while True:
            msg = self.state_subscriber.Read()
            if msg is not None:
                # stock unitree_sdk2py HandState_ 는 motor_state default 7-slot 이지만
                # sim docker 가 20-slot 으로 확장해 publish. wire format 호환 위해 동적 길이.
                n = min(DG5F_Num_Motors, len(msg.motor_state))
                for i in range(n):
                    self.hand_state_array[i] = msg.motor_state[i].q
            time.sleep(0.002)

    def _ctrl_publish(self, q_20: np.ndarray):
        """20 joint q vector → `rt/dg5f/cmd` publish.

        stock `unitree_hg.HandCmd_` 는 Dex3 기준 motor_cmd default 7-slot. DG-5F 는
        20 joint 필요 → CycloneDDS sequence 라 길이 확장 가능. 매 publish 시
        motor_cmd list 를 20개 `MotorCmd_` 로 reset 후 채움 (sim docker 가 20-slot
        IDL 로 wire format 매칭).
        """
        msg = unitree_hg_msg_dds__HandCmd_()
        msg.motor_cmd = [unitree_hg_msg_dds__MotorCmd_() for _ in range(DG5F_Num_Motors)]
        for i in range(DG5F_Num_Motors):
            msg.motor_cmd[i].mode = 1
            msg.motor_cmd[i].q = float(q_20[i])
            msg.motor_cmd[i].dq = 0.0
            msg.motor_cmd[i].tau = 0.0
            msg.motor_cmd[i].kp = 1.5  # Dex3 default (sim은 자체 PD 사용, 무시)
            msg.motor_cmd[i].kd = 0.2
        self.cmd_publisher.Write(msg)

    def _control_process(
        self,
        right_hand_array_in,
        hand_state_array,
        hand_data_lock,
        hand_state_array_out,
        hand_action_array_out,
    ):
        """retargeting + DDS publish loop (자식 프로세스). Dex3 패턴."""
        q_20_target = np.zeros(DG5F_Num_Motors)
        fixed_qpos = np.zeros(len(self.fixed_joint_names), dtype=np.float64)

        try:
            while True:
                t0 = time.time()

                # 1) Quest 3 right hand keypoint 읽기
                with right_hand_array_in.get_lock():
                    right_hand_data = np.array(right_hand_array_in[:]).reshape(25, 3).copy()

                # 2) hand 가 초기화 안 됐으면 skip (Dex3 패턴)
                if not np.all(right_hand_data == 0.0):
                    # 2.5) Frame 변환 (U5++): WebXR world → wrist-local + palm-aligned
                    # televuer 가 wrist orientation 미반영한 채 hand_pos 를 넘김 →
                    # 사용자 손목 회전 시 retargeter 가 잘못 풀이. retarget_dev 의
                    # apply_mano_transform 패턴 적용해 동일 손가락 자세는 동일 출력.
                    hand_local = webxr_to_wrist_local_mano(right_hand_data)

                    # 3) ref_value = task - origin vector (Day 1 spike)
                    ref_value = (
                        hand_local[self.right_indices[1, :]]
                        - hand_local[self.right_indices[0, :]]
                    )
                    # 4) retarget → robot_qpos (target + fixed mixed)
                    robot_qpos = self.right_retargeting.retarget(ref_value, fixed_qpos=fixed_qpos)

                    # 5) DDS 20-vec 추출
                    # - DexPilot (target=20): robot_qpos.shape == (20,) 그대로 사용.
                    #   URDF 순서 = DDS index 순서 (rj_dg_1_1, ..., _5_4) 이므로 직접 매핑.
                    # - vector (target=6, 이전 config 호환): expand_retarget_to_dg5f_20 으로
                    #   mimic 0.6/0.4 확장.
                    if len(self.target_joint_names) == DG5F_Num_Motors:
                        # DexPilot or full-target retargeter
                        q_20_target = np.array(robot_qpos[:DG5F_Num_Motors], dtype=np.float64)
                    else:
                        # subset target (e.g. vector type with 6 target joint)
                        q_target_dict = {
                            n: robot_qpos[self.full_joint_names.index(n)]
                            for n in self.target_joint_names
                        }
                        q_20_target = expand_retarget_to_dg5f_20(self.target_joint_names, q_target_dict)

                # 7) Publish
                self._ctrl_publish(q_20_target)

                # 8) state / action shared array update
                if hand_state_array_out is not None and hand_action_array_out is not None:
                    state_now = np.array(hand_state_array[:])
                    with hand_data_lock:
                        # state/action 둘 다 20-vec. 단순 mirror — record 용
                        hand_state_array_out[:] = state_now[: len(hand_state_array_out)]
                        hand_action_array_out[:] = q_20_target[: len(hand_action_array_out)]

                # 9) sleep to maintain fps
                elapsed = time.time() - t0
                time.sleep(max(0, 1.0 / self.fps - elapsed))
        except KeyboardInterrupt:
            pass
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            print("[DG5F_Controller] control_process exited.")
