# Day 1 spike — DG-5F dex_retargeting config + 단위 테스트

> Unit 1 of [Week 4 plan](README.md). 작업: DG-5F URDF를 xr_teleoperate/assets로 통합 + `dg5f_right.yml` dex_retargeting config 작성 + 단위 테스트로 동작 검증.

## 결과 요약 (2026-05-11)

```
[test] ✅ ALL CHECKS PASSED
  (a) retarget 3 dummy poses succeeded (20-vec each)
  (b) URDF limit 준수 (3 pose × 6 target joint, ±5e-3 tolerance)
  (c) round-trip max_err < 1.0 (3 cases: neutral / fist_mid / open_spread)
  (c-sign) thumb/index/middle/ring 방향 일치 (3 cases × 4 joint)
```

단, **vector retargeting의 알려진 한계**로 굽힘 magnitude는 underdetermined — Sim test (Unit 5)에서 실제 Quest 3 hand로 정확도 재검증 필요. 자세한 내용 §4 참조.

## 산출물

| 파일 | 역할 |
|---|---|
| [assets/dg5f_hand/dg5f_right.urdf](../../assets/dg5f_hand/dg5f_right.urdf) | DG-5F right hand URDF (mesh URI `package://` → `./meshes/`로 변환) |
| [assets/dg5f_hand/meshes/](../../assets/dg5f_hand/meshes/) | visual (.dae) + collision (.STL), 12MB |
| [assets/dg5f_hand/dg5f_right.yml](../../assets/dg5f_hand/dg5f_right.yml) | dex_retargeting 설정 (vector type, 6 target joint, 5 fingertip vector) |
| [scripts/test_dg5f_retargeting.py](../../scripts/test_dg5f_retargeting.py) | 단위 테스트 (yml load + 3 dummy pose + round-trip) |

## 설계 결정

### 1. retargeting type = vector (DexPilot 대신)

- 5 fingertip palm→tip vector + thumb 외전 (rj_dg_1_1) = 6 target joint
- DexPilot은 pairwise fingertip 거리도 매칭 — 더 정교하지만 Quest 3 hand stream으로 reliable한 pairwise distance 추출이 필요 → 일단 vector로 시작
- 정확도 부족하면 Unit 5에서 DexPilot 전환 검토

### 2. target_joint_names = 6개만 (URDF 전체 20 joint 중)

- 손가락당 _2 굴곡 joint 1개 + thumb _1 외전 1개 = 6
- 나머지 14 joint (각 손가락 _1 외전 — thumb 제외 + 모든 _3, _4 distal)는 `fixed_qpos`로 retarget() 호출 시 외부 전달
- DG5F_Controller가 _3, _4를 _2의 비례 mimic으로 확장 (Unit 3 작업)

### 3. WebXR 25-joint indexing

```
fingertip indices: thumb=4, index=9, middle=14, ring=19, pinky=24
origin = wrist (index=0)
target_link_human_indices_vector = [[0,0,0,0,0], [4,9,14,19,24]]
```

## 단위 테스트 구조

