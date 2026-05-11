# Day 3 spike — UR10e_ArmController + DG5F_Controller (DDS publisher)

> Unit 3 of [Week 4 plan](README.md). 작업: sim docker 의 `rt/lowcmd`, `rt/lowstate` (UR10e), `rt/dg5f/cmd`, `rt/dg5f/state` (DG-5F) 와 통신하는 controller 클래스 신규 작성.

## 결과 요약 (2026-05-11)

```
[smoke] Unit 3 controllers smoke test  ✅ ALL CHECKS PASSED
  (a) import OK
  (b) constants: UR10E_Num_Motors=6, DG5F_Num_Motors=20, topics 일치
  (c) expand_retarget_to_dg5f_20: thumb negative + finger 외전 fixed + mimic 0.6/0.4 검증
```

DDS instantiate / sim 연결 정확도는 Unit 5 e2e 에서.

## 산출물

| 파일 | 역할 |
|---|---|
| [scripts/ur10e_arm_controller.py](../../scripts/ur10e_arm_controller.py) | `UR10e_ArmController` — `rt/lowcmd` 6-motor publisher + `rt/lowstate` subscriber |
| [scripts/dg5f_controller.py](../../scripts/dg5f_controller.py) | `DG5F_Controller` + `expand_retarget_to_dg5f_20` — single-hand retargeting + 20-joint `rt/dg5f/cmd` publisher |
| [scripts/test_controllers_smoke.py](../../scripts/test_controllers_smoke.py) | import + constants + expansion 규칙 검증 (sim 없이 동작) |

## 설계 결정

### 1. UR10e_ArmController — G1 시그니처 호환

- `ctrl_dual_arm(q_target, tauff_target)`: 6-vec 또는 14-vec 입력 받음. 14-vec 시 right side 6개 (`q[7:13]`) 추출. UR10e_ArmIK가 6-vec sol_q 반환하므로 normally 6-vec.
- `get_current_dual_arm_q()`: 6-vec. `motor_state[0:6].q`.
- `ctrl_dual_arm_go_home()`: UR10e init pose `[0, -1.57, +1.57, -1.57, -1.57, 0]`로 (G1의 zeros와 다름).
- `speed_gradual_max(t)`: 시작 시 ramp-up.

### 2. LowCmd_ 35-motor slot 처리

`unitree_hg.LowCmd_`는 35 motor slot. UR10e는 0..5만 사용:
- motor_cmd[0..5]: mode=1, kp=80, kd=3, q=target_q
- motor_cmd[6..34]: mode=0 (passive), 무시

sim 측은 motor_cmd[0:6] 만 읽음 (보고서 §1.1).

### 3. kp/kd 채움 (sim 무시 but 일관성)

sim 보고서 §4.7: "kp/kd 는 sim 이 무시. sim 자체 ImplicitActuatorCfg 사용." 그러나 일관성 위해 G1 default arm gains (`kp=80, kd=3`) 채워 보냄. 실 robot 단계 (Phase 3) 에서 조정.

### 4. CRC

sim 무시 (보고서 §1.1). G1 패턴 따라 그대로 계산하지만 verify 안 됨.

### 5. DG5F_Controller — single-hand only

Dex3_1_Controller는 left/right 둘 다 처리. DG-5F는 single hand (sim 보고서 §1.4) → DG5F_Controller가 `right_hand_array_in` 1개만 받음. left_hand 관련 코드 모두 제거.

### 6. 6 target joint → 20 joint 확장 (`expand_retarget_to_dg5f_20`)

retargeter는 6 target joint q를 반환 (Day 1 결정). DDS는 20 joint 필요. 확장 규칙 (Day 1 spike §확장 규칙):

| DDS index | 값 | 설명 |
|---|---|---|
| 0 | `rj_dg_1_1` (retarget) | thumb 외전 |
| 1 | `rj_dg_1_2` (retarget, **negative**) | thumb 굴곡 |
| 2 | `0.6 * DDS[1]` | thumb mid mimic |
| 3 | `0.4 * DDS[1]` | thumb tip mimic |
| 4, 8, 12, 16 | `0.0` | finger 외전 fixed (open) |
| 5, 9, 13, 17 | `rj_dg_{2..5}_2` (retarget) | finger 굴곡 |
| 6, 10, 14, 18 | `0.6 * 굴곡` | finger mid mimic |
| 7, 11, 15, 19 | `0.4 * 굴곡` | finger tip mimic |

mimic 비율 0.6 / 0.4는 human PIP/DIP 굽힘 비율 추정. **Unit 5 sim test 에서 시각 확인 후 조정**.

### 7. multiprocessing.Process로 retargeting + DDS publish 분리

Dex3 패턴 그대로. 메인 프로세스 부담 줄이고 retargeting 100Hz로 안정 publish.

```python
hand_control_process = Process(target=self._control_process, args=(...), daemon=True)
hand_control_process.start()
```

자식 프로세스는 shared `right_hand_array_in` (multiprocessing.Array) 로부터 25-joint hand keypoint 받음. teleop_hand_and_arm.py (Unit 4)가 매 loop마다 write.

### 8. retargeter 사용 패턴 (Day 1 spike 결과 그대로)

```python
ref_value = right_hand_data[indices[1, :]] - right_hand_data[indices[0, :]]
robot_qpos = self.right_retargeting.retarget(ref_value, fixed_qpos=fixed_qpos)
q_target_dict = {n: robot_qpos[idx] for n in target_joint_names}
q_20 = expand_retarget_to_dg5f_20(target_joint_names, q_target_dict)
```

## 시행착오

### 시행착오 1: DDS instantiate은 sim 없이 hang

`ChannelPublisher.Init()`은 sim 없이도 동작 (publisher만 만들고 client 안 기다림). 그러나 `lowstate_subscriber.Read()` loop의 첫 데이터 대기에서 hang. 단위 테스트에선 instantiate 자체를 skip — smoke test는 import + constants + expansion 규칙만 검증.

DDS 실 동작 검증은 Unit 5 sim test 단계에서.

### 시행착오 없음 (추가)

UR10e_ArmController 와 DG5F_Controller 모두 G1/Dex3 패턴 그대로 → 첫 시도 통과.

## 다음 단계

✅ Unit 3 완료. Unit 4 (teleop_hand_and_arm.py + run_teleop.py 분기) 진입.

**Unit 4에서 처리할 항목**:
- run_teleop.py 의 `_sanity_check()` 가 `dex_retargeting` 검사 후 통과하도록 ([scripts/run_teleop.py](../../scripts/run_teleop.py) 변경 최소화)
- teleop_hand_and_arm.py 의 `--arm ur10e --ee dg5f` 분기 추가:
  - arm_ik = UR10e_ArmIK()
  - arm_ctrl = UR10e_ArmController(simulation_mode=True)
  - hand_ctrl = DG5F_Controller(right_hand_pos_array, ...) — single-hand
  - left_wrist_pose 는 dummy (np.eye(4)) 또는 무시
  - record state slicing 6 joint (G1 의 7+7 대신)

upstream teleop_hand_and_arm.py 가 dual-arm 14-vec 가정으로 작성됐으므로 monkey-patch 또는 새 entry script 작성 검토 (Unit 4 spike 에서 결정).
