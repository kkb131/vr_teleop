# Day 4 spike — teleop entry 통합 (run_teleop_ur10e.py)

> Unit 4 of [Week 4 plan](README.md). 작업: Unit 1-3 의 retargeting / IK / controller 를 묶어 **Quest 3 → IsaacSim sim teleop** 의 main entry 작성.

## 결과 요약 (2026-05-11)

```
[smoke] run_teleop_ur10e.py --help → argparse + import path OK
[smoke] _sanity_check 통과 (conda env tv, pinocchio.casadi, dex_retargeting)
```

DDS / televuer / ImageClient 실 부팅은 sim docker 필요 — Unit 5 e2e 단계.

## 산출물

| 파일 | 역할 |
|---|---|
| [scripts/run_teleop_ur10e.py](../../scripts/run_teleop_ur10e.py) | UR10e + DG-5F 전용 teleop entry. upstream 무수정 |

## 설계 결정

### 1. 새 entry script (Option B) — upstream 무수정

세 옵션 비교:

| Option | upstream 수정 | 장점 | 단점 |
|---|---|---|---|
| A. upstream 직접 patch | 큼 | argparse 흐름 단일 | xr_teleoperate/ gitignored, upstream update 시 lost |
| **B. 새 entry script** | **0** | self-contained, upstream pristine | main 로직 일부 복제 (~250 lines) |
| C. monkey-patch argparse | 0 | 단일 entry | argparse choices monkey-patch awkward |

**Option B 선택**: run_teleop.py 의 "upstream 무수정" 철학 유지. main 로직 복제는 비용 작음.

### 2. run_teleop.py 와의 차이

| 측면 | run_teleop.py (G1+Dex3) | run_teleop_ur10e.py |
|---|---|---|
| upstream main | runpy.run_path로 위임 | upstream main 의 핵심 로직 직접 복제 |
| arm/ee 분기 | upstream argparse `--arm G1_29 --ee dex3` | 본 entry 가 직접 UR10e_ArmIK + DG5F_Controller import |
| dual-arm 처리 | upstream 가 dual-arm 14-vec | single-arm 6-vec, `dummy_left = np.eye(4)` |
| 키 처리 | upstream의 on_press 사용 | 본 entry 의 on_press (`r`/`q` 만, `s` record 생략) |
| record | upstream의 EpisodeWriter | 일단 skip (Week 5+ 추가) |

### 3. main loop 단순화

upstream teleop_hand_and_arm.py main loop는 record / IPC / dual-arm slicing 등 복잡. UR10e+DG-5F entry는 핵심 5 step만:

```
1. img_client.get_head_frame() + tv_wrapper.render_to_xr (필요 시)
2. tele_data = tv_wrapper.get_tele_data()
3. right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()
   ↳ DG5F_Controller 자식 process 가 retargeting + publish
4. current_q = arm_ctrl.get_current_dual_arm_q()
5. sol_q = arm_ik.solve_ik(np.eye(4), tele_data.right_wrist_pose, current_q)
   arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)
6. sleep to maintain --frequency (default 30Hz)
```

### 4. monkey-patches 재사용

run_teleop.py 의 5 patches 중 본 entry 에 필요한 2 개만 적용:
- `_apply_http_monkey_patch` — vuer cert=None (USB-only adb reverse cert 신뢰 우회)
- `_patch_image_spawn_retry` — Quest 3 / Galaxy XR Chrome ws-race 회복

`_ensure_sim_defaults` (--img-server-ip localhost) 는 본 entry 의 argparse default 가 `localhost` 이라 monkey-patch 불필요.

`_sanity_check` (conda env tv + casadi + dex_retargeting) 그대로 적용.

`cwd 보정` 은 본 entry 가 절대 경로 URDF 사용하므로 불필요.

### 5. sys.path 처리

본 entry 는 다음 3 경로 추가:
```python
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "xr_teleoperate"))
sys.path.insert(0, str(REPO_ROOT / "xr_teleoperate" / "teleop"))
```

- scripts/: ur10e_arm_ik, ur10e_arm_controller, dg5f_controller
- xr_teleoperate/: televuer, dex_retargeting (editable install)
- xr_teleoperate/teleop/: teleimager (image_client)

