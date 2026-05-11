#!/usr/bin/env python3
"""UR10e + DG-5F teleop entry — Galaxy XR ws bridge 변형.

run_teleop_ur10e.py (Quest 3 / vuer) 의 Galaxy XR 변형. vuer 0.0.60 client React
가 Galaxy XR Chrome 에서 immersive 진입 후 publish freeze 되는 문제로,
self-hosted ws bridge ([scripts/bridge_pose_store.py](bridge_pose_store.py) +
[assets/webxr_to_pose.html](../assets/webxr_to_pose.html)) 가 검증됨.

이 entry 는 그 ws bridge 를 우리 UR10e+DG-5F pipeline 에 inject:
- televuer.televuer.TeleVuer / televuer.tv_wrapper.TeleVuer / televuer.TeleVuer
  세 군데 모두 BridgePoseStore 로 monkey-patch (run_teleop_ws.py 패턴 그대로)
- TeleVuerWrapper.__init__ 가 TeleVuer(...) 호출 시 BridgePoseStore 인스턴스
  생성 → 자체 ws server (default port 8013) 자동 시작
- TeleVuerWrapper 의 좌표 변환 / smoothing / hand_pos 그대로 — interface 동일

run_teleop_ur10e.py 와의 차이:
- vuer cert monkey-patch 제거 (vuer 안 씀 — ws bridge 자체 server)
- 영상 spawn retry monkey-patch 제거 (vuer 영상 plane 안 씀)
- adb reverse 안내: 8013 (ws bridge) + 60001/60003 (WebRTC 영상) 둘 다 필요
- 나머지 모두 동일: DDS init, UR10e_ArmIK, UR10e_ArmController, DG5F_Controller,
  relative motion + recalibrate (r/c/p/q 키) + --scale

Usage:
  conda activate tv
  source scripts/dds_env.sh
  adb reverse tcp:8013 tcp:8013        # ws bridge port
  adb reverse tcp:60001 tcp:60001      # head camera (optional)
  adb reverse tcp:60003 tcp:60003      # right_wrist camera (optional)
  python scripts/run_teleop_ur10e_ws.py
  # Galaxy XR Chrome → http://localhost:8013/ → Enter VR/AR → 손 들이밀기 → r 키

cf. [docs/galaxy_xr_ws_bridge_integration.md](../docs/galaxy_xr_ws_bridge_integration.md)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from multiprocessing import Array, Lock
from pathlib import Path

import numpy as np

# 본 repo 의 scripts/ + xr_teleoperate/teleop/ 둘 다 import 가능하게
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "xr_teleoperate"))
sys.path.insert(0, str(REPO_ROOT / "xr_teleoperate" / "teleop"))


# ─── BridgePoseStore monkey-patch (run_teleop_ws.py 패턴) ──────────────────

def _inject_bridge_pose_store() -> None:
    """televuer.TeleVuer 세 모듈 namespace 동시에 BridgePoseStore 로 교체.

    tv_wrapper.py:2 가 `from .televuer import TeleVuer` 로 직접 import + 같은
    파일 line 238 이 bare name `TeleVuer(...)` 호출. 또 televuer/__init__.py
    가 `from .televuer import TeleVuer` 로 re-export. Python `from X import Y`
    는 import 시점에 local namespace 에 캐시되므로 세 군데 모두 patch 필요.
    """
    import televuer as _tv_pkg
    import televuer.televuer as _tv_mod
    import televuer.tv_wrapper as _wrapper_mod
    from bridge_pose_store import BridgePoseStore

    _tv_mod.TeleVuer = BridgePoseStore
    _wrapper_mod.TeleVuer = BridgePoseStore
    _tv_pkg.TeleVuer = BridgePoseStore
    print("[run_teleop_ur10e_ws] televuer.TeleVuer / tv_wrapper.TeleVuer / 패키지 "
          "모두 BridgePoseStore 로 patch", flush=True)


def _sanity_check() -> None:
    """conda env tv 활성화 + 핵심 import 사전 확인 (aiohttp 추가)."""
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env != "tv":
        print(f"[run_teleop_ur10e_ws] ERROR: conda env 'tv' not active (current: '{env or '(none)'}')")
        print("                conda activate tv → source scripts/dds_env.sh → 재시도")
        sys.exit(2)
    try:
        import pinocchio.casadi  # noqa: F401
    except ImportError as e:
        print(f"[run_teleop_ur10e_ws] ERROR: pinocchio.casadi import 실패 — {e}")
        print("                unset PYTHONPATH 후 재시도")
        sys.exit(3)
    try:
        import dex_retargeting  # noqa: F401
    except ImportError:
        print("[run_teleop_ur10e_ws] ERROR: dex_retargeting 미설치")
        print("                INSTALL_DEX_RETARGETING=1 bash scripts/install.sh")
        sys.exit(4)
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("[run_teleop_ur10e_ws] ERROR: aiohttp 미설치 (BridgePoseStore ws server 필수)")
        print("                pip install aiohttp")
        sys.exit(5)


# ─── main ──────────────────────────────────────────────────────────────────

# state machine — run_teleop_ur10e.py 와 동일
START = False
STOP = False
READY = False
RECALIBRATE = False
PAUSED = False


def on_press(key):
    global START, STOP, RECALIBRATE, PAUSED
    if key == "r":
        START = True
        RECALIBRATE = True
    elif key == "c":
        RECALIBRATE = True
        print("[on_press] 'c' pressed — recalibrate scheduled.", flush=True)
    elif key == "p":
        PAUSED = not PAUSED
        if PAUSED:
            print("[on_press] ⏸  paused — robot 명령 정지. 손 새 위치로 옮긴 후 'p' 다시 누르면 resume + 자동 recalibrate.", flush=True)
        else:
            RECALIBRATE = True
            print("[on_press] ▶  resumed — recalibrate scheduled.", flush=True)
    elif key == "q":
        START = False
        STOP = True
    else:
        print(f"[on_press] {key} pressed, no action.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="UR10e + DG-5F teleop — Galaxy XR ws bridge 변형",
    )
    parser.add_argument("--port", type=int, default=8013,
                        help="ws bridge port (XR_BRIDGE_PORT env). default 8013")
    parser.add_argument("--frequency", type=float, default=30.0,
                        help="main loop control frequency")
    parser.add_argument("--input-mode", choices=["hand", "controller"], default="hand")
    parser.add_argument("--display-mode", choices=["immersive", "ego", "pass-through"],
                        default="immersive")
    parser.add_argument("--img-server-ip", type=str, default="localhost",
                        help="sim host image_server IP (보고서 §1.4 head/right_wrist)")
    parser.add_argument("--network-interface", type=str, default=None,
                        help="CycloneDDS network interface")
    parser.add_argument("--sim", action="store_true", default=True,
                        help="IsaacSim mode (보고서 §2: ChannelFactoryInitialize(1))")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Position scale factor for relative motion. "
                             "1.0 = 1:1 (사용자 손 10cm → robot 10cm). "
                             ">1.0 = robot 더 크게 움직임. Rotation 은 항상 1:1.")
    args = parser.parse_args()

    print(f"[run_teleop_ur10e_ws] args: {args}", flush=True)

    # 1) sanity check
    _sanity_check()

    # 2) BridgePoseStore monkey-patch — TeleVuerWrapper import 전에 (env var 먼저)
    os.environ["XR_BRIDGE_PORT"] = str(args.port)
    _inject_bridge_pose_store()
    print(f"[run_teleop_ur10e_ws] ws bridge port: {args.port}", flush=True)
    print(f"[run_teleop_ur10e_ws] Galaxy XR Chrome → http://localhost:{args.port}/", flush=True)
    print(f"[run_teleop_ur10e_ws] PC: adb reverse tcp:{args.port} tcp:{args.port} 필요", flush=True)

    # 3) DDS init
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    domain = 1 if args.sim else 0
    print(f"[run_teleop_ur10e_ws] ChannelFactoryInitialize({domain})", flush=True)
    ChannelFactoryInitialize(domain, networkInterface=args.network_interface)

    # 4) keyboard listener
    from sshkeyboard import listen_keyboard
    listener_thread = threading.Thread(
        target=listen_keyboard,
        kwargs={"on_press": on_press, "until": None, "sequential": False},
        daemon=True,
    )
    listener_thread.start()

    # 5) image client + camera config (영상 사용 시. ws bridge 자체는 영상 미통합이라
    # 영상은 별도 vuer 측 webrtc/zmq 채널. sim 측 image_server 가 머리/손목 카메라
    # publish 한다고 가정 — Quest 3 케이스와 같음.)
    from teleimager.image_client import ImageClient
    img_client = ImageClient(host=args.img_server_ip, request_bgr=True)
    camera_config = img_client.get_cam_config()
    print(f"[run_teleop_ur10e_ws] camera_config keys: {list(camera_config.keys())}", flush=True)
    xr_need_local_img = not (
        args.display_mode == "pass-through" or camera_config["head_camera"]["enable_webrtc"]
    )

    # 6) televuer wrapper — BridgePoseStore patched 상태로 instantiate
    from televuer import TeleVuerWrapper
    head_webrtc_port = camera_config["head_camera"].get("webrtc_port", 60001)
    tv_wrapper = TeleVuerWrapper(
        use_hand_tracking=args.input_mode == "hand",
        binocular=camera_config["head_camera"]["binocular"],
        img_shape=camera_config["head_camera"]["image_shape"],
        display_mode=args.display_mode,
        zmq=camera_config["head_camera"]["enable_zmq"],
        webrtc=camera_config["head_camera"]["enable_webrtc"],
        webrtc_url=f"https://{args.img_server_ip}:{head_webrtc_port}/offer",
    )

    # 7) UR10e arm IK + controller
    from ur10e_arm_ik import UR10e_ArmIK
    from ur10e_arm_controller import UR10e_ArmController

    print("[run_teleop_ur10e_ws] building UR10e_ArmIK...", flush=True)
    arm_ik = UR10e_ArmIK(verbose=True)
    print("[run_teleop_ur10e_ws] starting UR10e_ArmController...", flush=True)
    arm_ctrl = UR10e_ArmController(simulation_mode=args.sim)

    # 8) DG-5F controller (single-hand right)
    from dg5f_controller import DG5F_Controller, DG5F_Num_Motors

    right_hand_pos_array = Array("d", 75, lock=True)
    hand_data_lock = Lock()
    hand_state_array = Array("d", DG5F_Num_Motors, lock=False)
    hand_action_array = Array("d", DG5F_Num_Motors, lock=False)
    print("[run_teleop_ur10e_ws] starting DG5F_Controller...", flush=True)
    hand_ctrl = DG5F_Controller(
        right_hand_pos_array,
        hand_data_lock=hand_data_lock,
        hand_state_array_out=hand_state_array,
        hand_action_array_out=hand_action_array,
        fps=100.0,
        simulation_mode=args.sim,
    )

    # 9) sim 전용 publisher (scene reset)
    if args.sim:
        from unitree_sdk2py.core.channel import ChannelPublisher
        from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
        reset_pose_publisher = ChannelPublisher("rt/reset_pose/cmd", String_)
        reset_pose_publisher.Init()

    # 10) wait for [r]
    print("─" * 60, flush=True)
    print("🟢  Press [r] to start syncing Galaxy XR hand → UR10e + DG-5F", flush=True)
    print("⏸   Press [p] to pause/resume (resume 시 자동 recalibrate)", flush=True)
    print("🟡  Press [c] for immediate recalibrate (jump 가능)", flush=True)
    print("🔴  Press [q] to stop and exit", flush=True)
    print(f"📐  Position scale factor: {args.scale}  (rotation 은 항상 1:1)", flush=True)
    print(f"🌐  Galaxy XR: http://localhost:{args.port}/ + Enter VR/AR + 손 들이밀기", flush=True)
    print("⚠️   adb reverse tcp:{port} tcp:{port} (ws bridge) + 60001/60003 (영상) 확인".format(port=args.port), flush=True)
    print("─" * 60, flush=True)
    global READY
    READY = True

    while not START and not STOP:
        time.sleep(0.033)
        if camera_config["head_camera"]["enable_zmq"] and xr_need_local_img:
            head_img = img_client.get_head_frame()
            tv_wrapper.render_to_xr(head_img)

    if STOP:
        print("[run_teleop_ur10e_ws] stop before sync, exiting.", flush=True)
        _shutdown(img_client, tv_wrapper)
        return 0

    print("─" * 60, flush=True)
    print("🚀  Start Tracking", flush=True)
    print("─" * 60, flush=True)
    arm_ctrl.speed_gradual_max()

    # 11) main loop with relative motion (run_teleop_ur10e.py 와 동일)
    dummy_left_wrist = np.eye(4)
    origin_user_pose = None
    origin_robot_pose = None
    global RECALIBRATE
    try:
        while not STOP:
            t0 = time.time()

            if camera_config["head_camera"]["enable_zmq"]:
                if xr_need_local_img:
                    head_img = img_client.get_head_frame()
                    tv_wrapper.render_to_xr(head_img)

            tele_data = tv_wrapper.get_tele_data()

            if args.input_mode == "hand":
                with right_hand_pos_array.get_lock():
                    right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()

            if PAUSED:
                elapsed = time.time() - t0
                time.sleep(max(0, 1.0 / args.frequency - elapsed))
                continue

            current_q = arm_ctrl.get_current_dual_arm_q()
            current_dq = arm_ctrl.get_current_dual_arm_dq()

            if RECALIBRATE:
                origin_user_pose = tele_data.right_wrist_pose.copy()
                origin_robot_pose = arm_ik.forward_kinematics(current_q).homogeneous
                print(f"[run_teleop_ur10e_ws] calibrated.\n"
                      f"  user origin p = {origin_user_pose[:3, 3]}\n"
                      f"  robot origin p = {origin_robot_pose[:3, 3]}", flush=True)
                RECALIBRATE = False
                target_pose = origin_robot_pose
            else:
                curr_user = tele_data.right_wrist_pose
                delta_p = (curr_user[:3, 3] - origin_user_pose[:3, 3]) * args.scale
                R_delta = curr_user[:3, :3] @ origin_user_pose[:3, :3].T
                target_pose = np.eye(4)
                target_pose[:3, 3] = origin_robot_pose[:3, 3] + delta_p
                target_pose[:3, :3] = R_delta @ origin_robot_pose[:3, :3]

            sol_q, sol_tauff = arm_ik.solve_ik(
                dummy_left_wrist,
                target_pose,
                current_lr_arm_motor_q=current_q,
                current_lr_arm_motor_dq=current_dq,
            )
            arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)

            elapsed = time.time() - t0
            time.sleep(max(0, 1.0 / args.frequency - elapsed))
    except KeyboardInterrupt:
        print("[run_teleop_ur10e_ws] KeyboardInterrupt", flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        _shutdown(img_client, tv_wrapper, arm_ctrl=arm_ctrl)

    return 0


def _shutdown(img_client=None, tv_wrapper=None, arm_ctrl=None):
    print("[run_teleop_ur10e_ws] shutdown...", flush=True)
    try:
        if arm_ctrl is not None:
            arm_ctrl.ctrl_dual_arm_go_home()
    except Exception as e:
        print(f"[run_teleop_ur10e_ws] go_home fail: {e}")
    try:
        from sshkeyboard import stop_listening
        stop_listening()
    except Exception:
        pass
    try:
        if img_client is not None:
            img_client.close()
    except Exception as e:
        print(f"[run_teleop_ur10e_ws] img_client close fail: {e}")
    try:
        if tv_wrapper is not None:
            tv_wrapper.close()
    except Exception as e:
        print(f"[run_teleop_ur10e_ws] tv_wrapper close fail: {e}")
    print("[run_teleop_ur10e_ws] exit", flush=True)


if __name__ == "__main__":
    sys.exit(main())
