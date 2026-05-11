#!/usr/bin/env python3
"""Unit 3 controllers smoke test — sim docker 없이 동작 가능한 부분만 검증.

  (a) import — UR10e_ArmController / DG5F_Controller 클래스 정의 로드 가능
  (b) constants — DDS topic / motor count 가 sim 보고서와 일치
  (c) expand_retarget_to_dg5f_20 — 6 joint 입력 → 20 joint 확장 규칙 검증

DDS instantiate 는 sim docker 필요 — Unit 5 sim test 에서 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    print("[smoke] Unit 3 controllers smoke test")

    ok = True

    def check(cond: bool, label: str, detail: str = ""):
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {label}  {detail}")

    # (a) import
    try:
        import ur10e_arm_controller as uac
        import dg5f_controller as dgc
        check(True, "(a) import UR10e_ArmController + DG5F_Controller")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(False, "(a) import", f"err={e}")
        return 1

    # (b) constants
    check(uac.UR10E_Num_Motors == 6, "(b) UR10E_Num_Motors == 6", f"got {uac.UR10E_Num_Motors}")
    check(uac.kTopicLowCommand_Debug == "rt/lowcmd", "(b) UR10e cmd topic", uac.kTopicLowCommand_Debug)
    check(uac.kTopicLowState == "rt/lowstate", "(b) UR10e state topic", uac.kTopicLowState)
    expected_init = np.array([0.0, -1.57, +1.57, -1.57, -1.57, 0.0])
    check(
        np.allclose(uac.UR10E_INIT_POSE, expected_init, atol=1e-6),
        "(b) UR10e init pose (sim 보고서 §1.2)",
        f"got {uac.UR10E_INIT_POSE.tolist()}",
    )
    check(dgc.DG5F_Num_Motors == 20, "(b) DG5F_Num_Motors == 20", f"got {dgc.DG5F_Num_Motors}")
    check(dgc.kTopicDG5FCommand == "rt/dg5f/cmd", "(b) DG-5F cmd topic", dgc.kTopicDG5FCommand)
    check(dgc.kTopicDG5FState == "rt/dg5f/state", "(b) DG-5F state topic", dgc.kTopicDG5FState)

    # (c) expand_retarget_to_dg5f_20 — 6 input → 20 output, mimic + finger fixed
    target_names = ["rj_dg_1_1", "rj_dg_1_2", "rj_dg_2_2", "rj_dg_3_2", "rj_dg_4_2", "rj_dg_5_2"]
    q_target = {
        "rj_dg_1_1": +0.2,   # thumb 외전
        "rj_dg_1_2": -1.0,   # thumb 굴곡 (negative!)
        "rj_dg_2_2": +0.8,   # index 굴곡
        "rj_dg_3_2": +0.7,
        "rj_dg_4_2": +0.6,
        "rj_dg_5_2": +0.4,
    }
    q20 = dgc.expand_retarget_to_dg5f_20(target_names, q_target)
    check(q20.shape == (20,), "(c) expand 결과 shape (20,)", f"shape={q20.shape}")

    # finger-major check (sim 보고서 §1.3)
    # thumb: 0=_1_1, 1=_1_2, 2=mimic 0.6*_1_2, 3=mimic 0.4*_1_2
    check(abs(q20[0] - 0.2) < 1e-9, "(c) DDS[0] = rj_dg_1_1", f"q={q20[0]:+.3f}")
    check(abs(q20[1] - (-1.0)) < 1e-9, "(c) DDS[1] = rj_dg_1_2 (negative)", f"q={q20[1]:+.3f}")
    check(abs(q20[2] - 0.6 * -1.0) < 1e-9, "(c) DDS[2] = 0.6 * _1_2 (mimic)", f"q={q20[2]:+.3f}")
    check(abs(q20[3] - 0.4 * -1.0) < 1e-9, "(c) DDS[3] = 0.4 * _1_2 (mimic)", f"q={q20[3]:+.3f}")
    # index: 4=0 외전, 5=_2_2, 6=0.6 mimic, 7=0.4 mimic
    check(abs(q20[4]) < 1e-9, "(c) DDS[4] = 0 (index 외전 fixed)")
    check(abs(q20[5] - 0.8) < 1e-9, "(c) DDS[5] = rj_dg_2_2", f"q={q20[5]:+.3f}")
    check(abs(q20[6] - 0.6 * 0.8) < 1e-9, "(c) DDS[6] = 0.6 * _2_2 mimic")
    check(abs(q20[7] - 0.4 * 0.8) < 1e-9, "(c) DDS[7] = 0.4 * _2_2 mimic")
    # middle / ring / pinky 외전 = 0
    check(abs(q20[8]) < 1e-9, "(c) DDS[8] middle 외전 fixed")
    check(abs(q20[12]) < 1e-9, "(c) DDS[12] ring 외전 fixed")
    check(abs(q20[16]) < 1e-9, "(c) DDS[16] pinky 외전 fixed")
    # mimic ratios
    check(abs(q20[10] - 0.6 * 0.7) < 1e-9, "(c) DDS[10] middle 0.6 mimic")
    check(abs(q20[14] - 0.6 * 0.6) < 1e-9, "(c) DDS[14] ring 0.6 mimic")
    check(abs(q20[18] - 0.6 * 0.4) < 1e-9, "(c) DDS[18] pinky 0.6 mimic")

    print()
    if ok:
        print("[smoke] ✅ ALL CHECKS PASSED")
        print("[smoke] DDS instantiate / sim 연결은 Unit 5 e2e 단계에서 검증.")
        return 0
    else:
        print("[smoke] ❌ FAIL")
        return 2


if __name__ == "__main__":
    sys.exit(main())
