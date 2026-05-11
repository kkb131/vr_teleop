"""UR10e single-arm Pinocchio + CasADi IK.

xr_teleoperate/teleop/robot_control/robot_arm_ik.py 의 G1_29_ArmIK 패턴을 복제.
UR10e+DG-5F sim (unitree_sim_isaaclab fork) 측 인터페이스 기준:
  - joint 순서 (DDS index 0-5): shoulder_pan / shoulder_lift / elbow /
    wrist_1 / wrist_2 / wrist_3
  - init pose: [0.0, -1.57, +1.57, -1.57, -1.57, 0.0] (T/ready 자세)
  - EE link: wrist_3_link (sim USD가 tool0/flange/dg_palm 까지 --merge-joints
    로 흡수했으므로 wrist_3_link 가 effective EE)
  - base: AMR pedestal 위 z=1m — 본 클래스의 IK 좌표계는 robot base 기준이라
    z offset 무관. 외부(teleop loop)에서 wrist target 의 frame 변환 책임.

teleop_hand_and_arm.py 와 인터페이스 호환을 위해 dual-arm signature
(left_wrist, right_wrist) 유지하되 left는 무시하고 right 만 IK 풀이.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path

import casadi
import numpy as np
import pinocchio as pin
from pinocchio import casadi as cpin


# UR10e URDF + init pose — sim 보고서 §1.2 일치
UR10E_JOINT_NAMES = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]
UR10E_INIT_POSE = np.array([0.0, -1.57, +1.57, -1.57, -1.57, 0.0], dtype=np.float64)
UR10E_EE_LINK = "wrist_3_link"

# 본 repo 의 UR10e URDF 위치 (assets/ur10e_dg5f/ur10e.urdf)
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URDF_PATH = _REPO_ROOT / "assets" / "ur10e_dg5f" / "ur10e.urdf"


class UR10e_ArmIK:
    """Pinocchio + CasADi 기반 UR10e single-arm IK.

    Parameters
    ----------
    urdf_path : str | Path | None
        UR10e URDF 경로. None 시 본 repo 의 assets/ur10e_dg5f/ur10e.urdf 사용.
    cache_path : str | Path | None
        Pinocchio model cache pickle 경로. None 이면 캐시 사용 안 함.

    Notes
    -----
    teleop_hand_and_arm.py 의 G1_29_ArmIK 패턴 따라 solve_ik(left, right, ...)
    시그니처 유지. UR10e 는 single-arm 이므로 left_wrist 는 무시하고 right_wrist
    만 사용. 결과 sol_q 는 6-vec.
    """

    def __init__(self, urdf_path=None, cache_path=None, verbose: bool = False):
        self.urdf_path = Path(urdf_path) if urdf_path else DEFAULT_URDF_PATH
        self.cache_path = Path(cache_path) if cache_path else None
        self.verbose = verbose

        if self.cache_path and self.cache_path.exists():
            if self.verbose:
                print(f"[UR10e_ArmIK] loading cache {self.cache_path}")
            self.model = self._load_cache()
        else:
            if self.verbose:
                print(f"[UR10e_ArmIK] loading URDF {self.urdf_path}")
            if not self.urdf_path.exists():
                raise FileNotFoundError(f"UR10e URDF not found: {self.urdf_path}")
            # buildModelFromUrdf 는 mesh 무시 — kinematic chain 만 로드.
            # pinocchio.RobotWrapper.BuildFromURDF 는 visual / collision mesh 로드 시도하므로 회피.
            self.model = pin.buildModelFromUrdf(str(self.urdf_path))
            if self.cache_path:
                self._save_cache()
        self.data = self.model.createData()

        # UR10e 의 6 joint 순서가 URDF 등장 순서와 같다고 가정. 검증.
        urdf_joint_names = [
            self.model.names[i] for i in range(1, self.model.njoints)  # 0 은 universe
        ]
        if self.verbose:
            print(f"[UR10e_ArmIK] URDF joints: {urdf_joint_names}")
        # UR10e_JOINT_NAMES 가 URDF 안에 모두 있는지 확인
        for jn in UR10E_JOINT_NAMES:
            if jn not in urdf_joint_names:
                raise RuntimeError(f"joint '{jn}' not found in URDF {self.urdf_path}")

        # EE frame id
        if not self.model.existFrame(UR10E_EE_LINK):
            raise RuntimeError(f"EE link '{UR10E_EE_LINK}' not in URDF")
        self.ee_frame_id = self.model.getFrameId(UR10E_EE_LINK)

        # CasADi symbolic model
        self.cmodel = cpin.Model(self.model)
        self.cdata = self.cmodel.createData()

        # 변수 / 파라미터
        nq = self.model.nq  # UR10e: 6
        self.nq = nq
        self.cq = casadi.SX.sym("q", nq, 1)
        self.cTf = casadi.SX.sym("tf", 4, 4)
        cpin.framesForwardKinematics(self.cmodel, self.cdata, self.cq)

        # Error functions — single EE (G1 은 L_ee + R_ee 둘)
        self.translational_error = casadi.Function(
            "translational_error",
            [self.cq, self.cTf],
            [self.cdata.oMf[self.ee_frame_id].translation - self.cTf[:3, 3]],
        )
        self.rotational_error = casadi.Function(
            "rotational_error",
            [self.cq, self.cTf],
            [cpin.log3(self.cdata.oMf[self.ee_frame_id].rotation @ self.cTf[:3, :3].T)],
        )

        # IPOPT optimization problem
        self.opti = casadi.Opti()
        self.var_q = self.opti.variable(nq)
        self.var_q_last = self.opti.parameter(nq)  # smooth cost 용 seed
        self.param_tf = self.opti.parameter(4, 4)

        self.translational_cost = casadi.sumsqr(
            self.translational_error(self.var_q, self.param_tf)
        )
        self.rotation_cost = casadi.sumsqr(
            self.rotational_error(self.var_q, self.param_tf)
        )
        self.regularization_cost = casadi.sumsqr(self.var_q - UR10E_INIT_POSE)
        self.smooth_cost = casadi.sumsqr(self.var_q - self.var_q_last)

        # Joint limits
        self.opti.subject_to(
            self.opti.bounded(
                self.model.lowerPositionLimit, self.var_q, self.model.upperPositionLimit
            )
        )
        # Weighted total cost — G1 weight 따름
        self.opti.minimize(
            50 * self.translational_cost
            + self.rotation_cost
            + 0.02 * self.regularization_cost
            + 0.1 * self.smooth_cost
        )

        opts = {
            "expand": True,
            "detect_simple_bounds": True,
            "calc_lam_p": False,
            "print_time": False,
            "ipopt.sb": "yes",
            "ipopt.print_level": 0,
            "ipopt.max_iter": 30,
            "ipopt.tol": 1e-4,
            "ipopt.acceptable_tol": 5e-4,
            "ipopt.acceptable_iter": 5,
            "ipopt.warm_start_init_point": "yes",
            "ipopt.derivative_test": "none",
            "ipopt.jacobian_approximation": "exact",
        }
        self.opti.solver("ipopt", opts)

        # warm-start state
        self.init_data = UR10E_INIT_POSE.copy()

    def _save_cache(self):
        with open(self.cache_path, "wb") as f:
            pickle.dump({"model": self.model}, f)

    def _load_cache(self):
        with open(self.cache_path, "rb") as f:
            return pickle.load(f)["model"]

    def solve_ik(
        self,
        left_wrist,
        right_wrist,
        current_lr_arm_motor_q=None,
        current_lr_arm_motor_dq=None,
    ):
        """G1_29_ArmIK.solve_ik 시그니처 호환.

        left_wrist 는 무시 (single-arm). right_wrist 를 EE target 으로.

        Parameters
        ----------
        left_wrist : (4,4) ignored
        right_wrist : (4,4) SE3 target for wrist_3_link
        current_lr_arm_motor_q : (6,) or None
            현재 arm joint. seed (warm start) 로 사용.
        current_lr_arm_motor_dq : (6,) or None
            현재 arm joint velocity. tauff 계산에는 사용 안 함 (G1 패턴 따라 0).

        Returns
        -------
        sol_q : (6,) np.ndarray
        sol_tauff : (6,) np.ndarray  (gravity comp, RNEA)
        """
        if current_lr_arm_motor_q is not None and len(current_lr_arm_motor_q) >= self.nq:
            self.init_data = np.array(current_lr_arm_motor_q[: self.nq], dtype=np.float64)

        self.opti.set_initial(self.var_q, self.init_data)
        self.opti.set_value(self.param_tf, right_wrist)
        self.opti.set_value(self.var_q_last, self.init_data)

        try:
            sol = self.opti.solve()
            sol_q = self.opti.value(self.var_q)
            self.init_data = sol_q
            sol_tauff = pin.rnea(
                self.model, self.data, sol_q, np.zeros(self.nq), np.zeros(self.nq)
            )
            return sol_q, sol_tauff
        except Exception as e:
            if self.verbose:
                print(f"[UR10e_ArmIK] IK 수렴 실패 ({e}) — debug value 반환")
            sol_q = self.opti.debug.value(self.var_q)
            self.init_data = sol_q
            sol_tauff = pin.rnea(
                self.model, self.data, sol_q, np.zeros(self.nq), np.zeros(self.nq)
            )
            return sol_q, sol_tauff

    def forward_kinematics(self, q):
        """Forward kinematics — debugging / 단위 테스트용."""
        pin.framesForwardKinematics(self.model, self.data, np.asarray(q, dtype=np.float64))
        return self.data.oMf[self.ee_frame_id].copy()
