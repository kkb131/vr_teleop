# Week 4 — UR10e + DG-5F xr_teleop 측 통합 (작업 단위 계획)

> Phase 2 Week 4. sim docker 측 `unitree_sim_isaaclab` fork가 `feat/ur10e-dg5f-sim` branch로 완성됨 ([sim_build_complete_report.md](../../../unitree_sim_isaaclab/custom/docs/sim_build_complete_report.md), commit `74aad24`). 본 docker(xr_teleop dev PC)에서 Quest 3 + WebXR 입력으로 IsaacSim UR10e+DG-5F sim과 teleop이 동작할 때까지 5개 작업 단위로 진행.

## 작업 우선순위 / 전제

- **Meta Quest 3 우선** (현재 본 PC에 USB-C 연결 중). Galaxy XR은 Quest 3 통과 후 별도 Week (7-8).
- **sim 인터페이스는 sim docker가 완성한 그대로 사용** (DDS topic + joint 순서 + init pose).
- upstream `xr_teleoperate`는 가능한 한 새 파일만 추가 (G1_29_ArmIK 등 기존 클래스 옆에 `UR10e_ArmIK` 신규).
- 각 단위 완료 시 `docs/week4/dayN_*_spike.md` + `docs/week4/INTERIM_TEST_GUIDE.md` 누적 갱신.

## 단위별 분해

| Unit | 작업 | 핵심 산출 | 진입 조건 |
|---|---|---|---|
| **U1** | DG-5F dex_retargeting config 작성 + URDF 통합 + 단위 테스트 | `dg5f_right.yml`, `assets/dg5f/dg5f_right.urdf`, `day1_dg5f_retargeting_spike.md` | sim 보고서 §1.3 joint sign convention 정확 반영 |
| **U2** | UR10e_ArmIK (Pinocchio + CasADi single-arm) | `robot_arm_ik.py`에 클래스 추가, `day2_ur10e_ik_spike.md` | G1_29_ArmIK 패턴 복제, init pose seed, base z=1m offset |
| **U3** | UR10e_ArmController + DG5F_Controller (DDS publisher) | `robot_arm.py`, `robot_hand_dg5f.py`, `day3_controllers_spike.md` | rt/lowcmd[0:6] + rt/dg5f/cmd[0:20] |
| **U4** | teleop_hand_and_arm.py + run_teleop.py 분기 | `--arm ur10e --ee dg5f` 통과, `day4_integration_spike.md` | single-arm 처리, recording slicing |
| **U5** | Quest 3 end-to-end smoke + Gate 4 측정 + week4 report | adb reverse 절차, `day5_e2e_spike.md`, `week4_report.md` | Quest 3 → vuer → IsaacSim wrist_3_link 추종 |

## 공통 가정 / 환경

- conda env: `tv` (Python 3.10 + pinocchio 3.1.0 + numpy 1.26.4 + dex_retargeting 설치됨, `INSTALL_DEX_RETARGETING=1 bash scripts/install.sh` 통과 가정)
- DDS env: `source scripts/dds_env.sh` (RMW=cyclonedds, ROS_DOMAIN_ID=1)
- sim 부팅 (다른 docker): `./custom/scripts/run_ur10e_dg5f.sh --headless`
- Quest 3 USB-C 연결 + `adb reverse tcp:8012/60001/60003 tcp:8012/60001/60003`

## sim 보고서에서 가져온 핵심 사실 (잊지 말 것)

- UR10e joint 순서 (DDS index 0-5): `shoulder_pan_joint, shoulder_lift_joint, elbow_joint, wrist_1_joint, wrist_2_joint, wrist_3_joint`
- UR10e init pose: `[0.0, -1.57, 1.57, -1.57, -1.57, 0.0]` (T/ready 자세)
- UR10e EE: **`wrist_3_link`** (USD `--merge-joints`로 tool0/flange/dg_palm 흡수)
- UR10e base: AMR pedestal 위 — world z=1.0m offset
- DG-5F 20 joint finger-major (thumb=0..3, index=4..7, middle=8..11, ring=12..15, pinky=16..19)
- **thumb `rj_dg_1_2` (DDS index 1) flexion 방향 NEGATIVE** (URDF lower=-π, upper=0.0)
- ZMQ camera: head=55555, right_wrist=55557 (left_wrist=55556 disabled)
- WebRTC: 60001 head / 60003 right_wrist (60002 disabled)
- IMU 데이터 없음 (모두 0)
- `kp/kd` 무시 — sim 측 ImplicitActuatorCfg가 자체 PD 사용
- init pose hold 보장 — xr_teleop이 첫 명령 보낼 때까지 sim drift < 0.02 rad

## 단위 진행 표

| Unit | 시작일 | 완료일 | 상태 |
|---|---|---|---|
| U1 | 2026-05-11 | — | 진행 중 |
| U2 | — | — | 대기 |
| U3 | — | — | 대기 |
| U4 | — | — | 대기 |
| U5 | — | — | 대기 |
