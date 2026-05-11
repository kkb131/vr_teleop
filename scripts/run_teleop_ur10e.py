#!/usr/bin/env python3
"""UR10e + DG-5F 전용 teleop entry (Quest 3 / Galaxy XR → IsaacSim sim).

upstream xr_teleoperate/teleop/teleop_hand_and_arm.py 의 G1/H1 + dex3/inspire
분기를 그대로 두고, UR10e + DG-5F 전용 새 entry 신규 작성. upstream 코드 무수정.

본 entry 책임:
  1. run_teleop.py wrapper 패턴 monkey-patches 적용:
       - vuer cert=None (HTTP 모드 — adb reverse USB 환경 cert 신뢰 우회)
       - TeleVuer.main_image_*_webrtc retry-on-ws-disconnect
  2. _sanity_check (conda env tv + pinocchio.casadi + dex_retargeting)
  3. DDS init (ChannelFactoryInitialize(1) — sim 보고서 §2)
  4. TeleVuerWrapper (Quest 3 hand stream — display_mode='immersive', webrtc=True)
  5. ImageClient (rt/lowstate-host의 image_server: head=55555, right_wrist=55557)
  6. UR10e_ArmIK (Pinocchio + CasADi) + UR10e_ArmController (rt/lowcmd publisher)
  7. DG5F_Controller (Quest 3 right hand → 6 retarget joint → 20-joint expansion
     → rt/dg5f/cmd publisher)
  8. main loop (30Hz default):
       - tele_data = tv.get_tele_data()
       - sol_q = ik.solve_ik(dummy_left, tele_data.right_wrist_pose, current_q)
       - arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)
       - right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()
       - DG5F_Controller 자식 process 가 retargeting + publish 자동

Usage:
  conda activate tv
  source scripts/dds_env.sh   # ROS_DOMAIN_ID=1 + cyclonedds
  python scripts/run_teleop_ur10e.py                # default: --http --sim
  python scripts/run_teleop_ur10e.py --no-http      # HTTPS 모드 (cert 필요)

사용자 키:
  r — start sync (Quest 3 손동작을 UR10e/DG-5F 로 전달 시작)
  q — quit
"""
from __future__ import annotations

import argparse
import asyncio
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


# ─── wrapper-style monkey-patches (run_teleop.py 패턴) ─────────────────────

def _apply_http_monkey_patch() -> None:
    """televuer.Vuer 를 cert/key=None 강제 서브클래스로 교체 → plain HTTP."""
    import televuer.televuer as _tv_mod
    _OrigVuer = _tv_mod.Vuer

    class _PlainHTTPVuer(_OrigVuer):
        def __init__(self, *args, **kwargs):
            kwargs["cert"] = None
            kwargs["key"] = None
            super().__init__(*args, **kwargs)

    _tv_mod.Vuer = _PlainHTTPVuer
    print("[run_teleop_ur10e] HTTP mode — vuer cert/key forced to None", flush=True)


def _patch_image_spawn_retry() -> None:
    """TeleVuer 의 영상 spawn func 8 개를 ws-race retry wrapper 로 교체."""
    import televuer.televuer as _tv_mod
    _OrigTV = _tv_mod.TeleVuer

    def _wrap(orig_method):
        async def _retried(self, session):
            for attempt in range(20):
                try:
                    return await orig_method(self, session)
                except AssertionError as e:
                    if "Websocket session is missing" in str(e):
                        print(f"[run_teleop_ur10e] image spawn retry {attempt + 1}/20", flush=True)
                        await asyncio.sleep(0.5)
                        continue
                    raise
            print("[run_teleop_ur10e] WARN: image spawn 20 회 모두 실패", flush=True)
        _retried.__name__ = getattr(orig_method, "__name__", "_retried")
        return _retried

    patched = 0
    for name in (
        "main_image_monocular_webrtc", "main_image_binocular_webrtc",
        "main_image_monocular_zmq", "main_image_binocular_zmq",
        "main_image_monocular_webrtc_ego", "main_image_binocular_webrtc_ego",
        "main_image_monocular_zmq_ego", "main_image_binocular_zmq_ego",
    ):
        if hasattr(_OrigTV, name):
            setattr(_OrigTV, name, _wrap(getattr(_OrigTV, name)))
            patched += 1
    print(f"[run_teleop_ur10e] image spawn func wrapped ({patched} methods)", flush=True)


