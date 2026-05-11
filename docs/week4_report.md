# Week 4 개발 결과 보고서 — UR10e + Tesollo DG-5F 통합 (Gate 4 통과)

**프로젝트**: xr_teleoperate 기반 Galaxy XR + UR10e + DG-5F 원격조종 시스템
**기간**: Phase 2, Week 4 (2026-05-06 ~ 05-11)
**대상 헤드셋**: Meta Quest 3 (본 PC USB-C 검증 완료) / Samsung Galaxy XR (entry 작성 — 실측 미진행)
**목적**: Phase 1 G1+Dex3 sim 인프라를 **UR10e (6-DOF) + DG-5F (5-finger, 20-joint)** sim 으로 교체 + Quest 3 hand → IsaacSim 전 파이프라인 통과 (Gate 4)

---

## 1. 금주 목표

12주 개발 계획의 **Phase 2 - Week 4**. Path B (sim docker fork → 통합) 첫 주.

- sim docker (별도 docker, `unitree_sim_isaaclab` fork `feat/ur10e-dg5f-sim`) 가 Week 3 마지막에 완성 (commit `74aad24`).
- 본 docker (xr_teleop dev PC) 측 5 개 작업 단위 (U1–U5) 진행
- 사용자 실측 → 3 차 처방 적용 (U5+, U5++) → Gate 4 통과
- Galaxy XR 변형 entry 추가 (실측 미진행)

> Gate 4 통과 시 → Week 5 (Galaxy XR 검증 + recording infrastructure)
> Gate 4 실패 시 → 분기 처방

---

## 2. 핵심 결과 요약

### 2.1 단위별 결과

| Unit | 작업 | 검증 결과 | commit |
|---|---|---|---|
| **U1** | DG-5F dex_retargeting config (vector type → DexPilot) + URDF (12MB) + 단위 테스트 | ✅ PASS | `acb6996`, `02199d7` |
| **U2** | UR10e_ArmIK (Pinocchio + CasADi single-arm) | ✅ 100-pose round-trip median 2.63mm, solve 1.8ms | `fbd218f` |
| **U3** | UR10e_ArmController + DG5F_Controller (DDS publisher) | ✅ smoke 26 assertions | `fa29ffa`, `67c210a` |
| **U4** | `run_teleop_ur10e.py` (Quest 3 + vuer) | ✅ --help + sanity 통과 | `c18cf51` |
| **U5** | Quest 3 E2E + Gate 4 | ✅ **사용자 visual 확인 통과** | (다음 표) |
| **U5+** | Relative motion 캘리브레이션 + p/c/r/q 키 + `--scale` | ✅ | `60ec373` |
| **U5++** | DG-5F wrist-local + palm-aligned frame 변환 | ✅ yaw rotation diff=0 | `7cd3c3d` |
| **U6** | Galaxy XR ws bridge variant (`run_teleop_ur10e_ws.py`) | ✅ smoke PASS, 실측 대기 | `26d0a70` |

### 2.2 Gate 4 통과 확인 (사용자 3차 실측)

> "지금 상태도 잘 움직인다(open hand, fist, thumb-index pinch)" — 사용자 확인 (2026-05-11, U5++ 처방 후)

| 항목 | 결과 |
|---|---|
| Quest 3 wrist pose → UR10e tool0 추종 | ✅ relative motion 으로 init pose 무관 동작 |
| Quest 3 손목 회전 → DG-5F robust | ✅ frame transform 으로 yaw 회전 무관 |
| **open hand → DG-5F 펴짐** | ✅ |
| **fist → DG-5F 굽음** | ✅ |
| **thumb-index pinch** | ✅ (DexPilot pair-distance cost) |

**Gate 4 PASS** (Quest 3 기준). Galaxy XR 본기 검증은 Week 5+ 로 이월.

### 2.3 신규 파일 (Week 4 총합)

```
src/xr_teleop/
├── assets/
│   ├── dg5f_hand/                      # 본 repo 분리 (xr_teleoperate/ gitignored 회피)
│   │   ├── dg5f_right.urdf             # 원본 DG-5F right hand URDF
│   │   ├── dg5f_right_retarget.urdf    # PIP/DIP lower=0 — retarget 전용
│   │   ├── dg5f_right.yml              # DexPilot config (scaling 1.2, explicit indices)
│   │   └── meshes/                     # 12 MB visual + collision
│   └── ur10e_dg5f/
│       └── ur10e.urdf                  # UR10e URDF
├── docs/
│   ├── week4_report.md                 # 본 문서
│   └── week4/
│       ├── README.md                   # 5 단위 분해 계획
│       ├── INTERIM_TEST_GUIDE.md       # 누적 검증 가이드
│       ├── day1_dg5f_retargeting_spike.md
│       ├── day2_ur10e_ik_spike.md
│       ├── day3_controllers_spike.md
│       ├── day4_integration_spike.md
│       └── day5_e2e_spike.md           # 3 차 실측 + U5+/U5++ 처방 기록
└── scripts/
    ├── ur10e_arm_ik.py                 # UR10e_ArmIK (Pinocchio + CasADi single-arm)
    ├── ur10e_arm_controller.py         # rt/lowcmd publisher
    ├── dg5f_controller.py              # rt/dg5f/cmd publisher + frame transform
    ├── run_teleop_ur10e.py             # Quest 3 entry (vuer 기반)
    ├── run_teleop_ur10e_ws.py          # Galaxy XR entry (ws bridge variant)
    ├── test_dg5f_retargeting.py        # U1 + U5++ yaw robustness
    ├── test_ur10e_ik.py                # U2 100-pose round-trip
    └── test_controllers_smoke.py       # U3 smoke
```

