# Integration Guide for xr_teleoperate Docker

This document describes the **simulation host** environment so the
`xr_teleoperate` container can be configured to talk to it. Both containers
must run on the **same physical host** with `--network=host` for the default
configuration to work without extra wiring.

---

## 1. Simulation Host (this side)

| Item | Value |
|---|---|
| Sim repo | `unitree_sim_isaaclab` (commit on `main`) |
| Sim entry point | `python sim_main.py ...` |
| Conda env | `unitree_sim_env` (Python 3.11) inside `/root/miniconda3/envs/` |
| Isaac Sim version | **5.1.0** (pip-installed in the conda env) |
| Isaac Lab version | 0.46.6 (cloned at `/workspace/isaaclab/datasets/IsaacLab`) |
| OS / kernel | Ubuntu 24.04 / Linux 6.8 |
| GPU | NVIDIA RTX 4090 (24 GB), driver 580.126.09, CUDA 13.0 |
| ROS distro (sidecar only) | ROS 2 Jazzy at `/opt/ros/jazzy` |
| Docker network mode | `host` (verified via `/workspace/isaaclab/docker/docker-compose.yaml`) |

Host IP addresses available (pick one for `--public_ip` / `--img-server-ip`):

| NIC | IP | Notes |
|---|---|---|
| `lo` | `127.0.0.1` | Use this when xr_teleoperate runs on the same host |
| `enp12s0` | `211.221.73.41/24` | Primary wired, default route |
| `wlp13s0` | `192.168.0.10/24` | WiFi, secondary default |
| `docker0` | `172.17.0.1/16` | Docker bridge gateway |

---

## 2. DDS / Communication Settings (must match exactly)

Both containers MUST set:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1                # IMPORTANT: 1, not 0
```

**Why domain 1**: `sim_main.py` hard-codes `ChannelFactoryInitialize(1)`.
The xr_teleoperate side must call the same (or rely on `ROS_DOMAIN_ID=1`).

Multicast discovery works automatically when both containers use
`--network=host`. If you ever switch to bridge networking or run on
different physical hosts, switch to unicast peers via a CycloneDDS XML
config (template at `cyclonedds.xml` in the sim repo).

---

## 3. DDS Topics Published / Subscribed by the Sim

All topics are raw **CycloneDDS** types from `unitree_sdk2py.idl.*` — they
are **not** ROS 2 IDL, so `ros2 topic list` will not show them. Use
`unitree_sdk2py.ChannelSubscriber` / `ChannelPublisher` instead.

### Sim publishes (xr_teleoperate subscribes)

| Topic | Type | Rate | Notes |
|---|---|---|---|
| `rt/lowstate` | `unitree_hg.msg.dds_.LowState_` | ~94 Hz | 35 motor_state entries; IMU; foot force |
| `rt/dex3/left/state` | `unitree_hg.msg.dds_.HandState_` | step rate | Dex3 hand left |
| `rt/dex3/right/state` | `unitree_hg.msg.dds_.HandState_` | step rate | Dex3 hand right |
| `rt/sim_state` | `std_msgs.msg.dds_.String_` | event | JSON sim state |

### Sim subscribes (xr_teleoperate publishes)

| Topic | Type | Use |
|---|---|---|
| `rt/lowcmd` | `unitree_hg.msg.dds_.LowCmd_` | PD targets per motor (35 motors) |
| `rt/dex3/left/cmd` | `unitree_hg.msg.dds_.HandCmd_` | Dex3 left fingers |
| `rt/dex3/right/cmd` | `unitree_hg.msg.dds_.HandCmd_` | Dex3 right fingers |
| `rt/reset_pose/cmd` | `std_msgs.msg.dds_.String_` | Reset scene; payload = category int as string |
| `rt/run_command/cmd` | `std_msgs.msg.dds_.String_` | Wholebody high-level velocity (only for `Wholebody` tasks) |

### `MotorCmd_` payload (per motor, 35 entries in `LowCmd_.motor_cmd`)

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

CRC field on `LowCmd_` may be left at 0 — sim does not verify it (real robot does).

---

## 4. Camera Image Streaming (separate from Isaac Sim WebRTC)

`teleimager` runs an image server inside the sim process when launched with
`--enable_cameras`. xr_teleoperate's `image_client` connects via ZMQ
(default config at [`teleimager/cam_config_server.yaml`](teleimager/cam_config_server.yaml)).

| Camera | ZMQ port | WebRTC port | Resolution |
|---|---|---|---|
| head/front | 55555 | 60001 | 480 × 640 |
| left_wrist | 55556 | 60002 | 480 × 640 |
| right_wrist | 55557 | 60003 | 480 × 640 |

xr_teleoperate side: pass `--img-server-ip 127.0.0.1` (host net) or the host
LAN IP if running on a different machine.

JPEG compression is on by default (`--camera_jpeg --camera_jpeg_quality 85`).

---

## 5. Isaac Sim 3D Viewport WebRTC (optional, not used by xr_teleoperate)

This is the Omniverse Kit viewport stream — useful for human visual
debugging, **not** used by xr_teleoperate. Started by the sim when
`--no_render` and `--headless` are **omitted** and `--livestream_type` is 1
or 2.

Connect with NVIDIA's "Isaac Sim WebRTC Streaming Client" desktop app
pointed at `<public_ip>` (default port 8211 signaling + 49100+ data).

---

## 6. Sim Launch Command (reference)

```bash
# On the sim host:
source /workspace/isaaclab/datasets/unitree_sim_isaaclab/activate_env.sh
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
python sim_main.py \
  --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint \
  --enable_dex3_dds --robot_type g129 \
  --device cuda:0 --enable_cameras \
  --livestream_type 2 --public_ip 127.0.0.1
