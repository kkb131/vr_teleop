# SIM_UR10E_DG5F_BUILD_GUIDE

> **대상 독자**: IsaacSim 5.1.0이 설치된 별도 docker에서 동작하는 Claude Code 인스턴스.
> **목적**: `unitree_sim_isaaclab`을 fork해 **UR10e (6-DoF arm) + Tesollo DG-5F (5-finger hand)** 조합의 IsaacSim sim 환경을 구축하고, 본 docker(`xr_teleop` dev PC)에서 Quest 3 + WebXR 입력으로 teleop 검증할 수 있도록 DDS/ZMQ 인터페이스를 G1+Dex3 sim과 동일 패턴으로 publish.
> **선행 조건**: 본 docker에서 G1+Dex3 sim과의 풀 파이프라인은 이미 검증 완료됨 (Phase 1, commit `1cf8451`). UR10e+DG-5F는 같은 인터페이스로 publish하면 본 docker 측 코드는 단순 controller 추가만으로 동작 가능.

---

## 0. TL;DR (3분 안내)

1. `unitree_sim_isaaclab` clone, **H1-2 (27-DoF) + Inspire** task가 이미 등록되어 있으니 그 패턴을 복제 — UR10e+DG-5F 추가는 **architectural change가 아니라 config variation**.
2. UR10e URDF는 본 워크스페이스에 이미 있음: [/workspaces/tamp_ws/src/tamp_dev/.docker/assets/ur10e.urdf](/workspaces/tamp_ws/src/tamp_dev/.docker/assets/ur10e.urdf). DG-5F URDF는 [/workspaces/tamp_ws/src/dg5f_ros2/dg5f_description/urdf/dg5f_right.urdf](/workspaces/tamp_ws/src/dg5f_ros2/dg5f_description/urdf/dg5f_right.urdf) (single hand, right). 두 파일을 sim docker로 옮겨서 작업.
3. URDF → USD 변환 경로는 README에 미문서화 — Day 1 spike에서 확인 필요. 대안: IsaacLab의 표준 URDF importer (`omni.isaac.core.utils.urdf_to_usd`) 또는 `tools/` 폴더 스크립트.
4. 최종 검증: `python sim_main.py --task Isaac-Reach-UR10e-DG5F-Joint --robot_type ur10e --enable_dg5f_dds --device cuda:0 --enable_cameras --livestream_type 2 --public_ip 127.0.0.1` 부팅 + DDS topic 7가지 publish/subscribe 통과.
5. 작업 끝나면 본 docker(xr_teleop side) Claude Code에 결과 보고 → 본 docker가 후속 plan mode로 들어가 xr_teleoperate 측 UR10e_ArmIK / DG5F_Controller / dex_retargeting config 작업 진행.

---

## 1. Background & Final Goal

### 1.1 12-week 계획 위치

이 작업은 12주 개발 계획의 **Phase 2 (Week 4-6)** 일부. 최종 목표는 UR10e + Tesollo DG-5F (5-finger) teleop을 IsaacSim에서 검증한 후 real robot 단계로 옮기는 것. 본 docker는 이미 **Phase 1 (Week 1-3) 완료** 상태:

- ✅ Gate 1 (Week 1): Quest 3/Galaxy XR Chrome WebXR 25-joint hand tracking 동작
- ✅ Gate 2 (Week 2): televuer pose-only 30Hz 안정 스트리밍
- ✅ Gate 3 (Week 3): IsaacSim G1+Dex3 sim과 풀 파이프라인 (DDS + WebXR + WebRTC 영상) 동작

본 가이드의 sim build가 끝나면 본 docker에서 **Gate 4 (Week 6)** 통과를 위한 후속 작업을 진행.

### 1.2 핵심 설계 원칙: 인터페이스 호환성 유지

**xr_teleop 측 코드는 G1+Dex3 sim과 동일한 DDS/ZMQ 인터페이스로 동작 중**. UR10e+DG-5F sim도 **같은 topic 이름과 동일한 message type**으로 publish하면 xr_teleop 측 코드 변경이 최소화됨:

- `rt/lowstate` motor 수만 35 → 6으로 줄어들고, motor[0:6]만 의미 있음
- `rt/dex3/{left,right}/*` 제거, **`rt/dg5f/{state,cmd}` 신규 (single hand)**
- ZMQ camera 3개 + WebRTC 3개는 그대로 (port 동일)