### 2.4 commit 이력

```
26d0a70  feat(week4): run_teleop_ur10e_ws.py — Galaxy XR ws bridge 변형 entry
7cd3c3d  fix(week4): U5++ — DG-5F wrist-local + palm-aligned frame 변환
02199d7  fix(week4): DG-5F DexPilot 전환 — fist 고정 문제 해결
67c210a  fix(week4): DG5F motor_cmd IndexError + pause/resume 키 추가
60ec373  feat(week4): U5+ — relative motion 캘리브레이션 (init pose 무관 teleop)
728eadc  docs(week4): Unit 5 E2E test 절차 + week4_report draft
c18cf51  feat(week4): Unit 4 — run_teleop_ur10e.py
fa29ffa  feat(week4): Unit 3 — UR10e_ArmController + DG5F_Controller
fbd218f  feat(week4): Unit 2 — UR10e_ArmIK
acb6996  feat(week4): Unit 1 — DG-5F dex_retargeting config + unit test
```

---

## 3. 수행 내역 (Time-series)

### 3.1 코드 작업 단계 (U1–U4)

[day1](week4/day1_dg5f_retargeting_spike.md) ~ [day4](week4/day4_integration_spike.md) spike 참조.

핵심 사실:
- **sim docker 인터페이스 100% 그대로 활용**: G1+Dex3 과 동일 DDS pattern (`rt/lowstate`, `rt/lowcmd`, ZMQ 55555-7, WebRTC 60001/60003) + DG-5F 신규 topic (`rt/dg5f/{cmd,state}`).
- **DG-5F joint 순서 (DDS index 0..19)**: thumb(0..3), index(4..7), middle(8..11), ring(12..15), pinky(16..19). Thumb `rj_dg_1_2` flexion **negative direction** (URDF lower=-π).
- **UR10e init pose**: 사용자 튜닝 (Week 4 중 두 차례 변경 — Week 5 sim 환경 정합성 보고 최종 결정 가능). **relative motion 처방으로 init pose 변경에도 코드 무영향**.
- upstream `teleop_hand_and_arm.py` 무수정 원칙 유지 — 별도 entry script (`run_teleop_ur10e.py`) 작성.

### 3.2 사용자 1차 실측 → U5+ relative motion (commit `60ec373`)

**보고**: UR10e 가 Quest 3 wrist pose 따라 움직이긴 하지만 **로봇 초기 위치와 핸드 초기 위치 불일치 → 이상한 자세**.

**처방**: init pose 와 무관한 **relative motion 캘리브레이션** — 매 실행 `r` 키 시점에 origin 캡처 후 delta 만 robot 에 전달.

```python
# 'r' 키 (sync 시작) or 'c' 키 (재캘리) or 'p' resume 시
origin_user_pose  = tele_data.right_wrist_pose.copy()
origin_robot_pose = arm_ik.forward_kinematics(current_q).homogeneous

# 매 frame
delta_p   = (curr_user[:3,3] - origin_user[:3,3]) * args.scale
R_delta   = curr_user[:3,:3] @ origin_user[:3,:3].T   # world-frame
target_pose[:3,3]  = origin_robot[:3,3] + delta_p
target_pose[:3,:3] = R_delta @ origin_robot[:3,:3]
```

키 매핑 (최종):

| 키 | 동작 |
|---|---|
| `r` | sync 시작 + 첫 origin 캡처 |
| `p` | pause/resume 토글 (resume 시 자동 recalibrate) — 손 옮길 때 권장 |
| `c` | 즉시 recalibrate (jump 가능) |
| `q` | quit |

`--scale 1.5` argparse — position scale factor (rotation 은 항상 1:1).

### 3.3 사용자 2차 실측 → DG-5F IndexError + DexPilot 전환 (commits `67c210a`, `02199d7`)

**보고**:
1. DG-5F IndexError (`msg.motor_cmd[7].mode` out of range)
2. DG-5F 가 손 펴진 상태에서도 **주먹 자세로 고정**

