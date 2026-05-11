# Day 5 spike — Quest 3 End-to-End teleop test (Gate 4)

> Unit 5 of [Week 4 plan](README.md). 최종 작업: Quest 3 hand → vuer → xr_teleop → DDS → IsaacSim UR10e+DG-5F 전 파이프라인 동작 확인 + Gate 4 통과 측정.

## 상태: 사용자 실측 대기 (2026-05-11)

본 docker (xr_teleop dev PC) 의 코드 작업 (Unit 1-4) 은 완료. 본 단계는 **사용자가 sim docker + xr_teleop docker + Quest 3 셋을 동시에 부팅**해 실측하는 단계.

본 docker Claude Code 는 sim docker 에 접근 불가 — Unit 5 deliverable 은 **테스트 절차 문서 + 측정 양식 + 사용자가 보고할 결과 template**.

### 2026-05-11 1차 실측 후 사용자 피드백 + 처방

사용자 실측 결과:
- ✅ Quest 3 wrist pose 값에 맞춰 UR10e 움직임
- ❌ **로봇 초기 위치와 핸드 초기 위치 불일치 → 이상한 자세로 시작**
- ❌ **DG5F_Controller IndexError**: `msg.motor_cmd[i].mode = 1` 에서 i=7 부터 out of range

사용자 결정:
- init pose 임시 `[2.40, -1.18, 2.06, -0.88, 2.24, 0.0]` 로 변경 (사용자가 [scripts/ur10e_arm_ik.py:37](../../scripts/ur10e_arm_ik.py#L37), [scripts/ur10e_arm_controller.py:37](../../scripts/ur10e_arm_controller.py#L37) 직접 수정). 향후 재변경 가능.
- **Relative motion 캘리브레이션** 추가 — init pose 와 무관하게 매번 sync 시작 시점에 origin 캡처해 delta 만 robot 에 전달.
- **Pause/resume** 키 추가 — 새 origin 캡처 워크플로우 안전화.

처방 적용 (Unit 5+ 작업):

(1) **Relative motion** ([scripts/run_teleop_ur10e.py](../../scripts/run_teleop_ur10e.py) main loop):
- `r` 키 sync 시작 / `c` 키 (즉시 재캘리) / `p` 키 (pause → resume 시 자동 재캘리) 시 origin 재캡처
- `--scale` argparse (default 1.0, position 만 — rotation 은 항상 1:1)
- 자세한 동작 §3.1.

(2) **DG-5F IndexError 수정** ([scripts/dg5f_controller.py:_ctrl_publish](../../scripts/dg5f_controller.py)):
- 원인: stock `unitree_hg.HandCmd_` 의 `motor_cmd` 가 **Dex3 기준 7-slot** default. DG-5F 20 joint 인덱싱 시 `IndexError: list index out of range`.
- 해결: CycloneDDS `Sequence[MotorCmd_]` 는 가변 길이 — 매 publish 시 `msg.motor_cmd = [unitree_hg_msg_dds__MotorCmd_() for _ in range(20)]` 로 list 교체 후 채움. sim docker 가 20-slot wire format 으로 받음.
- `_subscribe_hand_state` 도 `min(20, len(msg.motor_state))` guard 추가 (sim 측 state 길이 동적 대응).

자세한 동작은 §3.1 참조.

### 2026-05-11 2차 실측 후 사용자 피드백 + 처방 (DexPilot 전환)

사용자 2차 실측 (relative motion + IndexError fix 후):
- ✅ UR10e 가 Quest 3 wrist pose 따라 움직임
- ✅ UR init pose 사용자 튜닝 `[0.0, -1.18, 2.06, -0.88, 1.50, 0.0]`
- ❌ **DG-5F 가 전혀 움직이지 않고 주먹 자세로 고정** — 사용자 손 펴진 상태인데도

원인 진단 (`/workspaces/tamp_ws/src/retarget_dev/models/dex_retarget/docs/dg5f_tuning.md` 분석):

기존 retarget_dev 팀이 동일 증상을 검증된 처방으로 해결했음:
1. **URDF PIP/DIP joint limit 음수 영역 (`[-π/2, +π/2]`)** → optimizer 가 "방향만 맞추는" cost 최소 해로 음수 사용 → 손등 꺾임 / fist-like 자세
2. **scaling_factor 1.0** → DG-5F 가 사람 손보다 ~1.2배 큰데 1:1 매핑 → 구부정한 자세
3. **vector type 의 magnitude underdetermined** → DexPilot 으로 전환 시 fingertip pair-distance cost 추가로 정확

검증된 권장 설정 그대로 적용:

```yaml
# assets/dg5f_hand/dg5f_right.yml
right:
  type: DexPilot                    # vector → DexPilot (pair-distance cost)
  urdf_path: dg5f_hand/dg5f_right_retarget.urdf   # PIP/DIP lower=0
  wrist_link_name: "rl_dg_palm"
  finger_tip_link_names: [rl_dg_1_tip, ..., rl_dg_5_tip]
  scaling_factor: 1.2               # 사람 손 ~1.2배 확대
  low_pass_alpha: 0.2
```

추가 작업:
- [assets/dg5f_hand/dg5f_right_retarget.urdf](../../assets/dg5f_hand/dg5f_right_retarget.urdf) 신규 — PIP/DIP joint 10개의 lower limit `-π/2 → 0` (Thumb _1_2 `[-π,0]` 은 그대로). retarget_dev fork 후 mesh URI 만 `./meshes/` 로 patch.
- [scripts/dg5f_controller.py](../../scripts/dg5f_controller.py) 수정:
  - DexPilot type 시 `target_joint_names == 20` — `expand_retarget_to_dg5f_20` 우회.
  - URDF 등장 순서 == DDS index 순서 (rj_dg_1_1, ..., _5_4) — `robot_qpos[:20]` 그대로 사용.
  - vector type 백워드 호환 유지 (yml 변경 시 자동 분기).

**검증된 사실**:
- DexPilot 의 auto-generated `target_link_human_indices` 가 **WebXR 25-joint fingertip 인덱스 [4, 9, 14, 19, 24] 와 정확히 일치** (MANO 21-joint 가 아님). 좌표 변환 layer 불필요.
- 단위 테스트 (a) build + (b) URDF limit 모두 PASS. (c) round-trip 은 DexPilot pair-distance ref_value (2, 15) shape 이라 fingertip-only round-trip 불가 — sim test 에서 검증.
- 3 dummy pose 에 retargeter 가 다른 값 반환 (입력에 반응). **fist 고정 문제 해결 가능성 큼**.

Unit 5 재측정 항목 (DexPilot 전환 후):
- DG-5F 손가락 굽힘 visual 추종 (G4-10)
- 굽힘 magnitude (G4-11) — 1.2 scaling 충분한가
- thumb sign convention (G4-12)
- 손가락 vs 손 펴짐 정확도 (open hand → DG-5F 도 펴진 자세인가)

---

## 3.1 Relative motion 캘리브레이션 (Unit 5+ 추가)

### 작동 원리

`run_teleop_ur10e.py` main loop 안에서 매 frame:

```python
# 'r' 키 (sync 시작) 또는 'c' 키 (재캘리) 시
if RECALIBRATE:
    origin_user_pose  = tele_data.right_wrist_pose.copy()       # Quest 3 wrist (4,4)
    origin_robot_pose = arm_ik.forward_kinematics(current_q).homogeneous   # UR10e wrist_3_link (4,4)
    RECALIBRATE = False
    target_pose = origin_robot_pose   # 캘리 직후 jitter 회피
else:
    curr_user = tele_data.right_wrist_pose
    delta_p   = (curr_user[:3, 3] - origin_user_pose[:3, 3]) * args.scale
    R_delta   = curr_user[:3, :3] @ origin_user_pose[:3, :3].T   # world-frame rotation
    target_pose       = np.eye(4)
    target_pose[:3,3] = origin_robot_pose[:3, 3] + delta_p
    target_pose[:3,:3] = R_delta @ origin_robot_pose[:3, :3]

sol_q = arm_ik.solve_ik(np.eye(4), target_pose, current_q)
```

핵심 효과:
- **init pose 와 무관**: robot 의 init pose 가 어떤 값이든 origin_robot_pose 가 그것을 캡처. init pose 변경되어도 코드 수정 없이 동작.
- **사용자가 손을 그대로 두면 robot 도 origin 유지** (이상한 자세로 튀어가지 않음).
- **1:1 delta mapping** (default `--scale 1.0`): 사용자 손 10cm 움직이면 robot 도 10cm.
- **Rotation 은 항상 1:1**: world-frame rotation `R_delta = R_curr @ R_origin.T`. scale 안 함.

### 키 매핑

| 키 | 동작 |
|---|---|
| **r** | sync 시작 + **첫 origin 캡처** |
| **p** | **pause/resume 토글**. resume 시 자동 recalibrate. **권장 워크플로우** — 손을 새 위치로 옮기는 동안 robot 정지 |
| **c** | **즉시 recalibrate** (jump 가능) — pause 없이 현재 손 = 현재 robot 새 origin |
| **q** | stop / exit |

`p` 와 `c` 의 차이:
- **`p`** (pause/resume): 손 새 위치로 옮기는 동안 robot 정지 → resume 시 그 위치에서 새 origin. **안전** 워크플로우.
- **`c`** (immediate recal): 현재 시점에 즉시 origin 교체. 그 사이 손 이동이 큰 거리였다면 robot 이 **jump** 할 가능성. 빠른 미세조정용.

### 사용 시나리오

**기본 시작**:
1. sim 부팅 + xr_teleop 부팅 → Quest 3 Enter VR + 손 들기
2. 손이 사용자에게 편한 위치 (팔꿈치 약 90°) 에 놓은 상태에서 `r` 키 → sync 시작
3. 사용자가 손 움직이면 robot 이 같은 delta 만큼 움직임 (1:1, rotation 도 1:1)

**손이 어색해졌을 때 (안전 워크플로우)**:
1. `p` 키 → ⏸ pause (robot 정지, 손 자유 이동)
2. 손을 새 편한 위치로
3. `p` 키 다시 → ▶ resume + 자동 recalibrate (새 origin)
4. sync 재개

**빠른 미세조정 (jump 허용)**:
1. 손을 약간 옆으로 옮긴 직후 `c` 키 → 즉시 새 origin
2. robot 은 마지막 명령 그대로지만 이후부터는 새 origin 기준 delta

**종료**:
- `q` 키 또는 Ctrl+C → arm 이 init pose 로 천천히 복귀 후 종료

### `--scale` 옵션

```bash
python scripts/run_teleop_ur10e.py             # default --scale 1.0 (1:1)
python scripts/run_teleop_ur10e.py --scale 1.5 # 사용자 손 10cm → robot 15cm
```

Position 만 scaling, rotation 은 항상 1:1.

### Smoke 검증

```bash
python /workspaces/tamp_ws/src/xr_teleop/scripts/run_teleop_ur10e.py --help
# → --scale SCALE 옵션 표시 + Position scale factor 설명
```

state transition 검증 (`r` → START+RECALIBRATE, `c` → RECALIBRATE, `q` → STOP) — 단위 테스트 PASS.

---

## 1. 사전 점검 (절대 빠지면 안 되는 4 가지)

```bash
# (1) conda env tv 활성
conda activate tv && conda env list | grep '^tv'

# (2) PYTHONPATH 정리 (ROS pinocchio 가림 회피)
unset PYTHONPATH

# (3) DDS env (양 docker 동일)
source /workspaces/tamp_ws/src/xr_teleop/scripts/dds_env.sh
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID  RMW=$RMW_IMPLEMENTATION"
# 예상: ROS_DOMAIN_ID=1  RMW=rmw_cyclonedds_cpp

# (4) Quest 3 USB-C 연결 + adb reverse
adb devices
adb reverse tcp:8012 tcp:8012     # televuer WebSocket
adb reverse tcp:60001 tcp:60001   # head camera WebRTC
adb reverse tcp:60003 tcp:60003   # right_wrist camera WebRTC (60002 disabled)
adb reverse --list                 # UsbFfs tcp:8012/60001/60003 확인
```

---

## 2. 부팅 절차 (3 터미널)

### Terminal 1 — sim docker

```bash
# sim docker shell 접속 후
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
./custom/scripts/run_ur10e_dg5f.sh --headless
# 약 80초 후 'rt/lowstate' 'rt/dg5f/state' publish 시작 (메시지 확인)
```

### Terminal 2 — xr_teleop docker, DDS smoke

```bash
conda activate tv && unset PYTHONPATH
source /workspaces/tamp_ws/src/xr_teleop/scripts/dds_env.sh
# sim 측 rt/lowstate / rt/dg5f/state 수신되는지 빠른 확인
python /workspaces/tamp_ws/src/xr_teleop/scripts/test_dds_sim.py
```

**기대 출력**:
- `rt/lowstate` 3 초 동안 ~280 msg
- `rt/dg5f/state` 3 초 동안 ~150 msg (50Hz throttle)
- ZMQ port 55555 head_camera frame 수신
- (55556 left_wrist 는 sim 측 disable — 0 frame OK)
- ZMQ port 55557 right_wrist_camera frame 수신

DDS 수신 안 되면 **여기서 멈추고** Terminal 1 의 sim 부팅 로그 확인.

### Terminal 3 — xr_teleop teleop entry

Terminal 2 와 같은 environ 에서:

```bash
python /workspaces/tamp_ws/src/xr_teleop/scripts/run_teleop_ur10e.py
```

부팅 메시지 순서 (기대):
```
[run_teleop_ur10e] args: ...
[run_teleop_ur10e] HTTP mode — vuer cert/key forced to None
[run_teleop_ur10e] image spawn func wrapped (... methods)
[run_teleop_ur10e] ChannelFactoryInitialize(1)
[run_teleop_ur10e] camera_config keys: ['head_camera', 'left_wrist_camera', 'right_wrist_camera']
[run_teleop_ur10e] building UR10e_ArmIK...
[run_teleop_ur10e] starting UR10e_ArmController...
[UR10e_ArmController] init...
[UR10e_ArmController] subscribed rt/lowstate.
[UR10e_ArmController] init OK.
[run_teleop_ur10e] starting DG5F_Controller...
[DG5F_Controller] init...
[DG5F_Controller] retargeter: target=6 joints, fixed=14
[DG5F_Controller] subscribed rt/dg5f/state.
[DG5F_Controller] init OK.
──────────────────────────────────────────────
🟢  Press [r] to start syncing Quest 3 hand → UR10e + DG-5F
🔴  Press [q] to stop and exit
──────────────────────────────────────────────
```

### Quest 3 (헤드셋 측)

1. Chrome 으로 `https://localhost:60001` 접속
   - "Your connection is not private" 경고 → "Advanced" → "Proceed to localhost (unsafe)"
   - 영상 (UR10e 상단 카메라) 보이면 cert 신뢰 완료
2. `https://localhost:60003` 접속 — 같은 절차 (right_wrist 카메라)
3. **새 탭**에서 `http://localhost:8012` (HTTP, 60001 과 다름)
4. vuer UI 가 뜨면 **"Enter VR"** 버튼 클릭
5. 헤드셋 view 안에서 손 들이밀기 — 양 손 인식 확인 (사용자가 hand-tracking ON 으로 설정)

### Terminal 3 에서 `r` 키

손 자세가 인식된 상태에서 Terminal 3 stdin 에 `r` 입력 → sync 시작.

**기대 동작** (시각 확인):
- IsaacSim viewport (또는 sim docker WebRTC viewport) 에 UR10e 가 Quest 3 손목 따라 움직임
- DG-5F 손가락이 Quest 3 손가락 굽힘에 반응

---

## 3. Gate 4 측정 항목 (사용자 채울 결과)

다음 표를 30 초 측정 후 채워 보고:

| # | 측정 항목 | 측정 방법 | 통과 기준 | 결과 |
|---|---|---|---|---|
| G4-1 | sim 부팅 시간 | Terminal 1 stopwatch | < 120 s | _ s |
| G4-2 | xr_teleop 부팅 시간 | Terminal 3 (run_teleop_ur10e.py 부터 "Press r") | < 60 s | _ s |
| G4-3 | rt/lowstate rate | test_dds_sim.py | 80-100 Hz | _ Hz |
| G4-4 | rt/dg5f/state rate | test_dds_sim.py | 40-60 Hz | _ Hz |
| G4-5 | vuer page 접속 OK | Quest 3 Chrome http://localhost:8012 | 페이지 로드 | ✅/❌ |
| G4-6 | Quest 3 영상 표시 | Enter VR 후 vuer scene 안 head 카메라 | 영상 보임 | ✅/❌ |
| G4-7 | Quest 3 hand pose recv | run_teleop_ur10e.py log "right_hand" 값 변화 | non-zero | ✅/❌ |
| G4-8 | UR10e tool0 추종 | sim viewport, Quest 3 오른손 ↔ wrist_3_link | 정성 추종 | ✅/❌ |
| G4-9 | UR10e tool0 정확도 | 손을 천천히 (±0.3m)로 5 점 이동 + 시각 측정 | < 10 cm | _ cm |
| G4-10 | DG-5F 손가락 굽힘 visual | Quest 3 손가락 굽힘 → DG-5F 손가락 visual | 정성 추종 (방향 일치) | ✅/❌ |
| G4-11 | DG-5F 굽힘 magnitude | Quest 3 풀 fist → DG-5F finger 굽힘 정도 | 60% 이상 굽음 | _ % |
| G4-12 | thumb rj_dg_1_2 sign | Quest 3 thumb 굽힘 → DG-5F thumb negative direction | ✅/❌ | _ |
| G4-13 | 30 초 측정 후 IK fail rate | run_teleop_ur10e.py log "convergence 실패" | < 5% | _ % |
| G4-14 | 30 초 측정 후 hang/freeze | freezing 없음 | smooth 30Hz | ✅/❌ |

---

## 4. 알려진 issue + 처방 (사용자가 막힐 때)

### Issue A: DG-5F 굽힘이 부족 (G4-11 30% 미만)

**원인**: Unit 1 식별 — vector retargeting magnitude underdetermined.

**처방**:
1. [scripts/dg5f_controller.py:69](../../scripts/dg5f_controller.py#L69) `expand_retarget_to_dg5f_20` 의 `mimic_mid=0.6` 를 1.2 로 (over-mimic) — distal joint 강화
2. 또는 `scripts/dg5f_controller.py` 의 retarget 결과 후처리에 magnitude 증폭 추가:
   ```python
   q_target_dict[name] *= 2.0   # scale 2배
   ```
3. 마지막 수단: dg5f_right.yml `type: DexPilot` 으로 변경

### Issue B: UR10e 가 Quest 3 손 위치를 못 따라감

**원인**: WebXR ↔ UR10e base frame 좌표 align 미적용. Quest 3 floor frame ≠ UR10e base frame.

**처방** ([scripts/run_teleop_ur10e.py](../../scripts/run_teleop_ur10e.py) main loop 안):
```python
# tele_data.right_wrist_pose 받은 후 IK 전에 transform 적용
# UR10e base 는 world z=1m. Quest 3 wrist 도 floor 기준이라 그대로 OK 일 수도.
# 사용자 어깨 위치 (대략 z=1.4m floor 기준) → UR10e base (z=1m) 오프셋:
offset = np.array([0.0, 0.0, -0.4])   # 사용자 손 ~ UR10e base 거리
target = tele_data.right_wrist_pose.copy()
target[:3, 3] += offset
sol_q, sol_tauff = arm_ik.solve_ik(np.eye(4), target, ...)
```

수치는 시각 확인 후 조정. 또는 user calibration step 추가.

### Issue C: IK 수렴 실패 (G4-13 fail rate 높음)

**원인**: target wrist 위치가 UR10e reach 밖.

**처방**:
1. UR10e reach ≈ 1.3m (base 기준). Quest 3 손 위치가 그 안에 있는지 확인.
2. seed 가 부적절 — `arm_ik.init_data = UR10E_INIT_POSE.copy()` 으로 reset 주기 추가.
3. IK fail 시 sol_q = current_q (이전 명령) 유지 — 자동 처리 됨 ([scripts/ur10e_arm_ik.py](../../scripts/ur10e_arm_ik.py) `except Exception` 블록).

### Issue D: Quest 3 vuer scene 빈 공간

**원인**: cert 신뢰 또는 ws race.

**처방**: 본 docker 의 [docs/xr_teleoperate_setup_issues.md](../xr_teleoperate_setup_issues.md) 의 "Galaxy XR Chrome 거부" 절 참조. `https://localhost:60001` 와 `https://localhost:60003` 둘 다 cert 신뢰 후 재시도.

---

## 5. 사용자 보고 양식

다음 형식으로 결과 회신:

```markdown
## Unit 5 E2E 측정 (2026-05-XX)

### Setup
- conda env tv: ✅
- adb reverse 8012/60001/60003: ✅
- sim docker boot: __ s

### Gate 4 측정 (§3 표)
- G4-1  sim boot:        ___ s
- G4-2  xr boot:         ___ s
- G4-3  rt/lowstate:     ___ Hz
- G4-4  rt/dg5f/state:   ___ Hz
- G4-5  vuer page:       ✅/❌
- G4-6  Quest 3 영상:     ✅/❌
- G4-7  hand recv:        ✅/❌
- G4-8  UR10e 추종:       ✅/❌
- G4-9  정확도:           ___ cm
- G4-10 DG-5F visual:     ✅/❌
- G4-11 굽힘 magnitude:   ___ %
- G4-12 thumb sign:       ✅/❌
- G4-13 IK fail rate:     ___ %
- G4-14 30s hang:         ✅/❌

### 발견된 issue + 처방
- ...

### Gate 4 통과 여부: ✅ / ⚠️ partial / ❌
```

이 결과로 본 docker Claude Code 가:
- 통과 시 → week4_report.md 마무리 + Week 5 plan 진입
- partial 시 → Issue A/B/C 처방 코드 적용 + 재측정
- 실패 시 → 더 깊은 분석 (DDS 통신 트레이스, dex_retargeting fork 검토)

---

## 6. 본 Unit 5 자체 검증 (사용자 입력 없이)

본 Claude Code 가 자체 검증한 항목 (sim docker 없이도 가능):

| # | 검증 | 결과 |
|---|---|---|
| 1 | `run_teleop_ur10e.py --help` argparse 동작 | ✅ Unit 4 |
| 2 | `_sanity_check` 통과 (conda env tv + casadi + dex_retargeting) | ✅ Unit 4 |
| 3 | `test_dg5f_retargeting.py` PASS | ✅ Unit 1 |
| 4 | `test_ur10e_ik.py` PASS | ✅ Unit 2 |
| 5 | `test_controllers_smoke.py` PASS | ✅ Unit 3 |

코드 측 작업은 모두 완료. **실 sim + Quest 3 검증만 남음**.