def _sanity_check() -> None:
    """conda env tv 활성화 + 핵심 import 사전 확인."""
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env != "tv":
        print(f"[run_teleop_ur10e] ERROR: conda env 'tv' not active (current: '{env or '(none)'}')")
        print("            conda activate tv 후 재시도")
        sys.exit(2)
    try:
        import pinocchio.casadi  # noqa
    except ImportError as e:
        print(f"[run_teleop_ur10e] ERROR: pinocchio.casadi import 실패 — {e}")
        print("            unset PYTHONPATH 후 재시도 (ROS Humble pinocchio 가림 의심)")
        sys.exit(3)
    try:
        import dex_retargeting  # noqa
    except ImportError:
        print("[run_teleop_ur10e] ERROR: dex_retargeting 미설치")
        print("            INSTALL_DEX_RETARGETING=1 bash scripts/install.sh")
        sys.exit(4)


# ─── main ──────────────────────────────────────────────────────────────────

# state machine (upstream teleop_hand_and_arm.py 패턴)
START = False
STOP = False
READY = False
# Relative motion origin re-capture flag.
# - 'r' 키 (sync 시작) 시 자동으로 True 로 → 첫 capture
# - 'c' 키 (recalibrate) 시 True 로 → 동작 중 origin 재캡처
RECALIBRATE = False


