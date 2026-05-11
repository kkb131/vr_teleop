# Week 4 개발 결과 보고서 — UR10e + Tesollo DG-5F 통합 (Quest 3 기반)

**프로젝트**: xr_teleoperate 기반 Galaxy XR + UR10e + DG-5F 원격조종 시스템
**기간**: Phase 2, Week 4
**대상 헤드셋**: Meta Quest 3 (현재 본 PC USB-C 연결) — Galaxy XR 은 Week 7-8 이월
**목적**: Phase 1 G1+Dex3 sim 인프라를 **UR10e + DG-5F sim** 으로 교체. Quest 3 hand → IsaacSim UR10e (6-DOF) + DG-5F (5-finger) teleop 동작 (Gate 4)

---

## 1. 금주 목표

12 주 개발 계획의 **Phase 2 - Week 4** 단계로, Path B (sim 우선 → 통합) 첫 주.

- sim docker 측 `unitree_sim_isaaclab` fork (`feat/ur10e-dg5f-sim`) 가 Week 3 마지막에 완성 (sim 보고서 `74aad24`) — DDS topic (rt/lowstate motor[0:6], rt/dg5f/{cmd,state}) + ZMQ camera (head 55555, right_wrist 55557) 모두 G1+Dex3 sim 과 같은 패턴 publish.
- 본 docker (xr_teleop dev PC) 측에서 다음 5 개 작업 단위 진행:
  1. **U1**: DG-5F dex_retargeting config (vector type, 6 target joint)
  2. **U2**: UR10e_ArmIK (Pinocchio + CasADi single-arm, wrist_3_link EE)
  3. **U3**: UR10e_ArmController + DG5F_Controller (DDS publisher)
  4. **U4**: `run_teleop_ur10e.py` (UR10e+DG-5F 전용 teleop entry, upstream 무수정)
  5. **U5**: Quest 3 end-to-end + Gate 4 측정

> Gate 4 통과 시 → Week 5 (DG-5F retargeting fine-tuning + 좌표 align)
> Gate 4 실패 시 → 분기 처방 ([day5_e2e_spike.md](week4/day5_e2e_spike.md) §4)

본 주차 통합 환경:
- **xr_teleop side**: 본 docker, conda env `tv` (Python 3.10, pinocchio 3.1.0, numpy 1.26.4, dex_retargeting installed via `INSTALL_DEX_RETARGETING=1 bash scripts/install.sh`)
- **sim host side**: 같은 물리 host의 별도 docker (`unitree_sim_isaaclab` fork `feat/ur10e-dg5f-sim`, IsaacSim 5.1.0)
- **헤드셋**: Meta Quest 3 (USB-C, `adb reverse tcp:8012/60001/60003`)
- 두 docker `--network=host` → CycloneDDS multicast 자동

---

## 2. 주요 결과 및 산출물

### 2.1 핵심 결과 요약 (Unit 별 검증)

