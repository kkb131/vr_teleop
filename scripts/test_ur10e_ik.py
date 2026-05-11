#!/usr/bin/env python3
"""UR10e_ArmIK 단위 테스트.

검증:
  (a) URDF load + Pinocchio model build (mesh 무시 — buildModelFromUrdf)
  (b) Forward kinematics — init pose 에서 wrist_3_link 위치 합리 (UR10e 기하)
  (c) Round-trip — 100개 random reachable wrist pose → IK → FK 회수, position err < 1cm

실행:
  conda activate tv && unset PYTHONPATH
  python /workspaces/tamp_ws/src/xr_teleop/scripts/test_ur10e_ik.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pinocchio as pin

# 본 scripts 디렉토리 import path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ur10e_arm_ik import UR10E_INIT_POSE, UR10e_ArmIK  # noqa: E402


def main() -> int:
    print("[test] UR10e_ArmIK unit test")

    # (a) URDF load + build
    t0 = time.perf_counter()
    try:
        ik = UR10e_ArmIK(verbose=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n[test] FAIL: build error: {e}", file=sys.stderr)
        return 2
    build_dt = time.perf_counter() - t0
    print(f"[test] (a) build OK ({build_dt:.2f}s)")
    print(f"        nq={ik.nq}, EE='{ik.model.frames[ik.ee_frame_id].name}'")

    # (b) FK at init pose
    fk_init = ik.forward_kinematics(UR10E_INIT_POSE)
    print(f"\n[test] (b) FK at init pose:")
    print(f"        translation = {fk_init.translation}")
    rpy = pin.rpy.matrixToRpy(fk_init.rotation)
    print(f"        rpy = {rpy}")

    ok = True

    def check(cond: bool, label: str, detail: str = ""):
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {label}  {detail}")

    # UR10e geometry sanity: init pose 에서 wrist_3 가 base 위 어딘가 reasonable 거리
    init_pos = fk_init.translation
    check(
        0.2 < np.linalg.norm(init_pos) < 1.5,
        "(b) FK init pose magnitude reasonable",
        f"|p|={np.linalg.norm(init_pos):.3f} m (UR10e reach ≈ 1.3 m)",
    )

    # (c) Round-trip — random reachable poses
    print("\n[test] (c) round-trip 100 random reachable poses")
    np.random.seed(42)
    n_trials = 100
    pos_errs = []
    rot_errs = []
    solve_times = []
    failures = 0

    # 작은 perturbation 으로 reachable workspace 안에서 random 자세 생성
    # init pose 근처에서 ±0.5 rad 변동
    for i in range(n_trials):
        # 1) random q in joint limits 부근 (init ± 0.5 rad)
        q_truth = UR10E_INIT_POSE + np.random.uniform(-0.5, 0.5, size=6)
        # joint limit clamp
        q_truth = np.clip(
            q_truth, ik.model.lowerPositionLimit, ik.model.upperPositionLimit
        )
        # 2) FK → target wrist pose
        target_pose = ik.forward_kinematics(q_truth).homogeneous

        # 3) IK 호출. seed 는 init pose (cold start 같은 조건).
        ik.init_data = UR10E_INIT_POSE.copy()
        t1 = time.perf_counter()
        # G1 signature 호환 — left dummy, right 가 target
        dummy_left = np.eye(4)
        sol_q, _ = ik.solve_ik(dummy_left, target_pose, current_lr_arm_motor_q=None)
        solve_times.append(time.perf_counter() - t1)

        # 4) FK 재계산 → err
        fk_sol = ik.forward_kinematics(sol_q)
        pos_err = np.linalg.norm(fk_sol.translation - target_pose[:3, 3])
        # rotation err: log map
        try:
            R_err = fk_sol.rotation @ target_pose[:3, :3].T
            rot_err = np.linalg.norm(pin.log3(R_err))
        except Exception:
            rot_err = np.nan

        pos_errs.append(pos_err)
        rot_errs.append(rot_err)

        if pos_err > 0.01:
            failures += 1

    pos_errs = np.array(pos_errs)
    rot_errs = np.array(rot_errs)
    solve_times = np.array(solve_times) * 1000  # ms

    print(f"        position err : mean={pos_errs.mean()*1000:.2f} mm  "
          f"max={pos_errs.max()*1000:.2f} mm  median={np.median(pos_errs)*1000:.2f} mm")
    print(f"        rotation err : mean={np.rad2deg(rot_errs.mean()):.2f}°  "
          f"max={np.rad2deg(rot_errs.max()):.2f}°")
    print(f"        solve time   : mean={solve_times.mean():.1f} ms  "
          f"max={solve_times.max():.1f} ms")
    print(f"        position err > 1cm: {failures}/{n_trials}")

    check(
        failures < n_trials * 0.05,
        "(c) round-trip fail rate < 5%",
        f"{failures}/{n_trials}",
    )
    check(
        np.median(pos_errs) < 0.005,
        "(c) position median err < 5mm",
        f"median={np.median(pos_errs)*1000:.2f} mm",
    )
    check(
        solve_times.mean() < 50.0,
        "(c) mean solve time < 50ms (30Hz teleop 충족)",
        f"mean={solve_times.mean():.1f} ms",
    )

    print()
    if ok:
        print("[test] ✅ ALL CHECKS PASSED")
        return 0
    else:
        print("[test] ❌ FAIL")
        return 3


if __name__ == "__main__":
    sys.exit(main())