def on_press(key):
    global START, STOP, RECALIBRATE
    if key == "r":
        START = True
        RECALIBRATE = True   # sync 시작 시점에 첫 origin capture
    elif key == "c":
        RECALIBRATE = True   # 동작 중 재캘리 (현재 사용자 손 위치 = 현재 robot 위치를 새 origin 으로)
        print("[on_press] 'c' pressed — recalibrate scheduled.")
    elif key == "q":
        START = False
        STOP = True
    else:
        print(f"[on_press] {key} pressed, no action.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="UR10e + DG-5F teleop (Quest 3 / Galaxy XR → IsaacSim sim)",
    )
    # wrapper-style options
    parser.add_argument("--http", dest="http", action="store_true", default=True,
                        help="(default) plain HTTP 모드 — vuer cert/key None 강제")
    parser.add_argument("--no-http", dest="http", action="store_false",
                        help="HTTPS 모드 강제")
    # teleop options
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
                             "1.0 = 직관적 1:1 (사용자 손 10cm → robot 10cm). "
                             ">1.0 = robot 더 크게 움직임. Rotation 은 항상 1:1.")
    args = parser.parse_args()

    print(f"[run_teleop_ur10e] args: {args}", flush=True)

    # 1) sanity check
    _sanity_check()

    # 2) monkey-patches BEFORE televuer import
    if args.http:
        _apply_http_monkey_patch()
    _patch_image_spawn_retry()

    # 3) DDS init
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    domain = 1 if args.sim else 0
    print(f"[run_teleop_ur10e] ChannelFactoryInitialize({domain})", flush=True)
    ChannelFactoryInitialize(domain, networkInterface=args.network_interface)

    # 4) keyboard listener
    from sshkeyboard import listen_keyboard, stop_listening
    listener_thread = threading.Thread(
        target=listen_keyboard,
        kwargs={"on_press": on_press, "until": None, "sequential": False},
        daemon=True,
    )
    listener_thread.start()

    # 5) image client + camera config
    from teleimager.image_client import ImageClient
    img_client = ImageClient(host=args.img_server_ip, request_bgr=True)
    camera_config = img_client.get_cam_config()
    print(f"[run_teleop_ur10e] camera_config keys: {list(camera_config.keys())}", flush=True)
    # left_wrist 는 sim 측 의도적 disable (보고서 §1.4)
    xr_need_local_img = not (
        args.display_mode == "pass-through" or camera_config["head_camera"]["enable_webrtc"]
    )

    # 6) televuer wrapper
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

    print("[run_teleop_ur10e] building UR10e_ArmIK...", flush=True)
    arm_ik = UR10e_ArmIK(verbose=True)
    print("[run_teleop_ur10e] starting UR10e_ArmController...", flush=True)
    arm_ctrl = UR10e_ArmController(simulation_mode=args.sim)

    # 8) DG-5F controller (single-hand right)
    from dg5f_controller import DG5F_Controller, DG5F_Num_Motors

    right_hand_pos_array = Array("d", 75, lock=True)  # 25 joint × 3 xyz
    hand_data_lock = Lock()
    hand_state_array = Array("d", DG5F_Num_Motors, lock=False)
    hand_action_array = Array("d", DG5F_Num_Motors, lock=False)
    print("[run_teleop_ur10e] starting DG5F_Controller...", flush=True)
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
    print("🟢  Press [r] to start syncing Quest 3 hand → UR10e + DG-5F", flush=True)
    print("🟡  Press [c] to recalibrate (현재 손 위치 = 현재 robot 위치 새 origin)", flush=True)
    print("🔴  Press [q] to stop and exit", flush=True)
    print(f"📐  Position scale factor: {args.scale}  (rotation 은 항상 1:1)", flush=True)
    print("⚠️   Quest 3 USB-C + adb reverse tcp:8012/60001/60003 확인", flush=True)
    print("─" * 60, flush=True)
    global READY
    READY = True

    while not START and not STOP:
        time.sleep(0.033)
        # display_mode != pass-through 일 때 image push (G1 패턴)
        if camera_config["head_camera"]["enable_zmq"] and xr_need_local_img:
            head_img = img_client.get_head_frame()
            tv_wrapper.render_to_xr(head_img)

    if STOP:
        print("[run_teleop_ur10e] stop before sync, exiting.", flush=True)
        _shutdown(img_client, tv_wrapper)
        return 0

    print("─" * 60, flush=True)
    print("🚀  Start Tracking", flush=True)
    print("─" * 60, flush=True)
    arm_ctrl.speed_gradual_max()

    # 11) main loop with relative motion (사용자 손 origin ↔ robot origin)
    dummy_left_wrist = np.eye(4)   # single-arm: left 무시
    origin_user_pose = None        # Quest 3 wrist (4,4) at calibrate 시점
    origin_robot_pose = None       # UR10e wrist_3_link (4,4) at calibrate 시점
    global RECALIBRATE
    try:
        while not STOP:
            t0 = time.time()

            # 11.1) image (record / webrtc-disabled path)
            if camera_config["head_camera"]["enable_zmq"]:
                if xr_need_local_img:
                    head_img = img_client.get_head_frame()
                    tv_wrapper.render_to_xr(head_img)

            # 11.2) Quest 3 hand pose
            tele_data = tv_wrapper.get_tele_data()

            # 11.3) right hand → DG5F controller (shared array)
            if args.input_mode == "hand":
                with right_hand_pos_array.get_lock():
                    right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()

            # 11.4) current arm state → IK seed
            current_q = arm_ctrl.get_current_dual_arm_q()
            current_dq = arm_ctrl.get_current_dual_arm_dq()

            # 11.5) Relative motion calibration
            # 'r' 키 (첫 sync) 또는 'c' 키 (재캘리) 시 origin 재캡처.
            if RECALIBRATE:
                origin_user_pose = tele_data.right_wrist_pose.copy()
                origin_robot_pose = arm_ik.forward_kinematics(current_q).homogeneous
                print(f"[run_teleop_ur10e] calibrated.\n"
                      f"  user origin p = {origin_user_pose[:3, 3]}\n"
                      f"  robot origin p = {origin_robot_pose[:3, 3]}", flush=True)
                RECALIBRATE = False
                # 캘리 직후 target = robot origin 그대로 (지터 회피).
                target_pose = origin_robot_pose
            else:
                # user delta in world frame
                curr_user = tele_data.right_wrist_pose
                delta_p = (curr_user[:3, 3] - origin_user_pose[:3, 3]) * args.scale
                R_delta = curr_user[:3, :3] @ origin_user_pose[:3, :3].T

                # robot target = robot origin + user delta (translation, rotation)
                target_pose = np.eye(4)
                target_pose[:3, 3] = origin_robot_pose[:3, 3] + delta_p
                target_pose[:3, :3] = R_delta @ origin_robot_pose[:3, :3]

            # 11.6) IK 풀이 (relative target)
            sol_q, sol_tauff = arm_ik.solve_ik(
                dummy_left_wrist,
                target_pose,
                current_lr_arm_motor_q=current_q,
                current_lr_arm_motor_dq=current_dq,
            )

            # 11.7) arm DDS publish
            arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)

            # 11.8) frequency control
            elapsed = time.time() - t0
            time.sleep(max(0, 1.0 / args.frequency - elapsed))
    except KeyboardInterrupt:
        print("[run_teleop_ur10e] KeyboardInterrupt", flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        _shutdown(img_client, tv_wrapper, arm_ctrl=arm_ctrl)

    return 0


def _shutdown(img_client=None, tv_wrapper=None, arm_ctrl=None):
    print("[run_teleop_ur10e] shutdown...", flush=True)
    try:
        if arm_ctrl is not None:
            arm_ctrl.ctrl_dual_arm_go_home()
    except Exception as e:
        print(f"[run_teleop_ur10e] go_home fail: {e}")
    try:
        from sshkeyboard import stop_listening
        stop_listening()
    except Exception:
        pass
    try:
        if img_client is not None:
            img_client.close()
    except Exception as e:
        print(f"[run_teleop_ur10e] img_client close fail: {e}")
    try:
        if tv_wrapper is not None:
            tv_wrapper.close()
    except Exception as e:
        print(f"[run_teleop_ur10e] tv_wrapper close fail: {e}")
    print("[run_teleop_ur10e] exit", flush=True)


if __name__ == "__main__":
    sys.exit(main())
