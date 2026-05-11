# Week 4 INTERIM_TEST_GUIDE — Quest 3 / sim 측 누적 검증

> Week 4 단위 작업이 한 단계씩 진행될 때마다 본 가이드를 갱신해, 현재까지의 작업물을 **누구나 처음부터 재현 가능**하도록 한다. 각 Unit 완료 시 §X에 절차 + 검증 명령 추가.

## 환경 사전 조건 (한번만)

### 본 docker (xr_teleop) 측

```bash
# conda env tv (Phase 1에서 만든 환경)
conda activate tv

# DDS + ROS 환경
source /workspaces/tamp_ws/src/xr_teleop/scripts/dds_env.sh   # RMW=cyclonedds, ROS_DOMAIN_ID=1

# PYTHONPATH 정리 (ROS Humble pinocchio 충돌 방지)
unset PYTHONPATH
```

### sim docker 측 (다른 docker)

```bash
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
git fetch && git checkout feat/ur10e-dg5f-sim && git pull
./custom/scripts/run_ur10e_dg5f.sh --headless    # 또는 viewport 모드
# 약 80초 후 'rt/lowstate' / 'rt/dg5f/state' publish 시작
```

### Quest 3 USB-C 연결 (xr_teleop 호스트)

```bash
# 본 docker가 동작하는 host에서:
adb devices            # Quest 3 인식 확인
adb reverse tcp:8012 tcp:8012     # vuer WebSocket
adb reverse tcp:60001 tcp:60001   # head camera WebRTC
adb reverse tcp:60003 tcp:60003   # right_wrist camera WebRTC (60002는 disabled)
```

---

## Unit 1: DG-5F retargeting (✅ 2026-05-11)

### 1.1 무엇이 추가됐나

- [xr_teleoperate/assets/dg5f_hand/](../../xr_teleoperate/assets/dg5f_hand/) — DG-5F right hand URDF + meshes
- [xr_teleoperate/assets/dg5f_hand/dg5f_right.yml](../../xr_teleoperate/assets/dg5f_hand/dg5f_right.yml) — dex_retargeting config
- [scripts/test_dg5f_retargeting.py](../../scripts/test_dg5f_retargeting.py) — 단위 테스트

### 1.2 검증 명령

```bash
conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_dg5f_retargeting.py
```

### 1.3 통과 기준

마지막 줄 `[test] ✅ ALL CHECKS PASSED` 확인. 세부:

```
(a) retarget 3 dummy poses succeeded (20-vec each)
(b) URDF limit 준수 — 6 target joint × 3 pose = 18 PASS
(c) round-trip max_err < 1.0 — 3 cases PASS (sign mismatch는 pinky underdetermined로 informational)
```

### 1.4 알려진 한계

- WebXR ↔ DG-5F palm frame 좌표 align 미반영 — Unit 5에서 실제 Quest 3 hand로 정확도 검증
- Vector retargeting magnitude underdetermined — 단단한 fist 만들기 어려울 수 있음. Sim 측 visual로 확인 후 필요 시 scaling 또는 DexPilot 전환

상세: [day1_dg5f_retargeting_spike.md](day1_dg5f_retargeting_spike.md) §4.

### 1.5 Unit 1 까지로는 sim teleop 불가

retargeting config만 있고 controller / IK / 통합이 없어 **실제 Quest 3 → sim 연결은 Unit 4 이후**. Unit 1 검증은 단위 테스트로 충분.

---

## Unit 2: UR10e_ArmIK (✅ 2026-05-11)

### 2.1 무엇이 추가됐나

- [assets/ur10e_dg5f/ur10e.urdf](../../assets/ur10e_dg5f/ur10e.urdf) — UR10e URDF (`src/tamp_dev/.docker/assets/`에서 copy)
- [scripts/ur10e_arm_ik.py](../../scripts/ur10e_arm_ik.py) — `UR10e_ArmIK` 클래스 (Pinocchio + CasADi single-arm, wrist_3_link EE)
- [scripts/test_ur10e_ik.py](../../scripts/test_ur10e_ik.py) — 100-trial round-trip 단위 테스트

### 2.2 검증 명령

```bash
conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_ur10e_ik.py
```

### 2.3 통과 기준

```
position err  median < 5 mm    (실측 2.63 mm)
solve time    mean   < 50 ms   (실측 1.8 ms — 30Hz 여유)
fail rate     < 5%              (실측 0/100)
```

상세: [day2_ur10e_ik_spike.md](day2_ur10e_ik_spike.md).

### 2.4 Unit 2까지로는 sim teleop 불가

IK 솔버만 작성. DDS publisher (Unit 3) + teleop entry (Unit 4) 추가 후 sim 연결 가능.

## Unit 3: UR10e_ArmController + DG5F_Controller (✅ 2026-05-11)

### 3.1 무엇이 추가됐나

