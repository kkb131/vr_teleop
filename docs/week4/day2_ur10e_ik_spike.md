# Day 2 spike — UR10e_ArmIK (Pinocchio + CasADi single-arm)

> Unit 2 of [Week 4 plan](README.md). 작업: UR10e용 single-arm IK 솔버 신규 작성. G1_29_ArmIK 패턴 복제 + dual-arm 제거 + wrist_3_link EE.

## 결과 요약 (2026-05-11)

```
[test] UR10e_ArmIK unit test
  (a) build OK (URDF load + Pinocchio model)
  (b) FK init pose: translation [0.692, 0.174, 0.677], |p|=0.983 m
  (c) round-trip 100/100 reachable poses:
      position err   median=2.63 mm   max=5.87 mm
      rotation err   mean=3.29°       max=6.99°
      solve time     mean=1.8 ms      max=9.8 ms (30Hz 여유)
      fail rate (>1cm): 0/100
[test] ✅ ALL CHECKS PASSED
```

## 산출물

| 파일 | 역할 |
|---|---|
| [assets/ur10e_dg5f/ur10e.urdf](../../assets/ur10e_dg5f/ur10e.urdf) | UR10e URDF (`src/tamp_dev/.docker/assets/`에서 copy) |
| [scripts/ur10e_arm_ik.py](../../scripts/ur10e_arm_ik.py) | `UR10e_ArmIK` 클래스 — G1_29_ArmIK 패턴 |
| [scripts/test_ur10e_ik.py](../../scripts/test_ur10e_ik.py) | 단위 테스트 (build + FK + 100-trial round-trip) |

## 설계 결정

### 1. G1_29_ArmIK 시그니처 호환 유지

`solve_ik(left_wrist, right_wrist, current_q, current_dq)` 시그니처 유지 (teleop_hand_and_arm.py 변경 최소화). UR10e는 single-arm이므로:
- `left_wrist`는 **무시**
- `right_wrist`만 EE target으로 사용 (sim 보고서 §1.5: "우측 손 hand pose만 사용")
- `sol_q` 반환은 **6-vec** (G1은 14-vec)

upstream teleop_hand_and_arm.py가 sol_q를 `arm_ctrl.ctrl_dual_arm(sol_q, ...)`에 넘기므로, UR10e_ArmController도 6-vec 받도록 작성 (Unit 3 작업).

### 2. URDF load: `pin.buildModelFromUrdf` vs `RobotWrapper.BuildFromURDF`

G1은 `RobotWrapper.BuildFromURDF` 사용 — visual/collision mesh 로드. UR10e URDF의 mesh URI는 `package://ur_description/...` (ROS 패키지 경로). 본 docker엔 ur_description 패키지 없어서 mesh load fail. → **`pin.buildModelFromUrdf`** 사용: kinematic chain만 로드, mesh 무시.

영향: visualization (meshcat) 불가. 하지만 IK 자체는 kinematic만 필요 — 충분.

### 3. EE frame: `wrist_3_link` 직접 사용 (offset 0)

sim 보고서 §1.2: USD 변환 시 `--merge-joints`로 tool0 / flange / dg_palm 모두 wrist_3_link로 흡수. 따라서 wrist_3_link가 effective EE.

G1은 wrist_yaw_joint 위에 +0.05m offset의 `L_ee`/`R_ee` frame 신규 추가 (손바닥 중심). UR10e는 그 단계 생략 — `getFrameId("wrist_3_link")` 직접 사용.

### 4. Init pose seed

`UR10E_INIT_POSE = [0, -1.57, +1.57, -1.57, -1.57, 0]` (T/ready 자세). sim 보고서 §1.5 일치. IK seed로 매번 init pose 사용 (또는 caller의 current_q). regularization cost도 init pose 기준.

### 5. Joint locking 없음

G1은 dual-arm + dual-hand의 거대 humanoid 모델에서 leg/waist/finger 28개 joint를 lock. UR10e는 pure 6-DOF arm — lock 필요 없음. `buildReducedRobot` 단계 생략.

### 6. Cost weights — G1과 동일

| Cost | weight |
|---|---|
| translational | 50 |
| rotation | 1 |
| regularization (q - init_pose) | 0.02 |
| smooth (q - q_last) | 0.1 |

조정 가능. 단위 테스트에서 rotation err 평균 3.29°는 약간 큼. Quest 3 hand에서 wrist rotation 정밀도가 부족하면 rotation weight 5로 늘릴지 Unit 5에서 결정.

### 7. Base z=1m offset

sim 측 UR10e는 AMR pedestal 위 (world z=1m). 본 IK 클래스는 **robot base frame** 기준으로 풀이 — base 위치 무관. 외부(teleop loop)가 Quest 3 wrist pose를 robot base frame으로 변환할 때 z offset 처리. Unit 4 작업.

## 단위 테스트 구조

```bash
conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_ur10e_ik.py
```

| 검증 | 내용 |
|---|---|
| (a) build | URDF load + Pinocchio model + CasADi 심볼릭 build 성공 |
| (b) FK | init pose 에서 wrist_3_link 위치가 UR10e 기하 reach 범위 (0.2 ~ 1.5m) |
| (c) Round-trip | random q (init ± 0.5 rad) → FK target → IK → FK 회수, 1cm 이내 |

## 시행착오

### 시행착오 1: URDF mesh URI (`package://ur_description/...`)

`pin.RobotWrapper.BuildFromURDF`가 mesh 로드 시도 → `ur_description` 패키지 없어 fail.

**해결**: `pin.buildModelFromUrdf` (model only, mesh 무시). Visualization은 불가하지만 IK엔 충분.

### 시행착오 없음 (추가 사항)

UR10e는 G1보다 훨씬 단순한 robot — 6-DOF pure arm. Joint locking 불필요, EE frame 신규 추가 불필요, dual-arm cost 단순화. 첫 시도에 IK convergence 100%.

## 성능

- **Build time**: 0.00s (URDF + CasADi symbolic) — G1 10s+ 대비 매우 빠름 (모델 작음)
- **Solve time**: mean 1.8ms, max 9.8ms — **30Hz teleop loop의 1/3 시간만 차지**

## 다음 단계

✅ Unit 2 완료. Unit 3 (UR10e_ArmController + DG5F_Controller) 진입.

**Unit 3에서 처리할 항목**:
- `UR10e_ArmController`: `rt/lowcmd.motor_cmd[0:6].q` publisher
- `DG5F_Controller`: `rt/dg5f/cmd.motor_cmd[0:20].q` publisher (Dex3_1_Controller 패턴, single-hand)
- DG5F_Controller가 retargeting 6 joint → 20 joint vector 확장 ([Day 1 spike](day1_dg5f_retargeting_spike.md) §확장 규칙)

**Unit 5 (sim test)에서 재검증할 항목**:
- IK rotation err (현재 3.29° 평균) — Quest 3 hand wrist rotation 정밀도와 비교
- Init pose seed 일관성 (sim 측 init pose와 align)
- z=1m base offset 처리 — Unit 4의 teleop entry에서