### 6. DG-5F single-hand: dummy left

upstream teleop_hand_and_arm.py 는 `tele_data.left_hand_pos` / `right_hand_pos` 둘 다 사용 (dual hand). UR10e+DG-5F 는 single right hand 만 — `right_hand_pos_array` 만 DG5F_Controller 에 전달, left 는 무시.

`tele_data.left_wrist_pose` 도 무시 (`dummy_left = np.eye(4)` 를 IK 에 넘김. UR10e_ArmIK 내부에서 left 무시).

### 7. shutdown 순서 (Ctrl+C, q 키)

```
1. arm_ctrl.ctrl_dual_arm_go_home()    # UR10e init pose 로
2. stop_listening()                    # sshkeyboard
3. img_client.close()                  # ZMQ socket
4. tv_wrapper.close()                  # vuer Process terminate
```

DG5F_Controller 의 자식 process 는 daemon=True 이므로 메인 process 종료 시 자동 정리.

## 알려진 한계 (Unit 5에서 검증)

### 한계 1: WebXR ↔ UR10e base frame 좌표 align

`tele_data.right_wrist_pose` 는 Quest 3 의 헤드셋 floor-frame 기준 (보통 사용자가 서 있는 위치 floor). UR10e 의 IK 는 robot base frame 기준 — sim 측 base 는 world z=1m AMR pedestal 위 (sim 보고서 §4.2).

**현재 entry 는 좌표 변환 미적용**: `tele_data.right_wrist_pose` 그대로 IK 에 전달. 사용자가 Quest 3 에서 손을 위로 들어도 UR10e 가 floor-frame 그대로 받으면 reach 범위 밖일 수 있음.

**Unit 5 에서 처리**:
- Quest 3 wrist position 에 offset 추가 (예: z += 0.8, x += 0.4 — 사용자 어깨 위치 → UR10e base 부근)
- 회전: Quest 3 quaternion 을 UR10e base 회전으로 변환
- 또는 user calibration step (사용자가 "neutral" 자세 잡고 그 시점을 origin 으로)

### 한계 2: DG-5F retargeting 정확도 (Unit 1 에서 식별)

Unit 1 spike 한계 — vector retargeting magnitude underdetermined. 실제 Quest 3 hand 로 굽힘 정도 확인 필요.

### 한계 3: WebXR vs DG-5F palm frame (Unit 1 한계)

DG-5F palm frame +z = finger direction. WebXR convention 과 다를 수 있어 사실상 회전 매트릭스 필요. Unit 5 에서 결정.

### 한계 4: keyboard input — sshkeyboard 안 동작 시

sshkeyboard 가 본 docker 의 stdin 에서 `r`/`q` 받음. tmux / IPC / non-interactive 환경에선 안 동작 — Unit 5 에서 IPC server 또는 다른 mechanism 검토.

## 사용 절차 (Unit 5 e2e 에서)

```bash
# Terminal 1: sim docker
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
./custom/scripts/run_ur10e_dg5f.sh --headless

# Terminal 2: xr_teleop docker
conda activate tv && source scripts/dds_env.sh
unset PYTHONPATH
# Quest 3 USB-C 연결 후:
adb reverse tcp:8012 tcp:8012
adb reverse tcp:60001 tcp:60001
adb reverse tcp:60003 tcp:60003
python scripts/run_teleop_ur10e.py
```

Quest 3 Chrome 으로 `https://localhost:60001` / `60003` 한 번씩 cert 신뢰 후, `http://localhost:8012` 접속 → Enter VR → 손 들이밀기 → Terminal 2 에서 `r` 키.

## 다음 단계

✅ Unit 4 완료. **Unit 5 (Quest 3 E2E + Gate 4 측정)** 진입.

Unit 5에서 처리할 항목:
- sim docker 부팅 + xr_teleop side 부팅 + Quest 3 연결
- 좌표 align 시도 (한계 1)
- 30초 hand tracking 측정 (lost frames, NaN, jitter)
- UR10e tool0 추종 정확도 (10cm 목표)
- DG-5F 손가락 굽힘 visual 확인
- week4_report.md 작성 (week1-3 포맷)