| Unit | 검증 | 결과 | 측정 |
|---|---|---|---|
| **U1** | DG-5F retargeting unit test | ✅ ALL PASS | 3 dummy poses, URDF limit, round-trip sign 일치 |
| **U2** | UR10e_ArmIK round-trip (100 random poses) | ✅ ALL PASS | median pos err 2.63mm, solve 1.8ms |
| **U3** | UR10e_ArmController + DG5F_Controller smoke | ✅ ALL PASS | 26 assertions: const + expansion 규칙 |
| **U4** | run_teleop_ur10e.py --help + sanity check | ✅ PASS | argparse + import + conda env tv 통과 |
| **U5** | Quest 3 E2E (sim + xr + Quest 3) | ⏳ **사용자 실측 대기** | [§3 측정 절차](#3-수행-내역) |

**Gate 4 통과 여부**: ⏳ U5 측정 후 판정

### 2.2 신규 파일

| 위치 | 파일 | 역할 |
|---|---|---|
| assets/ | `dg5f_hand/dg5f_right.urdf` + meshes/ (12MB) | DG-5F right hand URDF (xr_teleoperate/ gitignored 으로 본 repo 분리) |
| assets/ | `dg5f_hand/dg5f_right.yml` | dex_retargeting config (6 target joint, 5 fingertip vector) |
| assets/ | `ur10e_dg5f/ur10e.urdf` | UR10e URDF (src/tamp_dev 에서 copy) |
| scripts/ | `ur10e_arm_ik.py` | UR10e_ArmIK 클래스 (Pinocchio + CasADi) |
| scripts/ | `ur10e_arm_controller.py` | UR10e_ArmController (rt/lowcmd publisher) |
| scripts/ | `dg5f_controller.py` | DG5F_Controller (single-hand) + `expand_retarget_to_dg5f_20` |
| scripts/ | `run_teleop_ur10e.py` | UR10e+DG-5F teleop entry (upstream 무수정) |
| scripts/ | `test_dg5f_retargeting.py`, `test_ur10e_ik.py`, `test_controllers_smoke.py` | 단위 테스트 3 종 |
| docs/week4/ | README.md, INTERIM_TEST_GUIDE.md, day{1..5}_*_spike.md | 진행 기록 + 검증 가이드 |
| docs/ | `week4_report.md` (본 문서) | 주간 결과 보고 |

### 2.3 commit 이력

| commit | unit | 작업 |
|---|---|---|
| `acb6996` | U1 | DG-5F dex_retargeting config + URDF + unit test |
| `fbd218f` | U2 | UR10e_ArmIK (Pinocchio + CasADi single-arm) |
| `fa29ffa` | U3 | UR10e_ArmController + DG5F_Controller (DDS publisher) |
| `c18cf51` | U4 | run_teleop_ur10e.py (UR10e+DG-5F teleop entry) |
| (TBD) | U5 | E2E 결과 측정 후 추가 |

---

## 3. 수행 내역

### 3.1 sim docker 측 작업 (외부)

sim docker 측 Claude Code 가 Week 3 마지막에 [sim_build_complete_report.md](../../unitree_sim_isaaclab/custom/docs/sim_build_complete_report.md) 와 함께 `feat/ur10e-dg5f-sim` 브랜치 완성. 검증 7 항목 모두 PASS:

- `Isaac-Reach-UR10e-DG5F-Joint` task 부팅 (~80s)
- `rt/lowstate` 97 Hz publish (motor[0:6] valid)
- `rt/dg5f/state` ~50 Hz publish (motor[0:20])
- ZMQ camera head=55555 (30Hz, 5.9KB), right_wrist=55557 (30Hz, 21.8KB)
- WebRTC 60001 / 60003 OK (60002 disable)
- `rt/lowcmd` round-trip max err 0.025 rad
- `rt/dg5f/cmd` round-trip max err 0.015 rad

본 docker 측 작업의 출발점. **인터페이스가 G1+Dex3 sim 과 동일 패턴** → xr_teleop 측 변경 최소화.

### 3.2 Unit 1 — DG-5F dex_retargeting (commit `acb6996`)

상세: [day1_dg5f_retargeting_spike.md](week4/day1_dg5f_retargeting_spike.md).

핵심 작업:
- `dg5f_right.yml` — vector type, 6 target joint (thumb _1_1/_1_2 + 4 finger _2 굴곡)
- DG-5F URDF + 12MB meshes 를 본 repo `assets/dg5f_hand/` 로 이동 (xr_teleoperate/ gitignored)
- `scripts/test_dg5f_retargeting.py` — 3 dummy pose smoke + 3 round-trip cases

시행착오 5 건 (상세 spike 참조):
1. `retarget()` 가 (25,3) raw 가 아닌 (N_vec, 3) vector 차이를 받음
2. `fixed_qpos` 필요 (nontarget 14 joint)
3. DG-5F palm frame +z = finger (WebXR convention 과 다름)
4. Vector retargeting magnitude underdetermined (Unit 5 fine-tune 대상)
5. Pinky _2 underdetermined (외전 + 굴곡 둘 다 fingertip 영향)

### 3.3 Unit 2 — UR10e_ArmIK (commit `fbd218f`)

상세: [day2_ur10e_ik_spike.md](week4/day2_ur10e_ik_spike.md).

G1_29_ArmIK 패턴 복제 + dual-arm 제거. wrist_3_link 직접 EE. init pose seed `[0, -1.57, +1.57, -1.57, -1.57, 0]` (sim 보고서 §1.2).

**성능** (100 random reachable poses, init ± 0.5 rad):
- position err median 2.63 mm / max 5.87 mm (목표 < 5mm median ✅)
- rotation err mean 3.29° / max 6.99° (Unit 5 sim test 재검증)
- solve time mean 1.8 ms / max 9.8 ms (30Hz 의 1/3 만 차지)
- fail rate 0/100

핵심 결정: `pin.buildModelFromUrdf` (mesh 무시) 사용해 `package://ur_description` 의존성 회피.

### 3.4 Unit 3 — Controllers (commit `fa29ffa`)

상세: [day3_controllers_spike.md](week4/day3_controllers_spike.md).

- **UR10e_ArmController**: G1 ctrl_dual_arm signature 호환 (14-vec 받으면 [7:13] 추출). LowCmd_ 35-slot 중 motor_cmd[0..5] 만 의미 채움. kp=80, kd=3 default (sim 무시 — 일관성).
- **DG5F_Controller**: Dex3 패턴 + single-hand. `expand_retarget_to_dg5f_20` 으로 6 retarget joint → 20-vec finger-major 확장:

```
DDS 0  ← rj_dg_1_1                    thumb 외전
DDS 1  ← rj_dg_1_2 (NEGATIVE)         thumb 굴곡
DDS 2  = 0.6 * DDS 1                  thumb mid mimic
DDS 3  = 0.4 * DDS 1                  thumb tip mimic
DDS 4,8,12,16 = 0.0                   finger 외전 fixed
DDS 5,9,13,17 ← rj_dg_{2..5}_2        finger 굴곡
DDS 6,10,14,18 = 0.6 * 굴곡           mid mimic
DDS 7,11,15,19 = 0.4 * 굴곡           tip mimic
```

mimic 비율 0.6/0.4 는 Unit 5 sim test 에서 조정.

Smoke 26 assertions PASS — const + topic 이름 + expansion 규칙.

### 3.5 Unit 4 — run_teleop_ur10e.py (commit `c18cf51`)

상세: [day4_integration_spike.md](week4/day4_integration_spike.md).

upstream teleop_hand_and_arm.py 가 G1/H1 + dex3/inspire 만 지원 → **별도 entry script 신규 작성** (upstream 무수정 원칙 유지).

run_teleop.py 의 monkey-patches 2종 (`_apply_http_monkey_patch`, `_patch_image_spawn_retry`) 재사용 + `_sanity_check` 그대로. main loop 핵심 5 step (record / IPC / dual-arm slicing 생략).

```python
while not STOP:
    head_img = img_client.get_head_frame()
    tv_wrapper.render_to_xr(head_img)   # display_mode 따라
    tele_data = tv_wrapper.get_tele_data()
    right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()   # DG5F child process
    current_q = arm_ctrl.get_current_dual_arm_q()
    sol_q, sol_tauff = arm_ik.solve_ik(np.eye(4), tele_data.right_wrist_pose, current_q)
    arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)
    time.sleep(1/30 - elapsed)
```

Smoke (--help) PASS — argparse + import + sanity check.

### 3.6 Unit 5 — E2E test (사용자 실측 대기)

상세: [day5_e2e_spike.md](week4/day5_e2e_spike.md).

본 docker 의 Claude Code 가 sim docker 에 접근 불가 → 사용자가 직접 sim + Quest 3 부팅 + 측정. Day 5 spike 에 절차 + 측정 양식 + 알려진 issue 처방 4 개 (DG-5F magnitude / UR10e base frame / IK fail / vuer scene 빈 공간) 정리.

측정 대기 항목 14 개 (Gate 4 통과 기준). 통과 시 Week 5 진입.

---

## 4. 이슈 및 리스크

### 4.1 코드 단계에서 식별된 알려진 한계 (Unit 5 측정 결과 따라 처방 적용)

| ID | 설명 | 발견 단위 | Unit 5 처방 후보 |
|---|---|---|---|
| **R1** | DG-5F vector retargeting magnitude underdetermined — 풀 fist 만들기 어려울 수 있음 | U1 | mimic_mid/tip 비율 상향 (0.6→1.2), scaling_factor 조정, DexPilot 전환 |
| **R2** | WebXR ↔ UR10e base frame 좌표 align 미적용 — Quest 3 floor-frame 그대로 IK | U4 | run_teleop_ur10e.py main loop 의 target wrist 에 offset/rotation 추가 |
| **R3** | DG-5F pinky `rj_dg_5_2` underdetermined (외전+굴곡 둘 다 fingertip 영향) | U1 | 실 hand 에서 일관된 자세로 less ambiguous 예상 — 측정 후 결정 |
| **R4** | UR10e IK rotation err 평균 3.29° | U2 | rotation cost weight 5 (현재 1) 로 상향 |
| **R5** | DG-5F URDF mesh 12MB git commit — repo size 증가 | U1 | 큰 부담 아님. 향후 Git LFS 검토 |

### 4.2 향후 위험

- **DDS multicast 동작 불확실성**: 양 docker `--network=host` 가정. host firewall / non-host 변화 시 unicast peers 설정 필요 (sim 보고서 §10).
- **vuer 0.0.60 + Quest 3 호환성**: Phase 1 Week 3 의 ws-race issue 가 monkey-patch 로 해결. 다른 Quest 3 firmware update 시 재발 가능.
- **dex_retargeting fork 필요성**: vector retargeting 한계가 너무 크면 DG-5F 전용 retargeting layer 신규 작성 (현재 dex_retargeting 라이브러리는 surface-level wrapper).

---

## 5. 작업 상세 자료

### 5.1 파일 트리 (Week 4 추가/수정만)

```
src/xr_teleop/
├── assets/                                  # ← 신규: dg5f_hand + ur10e_dg5f (gitignored xr_teleoperate/ 회피)
│   ├── dg5f_hand/
│   │   ├── dg5f_right.urdf
│   │   ├── dg5f_right.yml                   # dex_retargeting config
│   │   └── meshes/{visual,collision}/
│   └── ur10e_dg5f/
│       └── ur10e.urdf
├── docs/
│   ├── week4_report.md                      # 본 문서
│   └── week4/
│       ├── README.md
│       ├── INTERIM_TEST_GUIDE.md            # 누적 검증 가이드
│       ├── day1_dg5f_retargeting_spike.md
│       ├── day2_ur10e_ik_spike.md
│       ├── day3_controllers_spike.md
│       ├── day4_integration_spike.md
│       └── day5_e2e_spike.md
└── scripts/
    ├── ur10e_arm_ik.py                      # U2
    ├── ur10e_arm_controller.py              # U3
    ├── dg5f_controller.py                   # U3
    ├── run_teleop_ur10e.py                  # U4
    ├── test_dg5f_retargeting.py             # U1
    ├── test_ur10e_ik.py                     # U2
    └── test_controllers_smoke.py            # U3
```

### 5.2 핵심 인터페이스 (sim ↔ xr_teleop)

| 채널 | 방향 | Type | Rate | UR10e+DG-5F 슬롯 |
|---|---|---|---|---|
| `rt/lowstate` | sim → xr | `LowState_` | ~97 Hz | motor_state[0:6].q/dq |
| `rt/lowcmd` | xr → sim | `LowCmd_` | 250 Hz | motor_cmd[0:6].q (mode/kp/kd sim 무시) |
| `rt/dg5f/state` | sim → xr | `HandState_` | ~50 Hz | motor_state[0:20].q |
| `rt/dg5f/cmd` | xr → sim | `HandCmd_` | 100 Hz | motor_cmd[0:20].q (finger-major) |
| ZMQ 55555 | sim → xr | JPEG | 30 Hz | head camera |
| ZMQ 55557 | sim → xr | JPEG | 30 Hz | right_wrist camera |
| WebRTC 60001 | sim → Quest 3 | h264 | 30 fps | head camera (vuer scene 표시) |
| WebRTC 60003 | sim → Quest 3 | h264 | 30 fps | right_wrist camera |

sim 보고서 §1.1 그대로.

---

## 6. 결론

Phase 2 Week 4 의 **코드 작업 (Unit 1-4) 모두 완료**. 본 docker Claude Code 가 자체 검증 가능한 모든 단위 테스트 PASS:
- DG-5F retargeting smoke ✅
- UR10e_ArmIK 100-pose round-trip ✅ (median 2.63 mm)
- Controllers smoke (26 assertions) ✅
- run_teleop_ur10e.py --help + sanity check ✅

**남은 단계: Unit 5 — 사용자가 sim docker + Quest 3 + xr_teleop docker 셋을 동시에 부팅해 E2E 측정**. Gate 4 통과 시 Week 5 (DG-5F retargeting fine-tuning + 좌표 align) 진입.

측정 절차 + 양식 + 알려진 issue 처방 4 개는 [day5_e2e_spike.md](week4/day5_e2e_spike.md) 에 정리. 사용자 측정 결과 회신 후 본 보고서 §2.1 의 U5 행 update + Gate 4 통과 여부 판정 + Week 5 plan 으로.