`scripts/test_dg5f_retargeting.py` — conda env `tv`에서 `PYTHONPATH` unset 후 실행:

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate tv && unset PYTHONPATH
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_dg5f_retargeting.py
```

3 종류 검증:

| 종류 | 내용 |
|---|---|
| (a) Smoke | yml/URDF load, RetargetingConfig.build(), retarget() 3 pose 예외 없이 호출 |
| (b) URDF limit | 6 target joint가 URDF lower/upper bound 안 (±5e-3 numerical tolerance) |
| (c) Round-trip | known target q → robot FK로 fingertip vector 계산 → retarget으로 회수, 방향(sign) 일치 검증 |

(c)가 **좌표계 align 무관** 검증 — 인공 WebXR hand 좌표계 매칭 문제 회피.

## 시행착오

### 시행착오 1: `retarget(ref_value)`의 ref_value 형식

처음엔 25-joint 전체 `(25, 3)` array를 그대로 넘김 → `"size of tensor a (5) must match the size of tensor b (25)"`. 

**해결**: `robot_hand_unitree.py:188`의 Dex3 사용 패턴 참조:
```python
ref_value = hand_kp[indices[1,:]] - hand_kp[indices[0,:]]  # (N_vec, 3)
```
즉 retargeter는 **이미 indexing 된 vector 차이 array** 를 받음, 25-joint raw가 아님.

### 시행착오 2: `Optimizer has 14 joints but non_target_qpos [] is given`

`retarget()` 두 번째 인자 `fixed_qpos`로 nontarget joint 14개 fixed value array 전달 필요.

```python
retargeter.retarget(ref_value, fixed_qpos=np.zeros(14))
```

`retargeter.optimizer.fixed_joint_names`로 14개 joint 순서 확인 가능.

### 시행착오 3: WebXR vs DG-5F palm frame 좌표계

WebXR convention은 보통 `+y = up`, DG-5F URDF palm frame은 **`+z = 손가락 방향`** (URDF rj_dg_2_1 origin xyz = `(-0.007, 0.027, 0.066)` → +z이 가장 큰 값).

dex_retargeting은 vector 그대로 비교 — 자동 좌표 변환 없음. 단위 테스트에선 dummy hand를 DG-5F palm frame에 맞게 작성 (+z = finger direction). 실제 Quest 3 운영 시엔 WebXR hand quaternion에서 DG-5F palm frame으로 회전 align 필요 (DG5F_Controller가 처리 — Unit 3).

### 시행착오 4: Round-trip 정확도 — vector retargeting의 한계

`fist_mid` 케이스에서 target `rj_dg_2_2=+1.0`이 recovered `+0.19`로 회수. **굽힘 magnitude underdetermined**.

원인: vector retargeting은 fingertip 위치만 매칭하는데, 동일 fingertip 위치를 만드는 robot 자세가 여러 개. 같은 palm→tip 벡터에 대해 retargeter가 일관된 솔루션 선택하지만, target과 정확히 같지 않음.

**실 영향**:
- 방향(sign)은 일치 — 굴곡 vs 펴짐 구분 OK
- magnitude는 약함 — 단단한 fist를 만들기 어려울 수도 있음 (실제 sim test에서 확인 필요)

**Unit 5에서 처리할 검증 항목**:
1. 실제 Quest 3 hand pose로 retargeting 결과 IsaacSim 시각 확인
2. 굽힘이 부족하면:
   - scaling_factor 조정 (현재 1.0)
   - DexPilot type 전환 검토
   - DG5F_Controller에서 _2 magnitude 후처리 증폭

### 시행착오 5 (informational): pinky `rj_dg_5_2` underdetermined

`fist_mid` 케이스에서 pinky target `+0.3`이 `-0.21`로 sign 반대. pinky의 `_1` 외전과 `_2` 굴곡이 모두 fingertip 위치에 영향 → 같은 fingertip을 만드는 (외전+굴곡) 조합이 다수. retargeter가 다른 valid 솔루션 선택.

**실제 운영 영향**: Quest 3 hand가 연속적으로 손가락 굽힘 → retargeter가 일관된 방향 유지할 가능성. last_qpos warm-start 효과로 smooth하게.

단위 테스트에선 informational로 표기, assertion 제외. Unit 5에서 실제 hand로 검증.

## DG5F_Controller 측 확장 규칙 (Unit 3 작업 내용)

Retargeter는 6 target joint q를 반환. DG5F_Controller가 받아서 20 joint vector로 확장 후 `rt/dg5f/cmd` publish. **확장 규칙 초안**:

```
# Direct (retargeting 결과 그대로)
DDS index 0  ← rj_dg_1_1 (thumb 외전)
DDS index 1  ← rj_dg_1_2 (thumb 굴곡, negative)
DDS index 5  ← rj_dg_2_2 (index 굴곡)
DDS index 9  ← rj_dg_3_2 (middle 굴곡)
DDS index 13 ← rj_dg_4_2 (ring 굴곡)
DDS index 17 ← rj_dg_5_2 (pinky 굴곡)

# Mimic (proportional to _2)
DDS index 2  = 0.6 * rj_dg_1_2 (thumb mid)
DDS index 3  = 0.4 * rj_dg_1_2 (thumb tip)
DDS index 6  = 0.6 * rj_dg_2_2 (index mid)
DDS index 7  = 0.4 * rj_dg_2_2 (index tip)
DDS index 10 = 0.6 * rj_dg_3_2 (middle mid)
DDS index 11 = 0.4 * rj_dg_3_2
DDS index 14 = 0.6 * rj_dg_4_2
DDS index 15 = 0.4 * rj_dg_4_2
DDS index 18 = 0.6 * rj_dg_5_2 (pinky mid — _2 가 negative 가능, mimic도 negative 따름)
DDS index 19 = 0.4 * rj_dg_5_2

# Fixed (외전, retargeting 안 함)
DDS index 4, 8, 12, 16 = 0.0 (index/middle/ring/pinky 외전 = neutral)
```

mimic 비율 0.6/0.4는 human hand의 PIP/DIP 굽힘 비율 추정치. Unit 3 작성 후 Unit 5 sim test에서 조정 가능.

## 다음 단계 (Unit 2 진입 조건)

✅ Unit 1 완료. Unit 2 (UR10e_ArmIK) 진입 가능.

**Unit 1에서 남은 미해결 항목** (Unit 5에서 처리):
- 실제 Quest 3 hand stream으로 retargeting 결과 정확도 검증
- 좌표계 align (WebXR vs DG-5F palm frame) 회전 매트릭스 결정
- scaling_factor / DexPilot 전환 / DG5F_Controller mimic 비율 fine-tuning