이 원칙을 sim build 내내 유지할 것.

### 1.3 환경 (sim docker가 이미 알고 있는 정보일 가능성 높지만 재확인)

| 항목 | 값 |
|---|---|
| Sim repo | `unitree_sim_isaaclab` (https://github.com/unitreerobotics/unitree_sim_isaaclab) |
| Sim entry point | `python sim_main.py ...` |
| Conda env | `unitree_sim_env` (Python 3.11) at `/root/miniconda3/envs/` |
| Isaac Sim version | **5.1.0** (pip-installed in conda env) |
| Isaac Lab version | 0.46.6 (cloned at `/workspace/isaaclab/datasets/IsaacLab`) |
| Activation | `source /workspace/isaaclab/datasets/unitree_sim_isaaclab/activate_env.sh` |

---

## 2. Pre-info: unitree_sim_isaaclab Repo

### 2.1 검증된 사실 (본 docker에서 GitHub README 확인)

- 이미 **G1 (29-DoF) + Dex3** 와 **H1-2 (27-DoF) + Inspire** 두 가지 robot+hand 조합이 task로 등록되어 있음. UR10e+DG-5F 추가는 같은 패턴의 config variation.
- 등록된 task 예시 (README에서 확인):
  - `Isaac-PickPlace-Cylinder-G129-Dex3-Joint`
  - `Isaac-PickPlace-Cylinder-G129-Inspire-Joint`
  - `Isaac-Stack-RgyBlock-G129-Dex3-Joint`
  - `Isaac-PickPlace-Cylinder-H12-27dof-Inspire-Joint` ← **H1-2 + Inspire reference**
  - `Isaac-Stack-RgyBlock-H12-27dof-Inspire-Joint`
  - `Isaac-Move-Cylinder-G129-Dex3-Wholebody`
- `--robot_type` flag로 g129/h1_2 분기. UR10e용으로 `ur10e` 추가 필요.
- End-effector flag: `--enable_dex3_dds`, `--enable_inspire_dds`, `--enable_dex1_dds` (gripper). UR10e용으로 `--enable_dg5f_dds` 추가 필요.

### 2.2 추정 구조 (Day 1 spike에서 정확히 확인할 항목)

- `robots/<robot_name>/` 디렉토리: URDF/USD path, joint limits, PD gains, mass properties
- `action_provider/<hand_name>_provider.py`: hand DDS topic ↔ 모터 인덱스 binding
- `tasks/` 또는 isaaclab Task class: gymnasium register + reward + termination
- `tools/`: URDF→USD 변환 스크립트 (없을 수도 있음 → IsaacLab 표준 importer 사용)

### 2.3 Day 1 spike에서 확인해야 할 것 (체크리스트)

1. `robots/h1_2/`의 정확한 디렉토리 구조 (어떤 .py / .yaml / .usd 파일이 있는지)
2. `action_provider/inspire_*.py`의 hand binding 패턴 (Inspire 6 motor → DDS HandCmd_ 변환)
3. `Isaac-PickPlace-Cylinder-H12-27dof-Inspire-Joint` task의 등록 위치 (gym.register 호출)
4. `sim_main.py`의 `--robot_type` 분기 위치 (어디서 robot config를 dispatch하는지)
5. URDF→USD 변환: `tools/` 디렉토리 확인 → 없으면 `omni.isaac.core.utils.urdf_to_usd` 또는 `omni.importer.urdf` 사용
6. Camera spawn 위치: G1+Dex3 task에서 head/left_wrist/right_wrist 3 카메라가 어떻게 정의되는지 (UR10e+DG-5F task에 그대로 옮길 것)

산출: `unitree_sim_isaaclab fork 내` `docs/sim_day1_spike.md` 작성 (sim docker 측에 작성, 본 docker로 결과 회신).

---

## 3. DDS / ZMQ Specification (xr_teleop ↔ sim)

본 docker의 [INTEGRATION_FOR_XR_TELEOPERATE.md](INTEGRATION_FOR_XR_TELEOPERATE.md)에서 발췌 + UR10e+DG-5F용 변경분.

### 3.1 환경 변수 (양 docker 모두 동일)

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1                # IMPORTANT: 1, not 0
```

`sim_main.py`에서 `ChannelFactoryInitialize(1)`을 hard-code. UR10e task에서도 동일하게.

Multicast discovery는 `--network=host` docker 환경에서 자동 동작. 둘 다 같은 host에 떠 있어야 함.

### 3.2 DDS topic 명세

#### Sim publishes (xr_teleop subscribes)

| Topic | Type | Rate | G1+Dex3 (현재) | **UR10e+DG-5F (목표)** |
|---|---|---|---|---|
| `rt/lowstate` | `unitree_hg.msg.dds_.LowState_` | ~94 Hz | 35 motor | **6 motor만 의미** (motor[0:6]) |
| `rt/dex3/left/state` | `unitree_hg.msg.dds_.HandState_` | step rate | Dex3 left | **publish 안 함 (제거)** |
| `rt/dex3/right/state` | `unitree_hg.msg.dds_.HandState_` | step rate | Dex3 right | **publish 안 함 (제거)** |
| **`rt/dg5f/state`** | `unitree_hg.msg.dds_.HandState_` | step rate | (없음) | **신규: DG-5F 20 joint** |
| `rt/sim_state` | `std_msgs.msg.dds_.String_` | event | JSON | 동일 |

#### Sim subscribes (xr_teleop publishes)

| Topic | Type | G1+Dex3 (현재) | **UR10e+DG-5F (목표)** |
|---|---|---|---|
| `rt/lowcmd` | `unitree_hg.msg.dds_.LowCmd_` | 35 motor PD targets | **6 motor만 처리** (나머지 무시) |
| `rt/dex3/left/cmd` | `unitree_hg.msg.dds_.HandCmd_` | Dex3 left | **subscribe 안 함 (제거)** |
| `rt/dex3/right/cmd` | `unitree_hg.msg.dds_.HandCmd_` | Dex3 right | **subscribe 안 함 (제거)** |
| **`rt/dg5f/cmd`** | `unitree_hg.msg.dds_.HandCmd_` | (없음) | **신규: DG-5F 20 joint targets** |
| `rt/reset_pose/cmd` | `std_msgs.msg.dds_.String_` | reset scene | 동일 |
| `rt/run_command/cmd` | `std_msgs.msg.dds_.String_` | wholebody high-level | UR10e wholebody는 미정 (Week 5+) |

#### `MotorCmd_` payload (per motor — `LowCmd_.motor_cmd[i]` 각 entry)

```
mode      : uint8     # 1 = PD enabled, 0 = passive
q         : float32   # target position [rad]
dq        : float32   # target velocity [rad/s]
tau       : float32   # feedforward torque [N·m]
kp        : float32   # P gain
kd        : float32   # D gain
reserve   : uint32
```

Effective torque: `τ = kp·(q_target − q_actual) + kd·(dq_target − dq_actual) + tau`.

`LowCmd_.crc`는 0이어도 sim은 verify 안 함 (real robot은 함). UR10e sim도 동일.

#### `HandCmd_` (DG-5F 신규 topic)

DG-5F는 single hand이므로 left/right 분리 없이 `rt/dg5f/cmd` 하나만 사용. `HandCmd_.motor_cmd[i]` 인덱스 0-19에 DG-5F joint 매핑 (joint 순서는 DG-5F URDF의 joint 등장 순 — Day 3 작업에서 명시).

### 3.3 DDS-only specs are *raw CycloneDDS types* — `ros2 topic list`로 안 보임

`unitree_sdk2py.idl.*`에서 import. ROS 2 IDL 아니므로 `ros2 topic list`엔 안 뜸. inspect는 `unitree_sdk2py.ChannelSubscriber`로 (verification 섹션 참조).

### 3.4 ZMQ camera streaming (G1과 동일, 변경 없음)

| Camera | ZMQ port | WebRTC port | Resolution |
|---|---|---|---|
| head/front | 55555 | 60001 | 480 × 640 |
| left_wrist | 55556 | 60002 | 480 × 640 |
| right_wrist | 55557 | 60003 | 480 × 640 |

UR10e single-arm 환경이라 left_wrist는 의미 없을 수 있지만 **port와 topic 이름은 그대로 유지** (xr_teleop 측 코드 변경 회피). UR10e tool0 link에 부착된 카메라를 `right_wrist`로, scene 위쪽 또는 head mount 카메라를 `head`로, dummy/zero 영상을 `left_wrist`로 publish해도 됨 (또는 head를 상부에 두고 right_wrist는 손목, left_wrist는 비활성으로 zero frame).

JPEG compression default ON (`--camera_jpeg --camera_jpeg_quality 85`). 그대로 유지.

### 3.5 WebRTC viewport (Isaac Sim Omniverse Kit, 별도)

`--livestream_type 2` + `--public_ip <ip>`로 부팅 시 kit viewport stream 8211 + 49100+. 디버깅용, xr_teleop은 사용 안 함. 그대로 유지.

---

## 4. URDF Sources

### 4.1 UR10e URDF

본 워크스페이스 (xr_teleop docker)에 이미 있음:

```
/workspaces/tamp_ws/src/tamp_dev/.docker/assets/ur10e.urdf      (canonical)
/workspaces/tamp_ws/src/tamp_dev/ur10e.urdf                     (sub copy)
/workspaces/tamp_ws/build/isaac_ros_cumotion_robot_description/urdf/ur10e_robotiq_2f_140.urdf   (with Robotiq 2F-140 gripper, 참고용)
```

**권장**: `src/tamp_dev/.docker/assets/ur10e.urdf` 사용 (canonical, no end-effector). DG-5F는 별도 URDF로 부착.

전송 방법:
- 본 docker 측에서 sim docker로 copy: `scp` 또는 host 공유 볼륨 사용. 사용자가 docker mount 또는 직접 복사 후 sim docker Claude Code에 경로 알려줌.
- 또는 sim docker Claude Code가 `ur_description` ROS 2 Jazzy 패키지에서 직접 받기 (sim docker에 ROS 2 Jazzy 설치되어 있음 per §1.3 sidecar).

### 4.2 DG-5F URDF

본 워크스페이스의 `dg5f_ros2` 패키지에 다양한 변형이 있음:

```
src/dg5f_ros2/dg5f_description/urdf/
├── dg5f_right.urdf              ← 권장: single right hand, ros2_control 메타 없음
├── dg5f_right_short.urdf        ← shorter alternate (검증 필요)
├── dg5f_right.xacro             ← xacro 원본
├── dg5f_left.urdf               ← left 변형 (DG-5F single-hand 환경에선 미사용)
├── dg5f_macro.xacro             ← 매크로 정의
└── ... (gz / driver 변형들)
```

**권장**: `dg5f_right.urdf` 사용. 단 Day 1 spike에서 다음을 확인:
- joint 개수 (예상: 5 fingers × 4 joints = 20)
- joint 순서 (DDS HandCmd_ motor index와 매핑되도록 명시)
- mass / inertia 값이 official Tesollo spec과 일치하는지 (없으면 dummy로 진행, Week 5에서 보정)

전송 방법: UR10e와 동일.

### 4.3 UR10e + DG-5F 결합

UR10e의 `tool0` link (또는 `flange` link)에 DG-5F base를 부착. 두 가지 방법:

(a) **단일 통합 URDF** 작성: UR10e URDF의 `tool0` link 아래에 DG-5F URDF를 `<xacro:include>` 또는 수동 fixed joint로 결합 → 단일 USD 변환.

(b) **두 개 별도 USD + IsaacLab Articulation 연결**: UR10e USD 따로, DG-5F USD 따로, IsaacLab에서 `mount` 관계로 결합.

H1-2 + Inspire reference 패턴을 보고 sim docker Claude Code가 더 자연스러운 방법 선택. 권장은 (a) — sim 환경에서 single articulation으로 다루는 게 PD 제어 인터페이스 단순화.

---

## 5. Work Steps (Day-by-Day)

### Day 1 — Spike: repo clone + structure 파악 + URDF→USD 변환 시도

1. `unitree_sim_isaaclab` clone (또는 이미 sim docker에 있으면 path 확인)
2. README + 디렉토리 구조 dump → §2.3 체크리스트 채우기
3. `Isaac-PickPlace-Cylinder-H12-27dof-Inspire-Joint` task가 sim docker에서 부팅되는지 먼저 확인 (baseline 검증):

```bash
source /workspace/isaaclab/datasets/unitree_sim_isaaclab/activate_env.sh
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
python sim_main.py \
  --task Isaac-PickPlace-Cylinder-H12-27dof-Inspire-Joint \
  --enable_inspire_dds --robot_type h1_2 \
  --device cuda:0 --enable_cameras \
  --livestream_type 2 --public_ip 127.0.0.1
```

부팅되고 `rt/lowstate` publish가 확인되면 OK. 안 되면 IsaacLab 0.46.6 / IsaacSim 5.1.0 호환성 문제 — sim docker 자체 환경 점검 필요 (이건 sim docker Claude Code의 책임).

4. UR10e URDF 사본 받아서 USD 변환 spike:
   - `tools/` 디렉토리 확인, 변환 스크립트 있으면 사용
   - 없으면 IsaacLab 표준 `omni.importer.urdf.UrdfImporter` 또는 IsaacLab CLI (`isaaclab.sh -p source/standalone/tools/convert_urdf.py` 패턴) 시도
   - 실패 시 `omni.isaac.core.utils.urdf_to_usd` 함수 직접 호출 시도
5. DG-5F URDF에 대해 동일하게 변환 spike

산출: sim docker fork 내 `docs/sim_day1_spike.md`. 다음 정보 포함:
- §2.3 체크리스트 답
- H1-2 baseline 부팅 결과 (성공/실패 + 로그)
- URDF→USD 변환 절차 (어떤 함수/스크립트가 동작했는지)
- Day 2 진입 가능 여부 + 막힘 사항

### Day 2 — `robots/ur10e/` 신규 + minimal task 등록

1. H1-2 reference 복제: `cp -r robots/h1_2 robots/ur10e` 후 다음을 UR10e로 바꿈:
   - URDF/USD path → UR10e (Day 1 변환 결과물)
   - joint count: 6
   - joint names: `["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"]` (UR10e 표준)
   - joint limits / mass / inertia: UR10e URDF에서 읽어옴 (URDF에 명시되어 있음)
   - PD gains: H1-2 값을 시작점으로 두되 Day 5에서 oscillation/sluggish 발견 시 조정. 초기 추정: `kp=300, kd=20` (G1 humanoid 대비 stiffer 필요할 수 있음, UR10e의 mass / link 길이 고려)
   - action_space dim: 6 (arm) + 20 (DG-5F) = 26 (또는 G1과 동일하게 35-slot으로 두고 UR10e 6 + DG-5F 20만 사용해도 됨 — 후자가 LowCmd_ message size를 G1과 같게 유지해 호환성 유리)

2. minimal task 등록: `Isaac-Reach-UR10e-DG5F-Joint`
   - reach task가 가장 단순 (target XYZ에 EE 도달)
   - gymnasium register (또는 IsaacLab Task class extension)
   - reward / termination은 H1-2 reach pattern 복제, EE link만 UR10e `tool0` (또는 DG-5F palm link)으로 변경

3. `sim_main.py`에 `--robot_type ur10e` 분기 추가

4. 부팅 검증:
```bash
python sim_main.py \
  --task Isaac-Reach-UR10e-DG5F-Joint \
  --robot_type ur10e \
  --device cuda:0 --enable_cameras \
  --livestream_type 2 --public_ip 127.0.0.1
```
부팅 + IsaacSim viewport (livestream)에 UR10e + DG-5F 표시 + `rt/lowstate` publish 확인.

DDS publish 확인 (sim docker 측에서 직접):
```bash
python - <<'PY'
import time
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
ChannelFactoryInitialize(1)
counts = {"n": 0}
def cb(msg): counts["n"] += 1
sub = ChannelSubscriber("rt/lowstate", LowState_)
sub.Init(cb, 10)
time.sleep(3)
sub.Close()
print(f"received {counts['n']} msgs in 3s (expect ~280)")
PY
```

### Day 3 — DG-5F action_provider 추가 + `rt/dg5f/{state,cmd}` topic

1. `action_provider/inspire_*.py` 또는 `dex3_*.py` 패턴 복제 → `dg5f_provider.py`
2. DG-5F 20 joint 인덱스 매핑 정의 (DG-5F URDF의 joint 등장 순서를 인덱스 0-19로 — Day 1 spike의 joint 순서 결과 참조). 각 손가락별 4 joint:
   - 0-3: thumb (rotation, base, prox, dist)
   - 4-7: index (base, prox, dist1, dist2 — DG-5F는 손가락마다 4 joint 가정. 정확한 이름은 URDF 참조)
   - 8-11: middle
   - 12-15: ring
   - 16-19: pinky
3. `rt/dg5f/cmd` subscribe → `HandCmd_.motor_cmd[0:20]`을 IsaacSim DG-5F joint actuator에 적용 (PD 제어)
4. `rt/dg5f/state` publish → IsaacSim DG-5F joint state를 `HandState_.motor_state[0:20]`로 매핑
5. `sim_main.py`에 `--enable_dg5f_dds` flag 추가

검증:
```bash
python sim_main.py --task Isaac-Reach-UR10e-DG5F-Joint --robot_type ur10e \
  --enable_dg5f_dds --device cuda:0 --enable_cameras --livestream_type 2 --public_ip 127.0.0.1
```
+ DDS subscribe로 `rt/dg5f/state` 확인:
```bash
python - <<'PY'
import time
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandState_
ChannelFactoryInitialize(1)
counts = {"n": 0}
def cb(msg): counts["n"] += 1
sub = ChannelSubscriber("rt/dg5f/state", HandState_)
sub.Init(cb, 10)
time.sleep(3)
sub.Close()
print(f"received {counts['n']} msgs in 3s")
PY
```

### Day 4 — Camera scene mount + ZMQ/WebRTC publish

H1-2 또는 G1 task의 camera 정의를 UR10e task로 옮김:
- **head**: scene 상단 또는 가상 머리 위치에 fixed mount → ZMQ 55555 + WebRTC 60001
- **right_wrist**: UR10e `tool0` link 또는 DG-5F palm에 부착 → ZMQ 55556... wait, **right_wrist는 ZMQ 55557 / WebRTC 60003**. left_wrist가 55556 / 60002.
- **left_wrist**: UR10e single-arm 환경에선 의미 없음. **zero frame (검은 영상) publish** 또는 right_wrist의 미러 publish (xr_teleop 측에서 left_wrist를 사용 안 하므로 그냥 zero로 두면 됨).

(ZMQ port 매핑 재확인: head=55555, left_wrist=55556, right_wrist=55557. WebRTC 동일 순서로 60001/60002/60003. UR10e+DG-5F sim의 right_wrist에 실제 손목 카메라를 mount.)

검증:
```bash
# ZMQ
python - <<'PY'
import zmq
s = zmq.Context().socket(zmq.SUB)
s.connect("tcp://127.0.0.1:55555")
s.setsockopt_string(zmq.SUBSCRIBE, "")
s.setsockopt(zmq.RCVTIMEO, 5000)
print("head_camera frame bytes:", len(s.recv()))
PY
```
+ WebRTC: 본 docker 측에서 `https://localhost:60001/60002/60003` 접속 + cert 신뢰 후 stream 수신 (xr_teleop 측 사용자가 별도 검증).

### Day 5 — Round-trip command 검증

본 docker 측에서 `rt/lowcmd`를 publish 후 sim의 UR10e가 추종하는지 확인. sim docker Claude Code는 **sim 측에서 어떤 동작을 보였는지** (UR10e가 움직였는가, 어떤 자세로 갔는가) 결과를 보고만 하면 됨.

본 docker가 publish할 명령 예시 (참고):
```python
# xr_teleop side (참고용 — sim docker는 publish할 필요 없음)
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, MotorCmd_
ChannelFactoryInitialize(1)
pub = ChannelPublisher("rt/lowcmd", LowCmd_); pub.Init()
# motor_cmd[0:6]에 UR10e target q, kp, kd 채워서 publish
```

sim docker 측은:
- `rt/lowcmd`를 subscribe해 motor_cmd[0:6]을 UR10e joint actuator targets로 적용
- IsaacSim에서 UR10e가 명령에 따라 움직이는지 viewport (livestream) 또는 `rt/lowstate` motor[0:6].q 값 변화로 확인

DG-5F도 동일하게 `rt/dg5f/cmd` subscribe 후 IsaacSim DG-5F joint 추종 확인.

PD tuning: oscillation 또는 너무 sluggish하면 `robots/ur10e/` PD gains 조정.

---

## 6. Verification (sim build 종료 조건)

다음 7가지 항목 모두 통과 시 sim build 완료. 본 docker 측 사용자에게 보고하고 후속 plan mode 진입.

| # | 항목 | 검증 명령 / 방법 | 통과 기준 |
|---|---|---|---|
| 1 | task 부팅 | `python sim_main.py --task Isaac-Reach-UR10e-DG5F-Joint --robot_type ur10e --enable_dg5f_dds --device cuda:0 --enable_cameras --livestream_type 2 --public_ip 127.0.0.1` | 80초 내 IsaacSim viewport에 UR10e+DG-5F 표시 |
| 2 | `rt/lowstate` publish | §3.4 ChannelSubscriber 코드 (LowState_) | 3초간 ~280 msg 수신 (~94Hz), motor[0:6].q가 valid float |
| 3 | `rt/dg5f/state` publish | §Day 3 ChannelSubscriber 코드 (HandState_) | step rate에 맞게 msg 수신, motor[0:20].q valid |
| 4 | ZMQ 3 cameras | §Day 4 zmq.SUB code (port 55555, 55556, 55557) | 각 port에서 non-zero byte frame 수신 |
| 5 | WebRTC 3 streams | sim 측 부팅 로그에서 `WebRTC server started on 60001/60002/60003` 확인 + 본 docker 측 https 접속 결과 보고 받음 | 3 port 모두 부팅 |
| 6 | `rt/lowcmd` round-trip | 본 docker 측 publish + sim 측 UR10e 추종 visual 확인 | UR10e joint이 명령에 따라 움직임 |
| 7 | `rt/dg5f/cmd` round-trip | 본 docker 측 publish + sim 측 DG-5F 추종 visual 확인 | DG-5F finger joint이 명령에 따라 움직임 |

**완료 보고 형식** (sim docker Claude Code → user → 본 docker Claude Code):

```
[SIM BUILD COMPLETE]
- Item 1 ✅ (boot time: 75s)
- Item 2 ✅ (rate: 92Hz)
- Item 3 ✅ (rate: 60Hz)
- Item 4 ✅ (head/left/right all received)
- Item 5 ✅ (all 3 streams)
- Item 6 ✅ (UR10e tracked target within 0.05 rad)
- Item 7 ✅ (DG-5F fingers responsive)

Repo: <fork URL or path>
Activation: source /workspace/isaaclab/datasets/unitree_sim_isaaclab/activate_env.sh
Launch:
  python sim_main.py --task Isaac-Reach-UR10e-DG5F-Joint --robot_type ur10e \
    --enable_dg5f_dds --device cuda:0 --enable_cameras \
    --livestream_type 2 --public_ip 127.0.0.1

Issues encountered:
  - <list any non-blocking quirks>

Files added/modified:
  - robots/ur10e/__init__.py
  - robots/ur10e/ur10e_cfg.py
  - robots/ur10e/<usd file>
  - action_provider/dg5f_provider.py
  - tasks/<reach task file>
  - sim_main.py (added --robot_type ur10e branch)
```

---

## 7. Risks & Fallbacks

| Risk | Trigger | Fallback |
|---|---|---|
| H1-2 baseline 자체가 sim docker에서 안 부팅 | Day 1 §5 step 3 실패 | sim docker 환경 점검: IsaacSim 5.1.0 / IsaacLab 0.46.6 버전 align. unitree_sim_isaaclab 의 setup 단계 재수행 |
| URDF→USD 변환 절차 미문서화 | Day 1 spike 막힘 | (a) `omni.importer.urdf.UrdfImporter` 직접 호출 (b) IsaacLab CLI (`isaaclab.sh -p source/standalone/tools/convert_urdf.py`) (c) Isaac Sim GUI에서 URDF importer extension 사용 후 USD 저장 |
| DG-5F URDF의 mass/inertia 부정확 → 시뮬 불안정 | Day 5 PD tuning 안 됨 | Week 5 작업으로 연기 (Tesollo official spec 또는 SolidWorks 기반 보정). Week 4에선 dummy 값으로 진행 |
| UR10e+DG-5F 통합 URDF 작성 어려움 | Day 1 §4.3 (a) 실패 | 방법 (b): UR10e 따로, DG-5F 따로 USD 후 IsaacLab Articulation으로 결합 |
| `rt/dg5f/{state,cmd}` topic 이름이 unitree_sdk2py에 미정의 | Day 3 publish 실패 | Topic name은 string이므로 자유. `HandState_` / `HandCmd_` IDL은 그대로 사용 — 단지 motor 슬롯 20개를 채우면 됨. unitree_sdk2py 변경 불필요 |
| IsaacSim 5.1.0이 sim_main.py 부팅 시 EULA prompt에서 hang | env var 미설정 | `export OMNI_KIT_ACCEPT_EULA=Y; export PRIVACY_CONSENT=Y` |
| Multicast가 host network에서 안 보임 | 본 docker에서 ChannelSubscriber 가 0 msg | 양 docker 모두 `--network=host` 확인. host firewall 점검. 안 되면 `cyclonedds.xml` unicast peers 설정 (sim repo에 template 있음) |

---

## 8. Out of Scope (xr_teleop docker가 후속 plan mode에서 진행)

이 가이드의 deliverable은 **sim 환경 그 자체** (위 §6 7가지 항목 통과). 다음 작업은 본 docker (xr_teleop side)에서 별도 plan으로 진행하므로 sim docker Claude Code는 신경 쓸 필요 없음:

- xr_teleoperate에 `UR10e_ArmController` (rt/lowcmd 6-motor publisher) + `UR10e_ArmIK` (Pinocchio + CasADi single-arm IK) 추가
- xr_teleoperate에 `DG5F_Controller` (rt/dg5f/cmd publisher) 추가
- `dex_retargeting` 라이브러리에 DG-5F config 등록 (Inspire 패턴 복제)
- `teleop_hand_and_arm.py`에 `--arm ur10e --ee dg5f` 분기
- 본 docker 측 `setup/test_dds_ur10e.py` 작성
- end-to-end smoke test (Quest 3 → vuer → IsaacSim UR10e tool0 추종 + DG-5F 손가락 동작)
- Week 4 report 작성

---

## 9. Communication Protocol

### 9.1 본 docker (xr_teleop) → sim docker

이 가이드 md 파일 자체가 본 docker가 sim docker에 보내는 1차 input. 부족하거나 막히면 sim docker Claude Code가 user에게 질문 → user가 본 docker Claude Code에 전달 → 본 docker가 가이드 update 후 재전달.

### 9.2 sim docker → 본 docker

§6의 "완료 보고 형식"에 따라 보고. user가 본 docker로 가져와 다음 plan mode 진입의 input으로 사용.

중간 단계 진척 보고도 환영 (예: "Day 1 spike 결과 — H1-2 baseline 부팅 OK, URDF→USD는 omni.importer.urdf 사용 가능 확인" 등). 본 docker가 가이드 update가 필요한지 판단.

### 9.3 URDF 파일 전달

본 docker → sim docker로 다음 두 파일 사본 전달 필요:
- `/workspaces/tamp_ws/src/tamp_dev/.docker/assets/ur10e.urdf`
- `/workspaces/tamp_ws/src/dg5f_ros2/dg5f_description/urdf/dg5f_right.urdf`

전달 방법은 user 환경에 따름:
- docker mount 공유 path (가장 깔끔)
- `scp` 또는 `cp` (host filesystem 공유)
- git: 본 docker가 별도 branch에 두 파일 commit 후 sim docker에서 pull
- 또는 sim docker의 ROS 2 Jazzy `ur_description` 패키지 사용 (UR10e만, DG-5F는 본 docker에서 받아야 함)

---

## 10. References

- 본 워크스페이스 내 참조:
  - [INTEGRATION_FOR_XR_TELEOPERATE.md](INTEGRATION_FOR_XR_TELEOPERATE.md) — DDS/ZMQ 사양 base (G1+Dex3 기준)
  - [week3_report.md](week3_report.md) — Phase 1 G1+Dex3 sim 부팅 절차 (UR10e 변형 base)
  - [xr_teleoperate_setup_issues.md](xr_teleoperate_setup_issues.md) — Phase 1 발견 issue 목록 (sim docker 측에 도움 안 될 가능성 높지만 참고)
- 외부:
  - https://github.com/unitreerobotics/unitree_sim_isaaclab
  - https://docs.isaacsim.omniverse.nvidia.com/5.1.0/ (Isaac Sim 5.1.0 docs)
  - https://isaac-sim.github.io/IsaacLab/v0.46.6/ (IsaacLab 0.46.6 docs)
  - https://github.com/unitreerobotics/unitree_sdk2_python (DDS topic / IDL)

---

*이 가이드는 본 docker (xr_teleop dev PC)의 Claude Code가 sim docker (IsaacSim 설치 환경)의 Claude Code에게 전달하는 self-contained build instruction입니다. 본 가이드만으로 sim build가 완료되도록 작성되었으며, 부족하거나 막히는 부분은 user를 통해 본 docker로 회신해 가이드 update를 요청해 주세요.*