**진단**:
1. stock `unitree_hg.HandCmd_` motor_cmd 가 Dex3 기준 **7-slot** default. DG-5F 20 joint 인덱싱 시 fail. CycloneDDS `Sequence[MotorCmd_]` 는 가변 길이 → 매 publish 시 list 를 20 개로 reset 후 채움.
2. retarget_dev (`/workspaces/tamp_ws/src/retarget_dev/.../docs/dg5f_tuning.md`) 의 검증 처방:
   - URDF PIP/DIP joint `[-π/2, +π/2]` 음수 허용 → optimizer 가 cost 최소 해로 음수 사용 → 손등 꺾임 / fist-like
   - scaling_factor 1.0 → DG-5F 가 사람 손 ~1.2 배 큰데 underdetermined
   - vector type magnitude 부정확 → DexPilot pair-distance cost 필요

**처방**:
- [assets/dg5f_hand/dg5f_right_retarget.urdf](../assets/dg5f_hand/dg5f_right_retarget.urdf) 신규 — PIP/DIP 10 joint lower=0 (Thumb `rj_dg_1_2` `[-π, 0]` 유지)
- [assets/dg5f_hand/dg5f_right.yml](../assets/dg5f_hand/dg5f_right.yml): `type: DexPilot`, `wrist_link_name`, `finger_tip_link_names`, `scaling_factor: 1.2`
- [scripts/dg5f_controller.py](../scripts/dg5f_controller.py): DexPilot full-target 시 `expand_retarget_to_dg5f_20` 우회 (URDF 순서 = DDS index 순서)

### 3.4 사용자 3차 실측 → U5++ frame transform (commit `7cd3c3d`)

**보고**: scaling_factor 변경에 따라 DG-5F 동작 magnitude 변화 OK, 그러나 **자세 자체가 부정확** — 사용자 추론 "잘못된 손목 Pose 기준 dex-retargeting 동작" + `unitree_dex3.yml` 의 `target_link_human_indices_dexpilot` 분석 요청.

**3 Explore agent 병렬 조사 종합**:
1. `tv_wrapper.py:330-331` 의 `fast_mat_inv` 는 translation 만 arm-frame 정렬 — **wrist orientation rotate 안 함**. 손목 회전 시 hand_pos vector 가 회전 반영 못 함.
2. dex_retargeting vector cost 는 **magnitude only** (frame 무관) — input 이 같은 frame 이어야 정확. `wrist_link_name` 은 단순 origin link 후보.
3. retarget_dev 의 `apply_mano_transform()` 패턴 표준 — wrist-center + SVD palm-plane fit + operator2mano rotation. `manus_debug.md` 의 **fist→spread inversion 버그 90% 원인이 이 변환 누락** (12 배 개선 측정).
4. upstream 모든 5-finger hand yml (Inspire / BrainCo) 의 `target_link_human_indices_dexpilot` = WebXR 25-keypoint convention `[4, 9, 14, 19, 24]` fingertip — **MANO 21 이 아님**. xr_teleoperate 라이브러리 표준 = WebXR 25.

**처방**:
- [scripts/dg5f_controller.py](../scripts/dg5f_controller.py) 에 `_estimate_wrist_frame_webxr`, `webxr_to_wrist_local_mano`, `_OPERATOR2MANO_RIGHT` 신규
- `_control_process()` retarget 호출 직전 frame 변환 1 줄 추가
- yml 에 `target_link_human_indices_dexpilot` 명시 (Inspire 패턴, auto 결과와 같음 — explicit 안전)

**검증** (단위 테스트):
```
(d) yaw 90° rotation → 동일 wrist-local 출력   ||diff|| = 0.000000
(d) ref_value yaw rotation 무관                ||diff|| = 0.000000
```

**사용자 visual 확인 결과**: open hand / fist / thumb-index pinch 모두 정상 동작 — **Gate 4 PASS**.

### 3.5 Galaxy XR 변형 entry (commit `26d0a70`)

vuer 0.0.60 client React 가 Galaxy XR Chrome 에서 immersive 진입 후 publish freeze 되는 문제로, `run_teleop_ws.py` 의 BridgePoseStore monkey-patch 패턴 적용:

- 세 namespace 동시 monkey-patch (`televuer.televuer.TeleVuer`, `tv_wrapper.TeleVuer`, `televuer.TeleVuer`) → `BridgePoseStore` 가 자체 ws server (port 8013) 가동
- `TeleVuerWrapper(...)` 가 patched 상태로 instantiate 됨 → interface 100% mimic
- 나머지 logic (UR10e_ArmIK, DG5F_Controller, relative motion, frame transform, r/p/c/q, `--scale`) 모두 동일