# Add --headless --no_render to skip the 3D viewport stream
```

Boot time: ~80 s on RTX 4090 before steady-state DDS publishing.

Other supported tasks (substitute for `--task`):
- `Isaac-PickPlace-Cylinder-G129-{Dex1,Dex3,Inspire}-Joint`
- `Isaac-PickPlace-RedBlock-G129-{Dex1,Dex3,Inspire}-Joint`
- `Isaac-Stack-RgyBlock-G129-{Dex1,Dex3,Inspire}-Joint`
- `Isaac-PickPlace-Cylinder-H12-27dof-Inspire-Joint`
- `Isaac-Stack-RgyBlock-H12-27dof-Inspire-Joint`
- `Isaac-Move-Cylinder-G129-{Dex1,Dex3,Inspire}-Wholebody`
- (others — see upstream README)

End-effector flags:
- `--enable_dex1_dds` (gripper) → topic `rt/dex1/{state,cmd}` *(check repo)*
- `--enable_dex3_dds` (3-finger dex hand) → `rt/dex3/{left,right}/{state,cmd}`
- `--enable_inspire_dds` (Inspire hand) → `rt/inspire/...`

---

## 7. xr_teleoperate Container Setup (other side)

Run the container with `--network=host`. Inside, before launching teleop:

```bash
# DDS settings — MUST match the sim host
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1
```

Then launch:

```bash
python teleop_hand_and_arm.py \
  --ee=dex3 \
  --sim \
  --img-server-ip 127.0.0.1
  # --network-interface enp12s0   # only if multicast is blocked
  # --record                      # optional: save trajectories
```

Match `--ee=` to the end-effector flag used by the sim (`dex1` / `dex3` / `inspire`).

`unitree_sdk2_python` version requirement (per upstream xr_teleoperate
README): commit ≥ `404fe44d76f705c002c97e773276f2a8fefb57e4`.

---

## 8. Connectivity Verification

### From xr_teleoperate container, while the sim is running

**A. DDS data flow check** — should print ~280 messages in 3 s (~94 Hz):

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

**B. ZMQ camera frame check** — should print non-zero byte count:

```bash
python - <<'PY'
import zmq
s = zmq.Context().socket(zmq.SUB)
s.connect("tcp://127.0.0.1:55555")
s.setsockopt_string(zmq.SUBSCRIBE, "")
s.setsockopt(zmq.RCVTIMEO, 5000)
print("head_camera frame bytes:", len(s.recv()))
PY
```

**C. Round-trip command test** — publish a passive lowcmd, confirm the sim
ticks without errors. The sim's terminal will show no error and the next
`rt/lowstate` will reflect the commanded state.

```bash
python - <<'PY'
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, MotorCmd_
import time
ChannelFactoryInitialize(1)
pub = ChannelPublisher("rt/lowcmd", LowCmd_); pub.Init()
zero = LowCmd_(
    mode_pr=0, mode_machine=0,
    motor_cmd=[MotorCmd_(mode=0, q=0, dq=0, tau=0, kp=0, kd=0, reserve=0) for _ in range(35)],
    reserve=[0,0,0,0], crc=0,
)
for _ in range(50):
    pub.Write(zero); time.sleep(0.02)
print("published 50 passive lowcmds")
PY
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ros2 topic list` shows only `/parameter_events`, `/rosout` | Unitree topics use raw CycloneDDS types, not ROS 2 IDL | Use `unitree_sdk2py.ChannelSubscriber` to inspect (see §8.A) |
| `ChannelSubscriber` receives 0 messages | Wrong DDS domain | Set `ROS_DOMAIN_ID=1` AND/OR pass `1` to `ChannelFactoryInitialize` |
| `ModuleNotFoundError: teleimager.image_server` (sim side) | `python` shell alias routing to Isaac Sim bundled Python | `unalias python python3 pip pip3` after `conda activate`, or use absolute path `/root/miniconda3/envs/unitree_sim_env/bin/python` |
| Isaac Sim hangs on EULA prompt | Non-interactive EULA acceptance not set | `export OMNI_KIT_ACCEPT_EULA=Y; export PRIVACY_CONSENT=Y` |
| ZMQ camera connect fails | Sim launched without `--enable_cameras` | Re-launch with the flag |
| Multicast not seen across containers | Host firewall / non-host network | Use unicast peers config (`cyclonedds.xml` template in sim repo) |
| Sim frame rate drops below 50 Hz | GPU contention with WebRTC | Run with `--no_render --headless` for compute-only |

---

## 10. Quick-Reference Cheat Sheet

```bash
# Sim host shell:
source /workspace/isaaclab/datasets/unitree_sim_isaaclab/activate_env.sh
cd /workspace/isaaclab/datasets/unitree_sim_isaaclab
python sim_main.py --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint \
  --enable_dex3_dds --robot_type g129 --device cuda:0 --enable_cameras \
  --livestream_type 2 --public_ip 127.0.0.1

# xr_teleoperate container shell:
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1
python teleop_hand_and_arm.py --ee=dex3 --sim --img-server-ip 127.0.0.1
```
