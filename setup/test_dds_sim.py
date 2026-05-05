#!/usr/bin/env python3
"""unitree_sim_isaaclab ↔ xr_teleoperate 통신 자동 진단.

INTEGRATION_FOR_XR_TELEOPERATE.md §8의 세 가지 verification을 한 번에 수행:
  A. DDS LowState subscribe (~280 msgs in 3s ≈ 94 Hz)
  B. ZMQ head camera frame (port 55555)
  C. passive LowCmd round-trip publish

전제: sim host에서 sim_main.py가 이미 돌고 있어야 함.

Usage:
  source setup/dds_env.sh        # ROS_DOMAIN_ID=1 + cyclonedds 강제
  python3 setup/test_dds_sim.py  # 모든 단계 자동 실행
"""
from __future__ import annotations

import argparse
import os
import sys
import time

DEFAULT_DOMAIN = 1
EXPECTED_LOWSTATE_HZ = 94
EXPECTED_LOWSTATE_3S = 280  # 3 * 94 = 282
LOWSTATE_MIN_OK = 240        # 약간의 변동 허용

CAMERA_PORTS = {
    "head":  ("tcp://127.0.0.1:55555", (480, 640)),
    "left":  ("tcp://127.0.0.1:55556", (480, 640)),
    "right": ("tcp://127.0.0.1:55557", (480, 640)),
}


# ─── colors ──────────────────────────────────────────────────────────────
if sys.stdout.isatty():
    R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"; B = "\033[34m"; X = "\033[0m"
else:
    R = G = Y = B = X = ""

def ok(msg):   print(f"{G}[OK]{X}   {msg}", flush=True)
def warn(msg): print(f"{Y}[WARN]{X} {msg}", flush=True)
def fail(msg): print(f"{R}[FAIL]{X} {msg}", flush=True)
def hdr(msg):  print(f"\n{B}── {msg} ──{X}", flush=True)


def check_env() -> int:
    hdr("0. DDS 환경 변수")
    rmw = os.environ.get("RMW_IMPLEMENTATION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    fails = 0
    if rmw == "rmw_cyclonedds_cpp":
        ok(f"RMW_IMPLEMENTATION={rmw}")
    else:
        warn(f"RMW_IMPLEMENTATION={rmw or '(unset)'} — 'rmw_cyclonedds_cpp' 권장. source setup/dds_env.sh")
    if domain == str(DEFAULT_DOMAIN):
        ok(f"ROS_DOMAIN_ID={domain}")
    else:
        warn(f"ROS_DOMAIN_ID={domain or '(unset)'} — sim_main.py는 {DEFAULT_DOMAIN}을 강제. ChannelFactoryInitialize({DEFAULT_DOMAIN})로 명시 호출하므로 동작은 함")
    return fails


def test_lowstate(duration: float = 3.0) -> bool:
    hdr(f"A. DDS LowState subscribe ({duration:.0f}s)")
    try:
        from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    except Exception as e:
        fail(f"unitree_sdk2py import 실패: {e}")
        return False

    ChannelFactoryInitialize(DEFAULT_DOMAIN)
    counts = {"n": 0}
    def cb(msg): counts["n"] += 1
    sub = ChannelSubscriber("rt/lowstate", LowState_)
    sub.Init(cb, 10)
    print(f"     ... {duration:.0f}s 동안 rt/lowstate 수신 카운트")
    time.sleep(duration)
    sub.Close()
    n = counts["n"]
    rate = n / duration
    expected = int(EXPECTED_LOWSTATE_HZ * duration)
    if n == 0:
        fail(f"메시지 0개 수신 — sim 미실행 또는 DDS 도메인 mismatch")
        return False
    elif rate < EXPECTED_LOWSTATE_HZ * 0.7:
        warn(f"{n} msgs ({rate:.1f} Hz, expected ~{EXPECTED_LOWSTATE_HZ} Hz) — 통신은 되지만 sim frame rate 낮음")
        return True
    else:
        ok(f"{n} msgs ({rate:.1f} Hz, expected ~{EXPECTED_LOWSTATE_HZ} Hz)")
        return True


def test_camera(name: str, addr: str, expected_shape) -> bool:
    try:
        import zmq
    except Exception as e:
        fail(f"pyzmq import 실패: {e}")
        return False
    ctx = zmq.Context()
    s = ctx.socket(zmq.SUB)
    s.connect(addr)
    s.setsockopt_string(zmq.SUBSCRIBE, "")
    s.setsockopt(zmq.RCVTIMEO, 5000)
    try:
        data = s.recv()
        ok(f"{name}_camera @ {addr}: {len(data):,} bytes")
        return True
    except zmq.error.Again:
        fail(f"{name}_camera @ {addr}: timeout — sim에 --enable_cameras 옵션 켜졌는지 확인")
        return False
    finally:
        s.close(); ctx.term()


def test_cameras() -> int:
    hdr("B. ZMQ camera frames")
    n_ok = 0
    for name, (addr, shape) in CAMERA_PORTS.items():
        if test_camera(name, addr, shape):
            n_ok += 1
    return n_ok


def test_round_trip() -> bool:
    hdr("C. passive LowCmd round-trip (50 msgs / 1s)")
    try:
        from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, MotorCmd_
    except Exception as e:
        fail(f"unitree_sdk2py import 실패: {e}")
        return False

    ChannelFactoryInitialize(DEFAULT_DOMAIN)
    pub = ChannelPublisher("rt/lowcmd", LowCmd_)
    pub.Init()
    zero = LowCmd_(
        mode_pr=0, mode_machine=0,
        motor_cmd=[MotorCmd_(mode=0, q=0, dq=0, tau=0, kp=0, kd=0, reserve=0)
                   for _ in range(35)],
        reserve=[0, 0, 0, 0], crc=0,
    )
    for _ in range(50):
        pub.Write(zero)
        time.sleep(0.02)
    ok("50 passive lowcmds published — sim 콘솔에 에러 없으면 round-trip OK")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--skip-cameras", action="store_true", help="ZMQ camera 점검 건너뛰기")
    p.add_argument("--skip-lowcmd", action="store_true", help="LowCmd publish 점검 건너뛰기")
    p.add_argument("--lowstate-duration", type=float, default=3.0, help="LowState subscribe 시간 (초)")
    args = p.parse_args()

    print(f"{B}══ unitree_sim_isaaclab ↔ xr_teleoperate 통신 진단 ══{X}")
    check_env()

    results = {}
    results["lowstate"] = test_lowstate(args.lowstate_duration)
    if not args.skip_cameras:
        n_cam = test_cameras()
        results["camera"] = (n_cam == len(CAMERA_PORTS))
        if 0 < n_cam < len(CAMERA_PORTS):
            warn(f"{n_cam}/{len(CAMERA_PORTS)}개 카메라만 응답 — sim의 wrist camera 활성화 여부 확인")
    if not args.skip_lowcmd:
        results["lowcmd"] = test_round_trip()

    hdr("요약")
    n_pass = sum(1 for v in results.values() if v)
    n_total = len(results)
    if n_pass == n_total:
        ok(f"{n_pass}/{n_total} 단계 통과 — Day 3(teleop_hand_and_arm.py 실행) 진입 가능")
        return 0
    else:
        fail(f"{n_pass}/{n_total} 단계 통과")
        print("\n  다음 액션:")
        print("    - sim 실행 중인지: ps aux | grep sim_main.py")
        print("    - DDS env: source setup/dds_env.sh")
        print("    - 다른 host로 sim이 옮겨갔다면 cyclonedds.xml로 unicast peers 설정 (INTEGRATION §2)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