Smoke OK (`--help`, state transition, BridgePoseStore 로드). 실제 Galaxy XR 본기 + sim docker 연결 검증은 사용자 측정 대기.

---

## 4. 핵심 인터페이스 (sim ↔ xr_teleop) — 최종

| 채널 | 방향 | Type | Rate | UR10e+DG-5F 슬롯 |
|---|---|---|---|---|
| `rt/lowstate` | sim → xr | `LowState_` | ~97 Hz | motor_state[0:6].q/dq (UR10e 6 joint) |
| `rt/lowcmd` | xr → sim | `LowCmd_` | 250 Hz | motor_cmd[0:6].q (kp/kd sim 무시) |
| `rt/dg5f/state` | sim → xr | `HandState_` | ~50 Hz | motor_state[0:20].q (DG-5F 20 joint) |
| `rt/dg5f/cmd` | xr → sim | `HandCmd_` | 100 Hz | motor_cmd[0:20].q (finger-major, **20-slot 동적 확장**) |
| ZMQ 55555 | sim → xr | JPEG | 30 Hz | head camera |
| ZMQ 55557 | sim → xr | JPEG | 30 Hz | right_wrist camera |
| WebRTC 60001 / 60003 | sim → XR | h264 | 30 fps | head / right_wrist (vuer scene 표시) |
| ws bridge 8013 | XR → xr | JSON | 30 Hz | Galaxy XR hand pose stream (vuer 우회) |

DexPilot indices (DG-5F retargeting, 명시 / auto 둘 다 동일):
```
origins: [9, 14, 19, 24, 14, 19, 24, 19, 24, 24,  0,  0,  0,  0,  0]
tasks:   [4,  4,  4,  4,  9,  9,  9, 14, 14, 19,  4,  9, 14, 19, 24]
```

---

## 5. 이슈 및 리스크 (현 상태)

### 5.1 해결됨 (Week 4 내)

| ID | 증상 | 처방 | commit |
|---|---|---|---|
| R1 | UR10e 가 init pose 와 hand 위치 불일치 시 이상한 자세 | Relative motion + r/p/c/q 키 + `--scale` | `60ec373` |
| R2 | DG-5F IndexError (motor_cmd 7-slot) | CycloneDDS Sequence 가변 길이 — 20-slot 동적 확장 | `67c210a` |
| R3 | DG-5F 손 펴진 상태에서 fist 고정 | DexPilot 전환 + retarget URDF (PIP/DIP lower=0) + scaling 1.2 | `02199d7` |
| R4 | DG-5F 자세 부정확 (사용자 손목 회전 시) | WebXR wrist-local + palm-aligned frame 변환 | `7cd3c3d` |

### 5.2 미해결 / 이월

| ID | 증상 / 미확인 | 우선순위 | 처리 시점 |
|---|---|---|---|
| O1 | Galaxy XR 본기 + ws bridge entry 실측 미진행 | **High** | Week 5 초 |
| O2 | DexPilot convention (mediapipe vs manus) 결정 미확정 — fist↔spread inversion 시 row 1 sign flip 필요 | Medium | Week 5 visual 확인 |
| O3 | UR10e workspace boundary — relative motion 의 sum of deltas 가 reach 밖 도달 시 IK fail handling | Medium | Week 5 또는 Phase 3 |
| O4 | sim 측 wrist 카메라 (60003) 가 vuer scene 안 표시 — head 만 (Phase 1 기록) | Low | Week 9 멀티카메라 |
| O5 | UR10e init pose `[0.0, -1.18, 2.06, -0.88, 1.50, 0.0]` 의 sim 환경 정합성 (사용자 튜닝 중) | Low | Week 5+ visual |

### 5.3 향후 위험

- **DDS multicast 안정성**: `--network=host` 가정. 다른 host 운용 시 unicast peers 필요.
- **dex_retargeting fork 필요성**: 현재 OK 이나 향후 정밀도 부족 시 자체 retargeting layer.
- **Real robot 진입 시 DDS → ur_rtde bridge**: Phase 3 (Week 7+) 작업.

---

## 6. 결론

**Phase 2 Week 4 의 Gate 4 통과** (Quest 3 기준):
- Quest 3 hand → IsaacSim UR10e + DG-5F teleop 전 파이프라인 정상 동작
- DG-5F 손가락 자세 (open / fist / pinch) visual 확인 — 사용자 확인 (2026-05-11)

3 차에 걸친 사용자 실측 피드백을 통해 처방 검증 완료. 검증 자료 (retarget_dev / unitree upstream / dex_retargeting 라이브러리 내부) 기반 정확한 원인 진단 → 검증된 패턴 적용 → 실측 통과.

**남은 Week 4 항목**: Galaxy XR ws bridge entry 실측 (사용자 측정 대기).
**다음 단계**: Week 5 진입 — 전략은 [week5_strategy.md](week5_strategy.md) 참조.
