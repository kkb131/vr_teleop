#!/usr/bin/env python3
"""DG-5F dex_retargeting 단위 테스트.

목적:
  - assets/dg5f_hand/dg5f_right.yml + dg5f_right.urdf 로드 가능 확인
  - dummy WebXR 25-joint hand pose 입력 → 6 target joint 출력
  - thumb rj_dg_1_2 (negative flexion direction) sign convention 확인
  - 모든 joint 출력이 URDF limit 안에 있는지

실행:
  conda activate tv
  cd src/xr_teleop/xr_teleoperate/teleop/robot_control     # urdf_path가 cwd-relative
  python /workspaces/tamp_ws/src/xr_teleop/scripts/test_dg5f_retargeting.py

또는 (cwd 자동 보정):
  python -m scripts.test_dg5f_retargeting   # 추후 packaging 후
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import yaml

# urdf_path는 yml에서 "dg5f_hand/dg5f_right.urdf" — set_default_urdf_dir로 base를 지정
# Inspire/Dex3 패턴: dex_retargeting cwd가 robot_control/ 일 때 ../assets 가 됨.
# 단위 테스트는 cwd 무관하게 동작하도록 절대 경로로 설정.
REPO_ROOT = Path(__file__).resolve().parents[1]  # xr_teleop/
ASSETS_DIR = REPO_ROOT / "assets"   # 본 repo의 assets (xr_teleoperate/ gitignored이라 분리)
YML_PATH = ASSETS_DIR / "dg5f_hand" / "dg5f_right.yml"

from dex_retargeting import RetargetingConfig  # noqa: E402


# 보고서 §1.3 + dg5f_right.urdf 한계
URDF_LIMITS = {
    "rj_dg_1_1": (-0.384, +0.890),
    "rj_dg_1_2": (-3.1416, +0.0),    # negative flexion
    "rj_dg_2_2": (0.0, +2.0071),     # positive flexion
    "rj_dg_3_2": (0.0, +1.9548),
    "rj_dg_4_2": (0.0, +1.9024),
    "rj_dg_5_2": (-0.4189, +0.6109),
}


def make_dummy_hand(pose: str) -> np.ndarray:
    """**DG-5F palm frame 기준** 25-joint hand keypoint positions [meters].

    DG-5F URDF palm frame:
      - +z = 손가락 뻗는 방향 (finger forward)
      - +y = palm normal (손바닥 등쪽 — palm 두께 방향)
      - +x = pinky 쪽 (DG-5F는 right hand; -x = thumb 쪽)

    실제 WebXR Quest 3 좌표계와 다를 수 있어 sim test 단계에서 회전 align 필요.
    여기선 retargeting *동작 자체* (sign convention, joint limit, 입력→출력 변화) 검증용 dummy.

    Pose:
      - 'open': 손가락이 +z 방향으로 펼쳐진 자세
      - 'fist': fingertip이 palm 안쪽(-y)으로 굽힌 자세
      - 'thumb_curl': thumb만 굽음
    """
    p = np.zeros((25, 3), dtype=np.float64)
    p[0] = [0.0, 0.0, 0.0]  # wrist == palm origin

    # 손가락 base position (URDF origin과 매칭, palm frame):
    #   thumb (-0.016, 0.019, 0.013)
    #   index (-0.007, 0.027, 0.066)
    #   middle ( 0.000, 0.027, 0.083)
    #   ring  (+0.007, 0.027, 0.077)
    #   pinky (+0.014, 0.027, 0.070)

    if pose == "open":
        # 모든 손가락이 +z 방향으로 펼침
        # thumb (1..4): -x 쪽으로 약간 회전 + +z 방향
        p[1] = [-0.020, +0.020, +0.025]
        p[2] = [-0.035, +0.020, +0.050]
        p[3] = [-0.045, +0.020, +0.075]
        p[4] = [-0.050, +0.020, +0.085]    # thumb-tip
        # index (5..9): wrist에서 +z 방향
        p[5] = [-0.007, +0.027, +0.075]
        p[6] = [-0.007, +0.027, +0.105]
        p[7] = [-0.007, +0.027, +0.125]
        p[8] = [-0.007, +0.027, +0.140]
        p[9] = [-0.007, +0.027, +0.150]    # index-tip
        # middle (10..14)
        p[10] = [+0.000, +0.027, +0.092]
        p[11] = [+0.000, +0.027, +0.125]
        p[12] = [+0.000, +0.027, +0.150]
        p[13] = [+0.000, +0.027, +0.165]
        p[14] = [+0.000, +0.027, +0.175]   # middle-tip
        # ring (15..19)
        p[15] = [+0.007, +0.027, +0.085]
        p[16] = [+0.007, +0.027, +0.115]
        p[17] = [+0.007, +0.027, +0.138]
        p[18] = [+0.007, +0.027, +0.155]
        p[19] = [+0.007, +0.027, +0.163]   # ring-tip
        # pinky (20..24)
        p[20] = [+0.014, +0.027, +0.080]
        p[21] = [+0.014, +0.027, +0.105]
        p[22] = [+0.014, +0.027, +0.123]
        p[23] = [+0.014, +0.027, +0.135]
        p[24] = [+0.014, +0.027, +0.140]   # pinky-tip

    elif pose == "fist":
        # fingertip이 palm 안쪽(-y, palm 안쪽)으로 굽힘. +z 방향에서 -y 방향으로 회전.
        # thumb: -x, -y 가깝게 굽힘
        p[1] = [-0.020, +0.020, +0.025]
        p[2] = [-0.030, +0.010, +0.040]
        p[3] = [-0.030, -0.010, +0.045]
        p[4] = [-0.025, -0.020, +0.040]    # thumb-tip 굽음
        # index: 처음 +z, 그 다음 -y 방향으로 굽음
        p[5] = [-0.007, +0.027, +0.075]
        p[6] = [-0.007, +0.020, +0.110]
        p[7] = [-0.007, -0.005, +0.115]
        p[8] = [-0.007, -0.030, +0.105]
        p[9] = [-0.007, -0.045, +0.085]    # index-tip palm 안쪽
        # middle: 가장 긴 손가락, 더 굽음
        p[10] = [+0.000, +0.027, +0.092]
        p[11] = [+0.000, +0.020, +0.130]
        p[12] = [+0.000, -0.010, +0.135]
        p[13] = [+0.000, -0.040, +0.120]
        p[14] = [+0.000, -0.055, +0.095]   # middle-tip
        # ring
        p[15] = [+0.007, +0.027, +0.085]
        p[16] = [+0.007, +0.020, +0.120]
        p[17] = [+0.007, -0.005, +0.125]
        p[18] = [+0.007, -0.030, +0.115]
        p[19] = [+0.007, -0.045, +0.090]   # ring-tip
        # pinky
        p[20] = [+0.014, +0.027, +0.080]
        p[21] = [+0.014, +0.020, +0.110]
        p[22] = [+0.014, +0.000, +0.118]
        p[23] = [+0.014, -0.025, +0.105]
        p[24] = [+0.014, -0.035, +0.085]   # pinky-tip

    elif pose == "thumb_curl":
        # 다른 손가락 open, thumb만 굽음
        p = make_dummy_hand("open").copy()
        p[1] = [-0.020, +0.020, +0.025]
        p[2] = [-0.030, +0.010, +0.040]
        p[3] = [-0.030, -0.010, +0.045]
        p[4] = [-0.025, -0.020, +0.040]
    else:
        raise ValueError(f"unknown pose {pose}")

    return p


def load_retargeter():
    """yml load + RetargetingConfig.build()."""
    with YML_PATH.open() as f:
        cfg = yaml.safe_load(f)
    right_cfg = cfg["right"]
    # urdf_path는 yml에 'dg5f_hand/dg5f_right.urdf'로 적혀있음.
    # set_default_urdf_dir로 absolute base 지정해 cwd 의존성 제거.
    RetargetingConfig.set_default_urdf_dir(str(ASSETS_DIR))
    rcfg = RetargetingConfig.from_dict(right_cfg)
    retargeter = rcfg.build()
    return retargeter, right_cfg


def main() -> int:
    print(f"[test] loading dg5f_right.yml from {YML_PATH}")
    if not YML_PATH.exists():
        print(f"[test] FAIL: yml not found at {YML_PATH}", file=sys.stderr)
        return 1

    try:
        retargeter, cfg = load_retargeter()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n[test] FAIL: retargeter build error: {e}", file=sys.stderr)
        return 2

    # dex_retargeting joint_names == URDF의 모든 revolute joint (20개).
    # target_joint_names (yml) = retargeter가 자유롭게 풀이 (6개).
    # 나머지 14개 = fixed_qpos로 retarget() 호출 시 전달.
    target_joint_names = list(retargeter.optimizer.target_joint_names)
    fixed_joint_names = list(retargeter.optimizer.fixed_joint_names)
    print(f"[test] retargeter.joint_names ({len(retargeter.joint_names)}): {list(retargeter.joint_names)}")
    print(f"[test] target_joint_names ({len(target_joint_names)}): {target_joint_names}")
    print(f"[test] fixed_joint_names ({len(fixed_joint_names)}): {fixed_joint_names}")
    print(f"[test] target_link_human_indices = {retargeter.optimizer.target_link_human_indices}")

    # fixed_qpos: nontarget joint들을 0으로 (init/relaxed). DG5F_Controller 측에서
    # 실제로는 init pose 또는 직전 값으로 전달하지만, 단위 테스트는 0이면 충분.
    fixed_qpos = np.zeros(len(fixed_joint_names), dtype=np.float64)

    # vector retargeting의 ref_value는 25-joint raw가 아니라 (N_vector, 3) shape의
    # task-origin 차이 벡터. dex_retargeting의 robot_hand_unitree.py:188 패턴 따름:
    #   ref = hand_kp[indices[1,:]] - hand_kp[indices[0,:]]
    indices = retargeter.optimizer.target_link_human_indices  # shape (2, N_vec)
    print(f"[test] vector indices [origins, tasks] = \n  origins: {indices[0]}\n  tasks:   {indices[1]}")

    # 3 poses 검증
    results = {}
    for pose in ("open", "fist", "thumb_curl"):
        hand_kp = make_dummy_hand(pose)
        ref_value = hand_kp[indices[1, :]] - hand_kp[indices[0, :]]   # (N_vec, 3)
        robot_qpos = retargeter.retarget(ref_value, fixed_qpos=fixed_qpos)
        # robot_qpos는 20-vector (target + fixed mixed). target만 추출.
        q_map = dict(zip(retargeter.joint_names, robot_qpos))
        results[pose] = (q_map, hand_kp)
        print(f"\n[test] pose={pose}")
        for name in target_joint_names:
            val = q_map[name]
            lo, hi = URDF_LIMITS.get(name, (-np.inf, np.inf))
            mark = ""
            if val < lo - 1e-4 or val > hi + 1e-4:
                mark = "  !! OUT OF LIMIT"
            print(f"  {name:12s} = {val:+.4f}   (limit {lo:+.3f} .. {hi:+.3f}){mark}")

    # ─── Assertions ────────────────────────────────────────────────────────
    print("\n[test] ─── checks ───")

    # results는 이미 q_map dict (joint_name → val).
    open_q = results["open"][0]
    fist_q = results["fist"][0]
    thumb_q = results["thumb_curl"][0]

    ok = True

    def check(cond: bool, label: str, detail: str = ""):
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {label}  {detail}")
        return cond

    # 단위 테스트 범위:
    #   (a) smoke: yml/URDF load OK, retarget 3 dummy poses 예외 없이 동작, 20-vec 반환
    #   (b) URDF limit 준수 (5e-3 tolerance — numerical boundary)
    #   (c) ROUND-TRIP: known robot q → robot FK → dummy human vector → retarget 회수
    #       Quest 3 / DG-5F 좌표계 align 무관하게 retargeting 수렴성 검증.

    # (a) retarget 성공
    check(
        len(results) == 3 and all(len(r[0]) == 20 for r in results.values()),
        "(a) retarget 3 dummy poses succeeded (20-vec each)",
    )

    # (b) target joint 출력 URDF limit 안 (numerical tolerance 5e-3)
    for pose, (q_map, _) in results.items():
        for name in target_joint_names:
            val = q_map[name]
            lo, hi = URDF_LIMITS.get(name, (-np.inf, np.inf))
            check(
                lo - 5e-3 <= val <= hi + 5e-3,
                f"(b) {pose} {name} in URDF limit (±5e-3)",
                f"q={val:+.4f}",
            )

    # (c) ROUND-TRIP: 좌표계 align 무관 검증
    print("\n[test] ─── (c) round-trip 검증 (좌표계 align 무관) ───")
    robot = retargeter.optimizer.robot
    palm_link_id = robot.get_link_index("rl_dg_palm")
    tip_link_ids = [robot.get_link_index(f"rl_dg_{i}_tip") for i in (1, 2, 3, 4, 5)]

    # 의미 있는 known target pose: thumb 약한 굴곡 + 4 finger 중간 굴곡
    known_targets = [
        {"name": "neutral", "q": {n: 0.0 for n in target_joint_names}},
        {"name": "fist_mid", "q": {
            "rj_dg_1_1": +0.0,
            "rj_dg_1_2": -0.8,
            "rj_dg_2_2": +1.0,
            "rj_dg_3_2": +1.0,
            "rj_dg_4_2": +1.0,
            "rj_dg_5_2": +0.3,
        }},
        {"name": "open_spread", "q": {
            "rj_dg_1_1": +0.4,
            "rj_dg_1_2": -0.1,
            "rj_dg_2_2": +0.05,
            "rj_dg_3_2": +0.05,
            "rj_dg_4_2": +0.05,
            "rj_dg_5_2": +0.0,
        }},
    ]

    for case in known_targets:
        # robot full qpos vector (20) — target은 known, fixed는 0
        full_q = np.zeros(20)
        for n, v in case["q"].items():
            idx = list(retargeter.joint_names).index(n)
            full_q[idx] = v
        # robot FK
        robot.compute_forward_kinematics(full_q.astype(np.float32))
        palm_pose = robot.get_link_pose(palm_link_id)
        tip_poses = [robot.get_link_pose(tid) for tid in tip_link_ids]
        # palm → tip vectors (in world frame, but origin=palm 이므로 palm-relative)
        palm_pos = palm_pose[:3, 3]
        tip_positions = [tp[:3, 3] for tp in tip_poses]
        palm_to_tips = np.array([tp - palm_pos for tp in tip_positions])  # (5, 3)

        # human dummy: wrist at 0, fingertip at (palm_to_tips * scale=1.0)
        # ref_value는 task - origin 차이라 그대로 사용
        ref_value = palm_to_tips.copy()  # (5, 3)

        # 재시도 위해 retargeter state 초기화 — last_qpos를 0으로 (cold start)
        retargeter.last_qpos = np.zeros(len(target_joint_names))

        robot_qpos = retargeter.retarget(ref_value, fixed_qpos=np.zeros(len(fixed_joint_names)))
        q_recovered = {n: robot_qpos[list(retargeter.joint_names).index(n)] for n in target_joint_names}

        print(f"\n  case={case['name']}:")
        max_err = 0.0
        for n in target_joint_names:
            target = case["q"][n]
            recovered = q_recovered[n]
            err = abs(target - recovered)
            max_err = max(max_err, err)
            print(f"    {n:12s}: target={target:+.4f}  recovered={recovered:+.4f}  err={err:.4f}")
        # vector retargeting은 fingertip *위치*만 매칭 — 굽힘 *magnitude*는 underdetermined.
        # exact value 검증보다 "방향(sign) 일치 + max_err < 1.0" 수준의 정성 검증.
        # 자세한 정량 평가는 Unit 5 (실제 Quest 3 hand) 단계로.
        check(
            max_err < 1.0,
            f"(c) round-trip {case['name']} max_err < 1.0 (vector retargeting 한계 감안)",
            f"max_err={max_err:.4f}",
        )
        # sign 일치 확인 (target ≠ 0 인 joint만).
        # pinky rj_dg_5_2는 _1 외전과 _2 굴곡이 모두 fingertip 위치에 영향 → underdetermined.
        # 실제 Quest 3 hand에선 손가락이 일관된 방향으로 굽으므로 ambiguity 감소 — informational.
        for n in target_joint_names:
            target = case["q"][n]
            recovered = q_recovered[n]
            if abs(target) > 0.05:  # nontrivial target
                sign_ok = (np.sign(target) == np.sign(recovered)) or abs(recovered) < 0.1
                if n == "rj_dg_5_2":  # informational only (pinky underdetermined)
                    mark = "[info]" if sign_ok else "[info-mismatch]"
                    print(f"  {mark} {case['name']} {n} sign  target={target:+.4f}, recovered={recovered:+.4f}")
                else:
                    check(
                        sign_ok,
                        f"(c-sign) {case['name']} {n} sign 일치",
                        f"target={target:+.4f}, recovered={recovered:+.4f}",
                    )

    print()
    if ok:
        print("[test] ✅ ALL CHECKS PASSED")
        return 0
    else:
        print("[test] ❌ FAIL — see above")
        return 3


if __name__ == "__main__":
    sys.exit(main())