- [scripts/ur10e_arm_controller.py](../../scripts/ur10e_arm_controller.py) — `UR10e_ArmController` (rt/lowcmd[0:6] publisher + rt/lowstate subscriber + 250Hz publish thread)
- [scripts/dg5f_controller.py](../../scripts/dg5f_controller.py) — `DG5F_Controller` (single-hand, rt/dg5f/cmd[0:20] publisher) + `expand_retarget_to_dg5f_20` (6 retarget joint → 20-vec with mimic 0.6/0.4)
- [scripts/test_controllers_smoke.py](../../scripts/test_controllers_smoke.py) — import + constants + expansion 규칙

### 3.2 검증 명령

```bash
conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_controllers_smoke.py
```

마지막 줄 `[smoke] ✅ ALL CHECKS PASSED` 확인.

### 3.3 통과 기준 (smoke level)

- UR10E_Num_Motors=6, DG5F_Num_Motors=20, topic 이름 sim 보고서 일치
- 6 input joint → 20 joint 확장 시 thumb negative + finger 외전 fixed + mimic 0.6/0.4 정확

DDS instantiate (sim 연결) 정확도는 Unit 5 e2e 단계에서. 상세: [day3_controllers_spike.md](day3_controllers_spike.md).

### 3.4 Unit 3까지로는 sim teleop 불가

teleop entry (Unit 4) 추가 후 sim 연결 가능. Controllers 는 instantiate 단계에서 DDS subscribe 대기로 hang — sim docker 부팅 후 동작.

## Unit 4: run_teleop_ur10e.py — teleop entry (✅ 2026-05-11)

### 4.1 무엇이 추가됐나

- [scripts/run_teleop_ur10e.py](../../scripts/run_teleop_ur10e.py) — UR10e + DG-5F 전용 teleop entry. upstream 무수정 (별도 entry script).

### 4.2 검증 명령

**Smoke (sim 없이)**:
```bash
conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/run_teleop_ur10e.py --help
```

argparse + import path + sanity check 통과 확인.

**실 연결 (Unit 5)**:
```bash
# Terminal 1 (sim docker):
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
./custom/scripts/run_ur10e_dg5f.sh --headless

# Terminal 2 (xr_teleop docker):
conda activate tv && source /workspaces/tamp_ws/src/xr_teleop/scripts/dds_env.sh && unset PYTHONPATH
# Quest 3 USB-C 연결 후:
adb reverse tcp:8012 tcp:8012
adb reverse tcp:60001 tcp:60001
adb reverse tcp:60003 tcp:60003
python /workspaces/tamp_ws/src/xr_teleop/scripts/run_teleop_ur10e.py
```

Quest 3:
1. Chrome 으로 `https://localhost:60001` 접속 → cert 신뢰 (head camera)
2. `https://localhost:60003` 접속 → cert 신뢰 (right_wrist camera)
3. `http://localhost:8012` 접속 → "Enter VR" → 손 들이밀기
4. Terminal 2 에서 `r` 키 → sync 시작

### 4.3 알려진 한계 (Unit 5 에서 처리)

- WebXR ↔ UR10e base frame 좌표 align (현재 미적용 — Quest 3 floor-frame 그대로 IK)
- DG-5F retargeting magnitude underdetermined (Unit 1 한계)

상세: [day4_integration_spike.md](day4_integration_spike.md) §"알려진 한계".

### 4.4 종료

Terminal 2 에서 `q` 키 또는 Ctrl+C. `arm_ctrl.ctrl_dual_arm_go_home()` 으로 init pose 복귀 후 종료.

## Unit 5: End-to-end Quest 3 → sim (대기)

(작업 진행 시 추가)

---

## 트러블슈팅 (모든 Unit 공통)

| 증상 | 원인 | 해결 |
|---|---|---|
| `Optimizer has N joints but non_target_qpos [] is given` | `retarget()` 두 번째 인자 `fixed_qpos` 누락 | `retarget(ref_value, fixed_qpos=np.zeros(N))` |
| `size of tensor a (X) must match (25)` | ref_value를 25-joint raw로 전달 | `ref = hand_kp[indices[1]] - hand_kp[indices[0]]` (vector 차이) 형식으로 |
| `pinocchio.casadi import 실패` | conda env tv 미활성 또는 ROS PYTHONPATH 가림 | `conda activate tv && unset PYTHONPATH` |
| Quest 3 vuer scene 빈 공간 | webrtc cert 신뢰 안 됨 또는 ws race | `https://localhost:60001` 한 번 접속 후 cert 신뢰. run_teleop.py가 retry monkey-patch 자동 적용 |
| sim 측 `rt/lowstate` 안 들어옴 | ROS_DOMAIN_ID 불일치 또는 multicast 막힘 | 양 docker `source dds_env.sh` 후 `ROS_DOMAIN_ID=1` 확인. `--network=host` 모드 확인 |
