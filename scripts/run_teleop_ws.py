#!/usr/bin/env python3
"""xr_teleoperate teleop_hand_and_arm.py 의 Galaxy XR ws bridge 통합 wrapper.

배경: Galaxy XR Chrome 에서 vuer 0.0.60 client React 가 immersive 진입 후 publish
freeze (R3F XR-RAF 전환 실패 가설) 되는 문제로, vuer 의존 경로 전체를 우회하는
자체 ws bridge (scripts/bridge_pose_store.py + assets/webxr_to_pose.html) 가 검증됨.

이 wrapper 는 그 ws bridge 를 teleop_hand_and_arm.py 에 inject:
- televuer.televuer.TeleVuer 클래스를 scripts/bridge_pose_store.BridgePoseStore 로
  monkey-patch
- TeleVuerWrapper.__init__ 안에서 self.tvuer = TeleVuer(...) 호출 시 우리
  BridgePoseStore 인스턴스가 생성됨 (자체 ws server 자동 시작)
- TeleVuerWrapper 의 좌표 변환/smoothing 은 그대로 유지 — TeleVuer interface 100%
  mimick 이라 wrapper 측에서 차이를 인지 못 함

옵션 A 범위: pose-only 통합. 영상은 별도 모니터링 (옵션 B1/B2 에서 영상 통합 진입).

Usage:
  conda activate tv
  source scripts/dds_env.sh
  adb reverse tcp:8013 tcp:8013        # ws bridge port (XR_BRIDGE_PORT)
  python3 scripts/run_teleop_ws.py --ee dex3 --sim
  # Galaxy XR Chrome → http://localhost:8013/ → Enter VR/AR → 손 들이밀기 → r 키 동기화

cf. [docs/galaxy_xr_ws_bridge_integration.md](../docs/galaxy_xr_ws_bridge_integration.md)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _parse_wrapper_args() -> tuple[argparse.Namespace, list[str]]:
    p = argparse.ArgumentParser(
        description="teleop_hand_and_arm.py + Galaxy XR ws bridge wrapper",
        add_help=False,
    )
    p.add_argument("--port", type=int, default=8013,
                   help="ws bridge port (XR_BRIDGE_PORT env). default 8013")
    p.add_argument("--upstream-help", action="store_true",
                   help="업스트림 teleop_hand_and_arm.py --help 표시")
    return p.parse_known_args()


def _inject_bridge_pose_store() -> None:
    """televuer.televuer.TeleVuer 클래스를 BridgePoseStore 로 monkey-patch.

    TeleVuerWrapper.__init__ (tv_wrapper.py:195) 안에서 `self.tvuer = TeleVuer(...)`
    호출 시 우리 BridgePoseStore 인스턴스가 만들어진다. BridgePoseStore 는 자체
    aiohttp ws server (port 8013) 를 background thread 로 자동 시작 + TeleVuer 와
    동일 시그니처/property/method 를 제공하므로 TeleVuerWrapper 측 코드는 변경 zero.
    """
    # scripts/ 디렉토리를 sys.path 에 추가 (bridge_pose_store import 위해)
    setup_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(setup_dir))

    import televuer.televuer as _tv_mod
    from bridge_pose_store import BridgePoseStore

    _tv_mod.TeleVuer = BridgePoseStore
    print("[run_teleop_ws] televuer.TeleVuer → BridgePoseStore monkey-patched", flush=True)


def _ensure_sim_defaults(passthrough: list[str]) -> list[str]:
    """run_teleop.py 와 동일 — --img-server-ip default 보정.

    옵션 A 에서는 영상 미통합이라 이 값이 사실상 안 쓰이지만 teleop_hand_and_arm.py
    의 argparse 가 이 인자를 요구하거나 cam config 로딩에 사용할 수도 있어
    안전하게 'localhost' 로 채워둠.
    """
    if not any(a == "--img-server-ip" or a.startswith("--img-server-ip=") for a in passthrough):
        passthrough = ["--img-server-ip", "localhost", *passthrough]
        print("[run_teleop_ws] inserted --img-server-ip localhost (default)", flush=True)
    return passthrough


def _resolve_teleop_path() -> Path:
    here = Path(__file__).resolve().parent
    teleop = here.parent / "xr_teleoperate" / "teleop" / "teleop_hand_and_arm.py"
    if not teleop.exists():
        print(f"[run_teleop_ws] ERROR: {teleop} 없음 — bash scripts/install.sh 먼저", file=sys.stderr)
        sys.exit(1)
    return teleop


def _sanity_check() -> None:
    """conda env tv 활성화 + 핵심 import 사전 확인 — fail-fast.

    run_teleop.py 의 sanity check 와 동일 + aiohttp (BridgePoseStore 의존성) 추가.
    """
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env != "tv":
        print(f"[run_teleop_ws] ERROR: conda env 'tv' not active (current: '{env or '(none)'}')")
        print("                conda activate tv  → source scripts/dds_env.sh  → 재시도")
        sys.exit(2)
    try:
        import pinocchio.casadi  # noqa: F401
    except ImportError as e:
        print(f"[run_teleop_ws] ERROR: pinocchio.casadi import 실패 — {e}")
        print("                unset PYTHONPATH 후 재시도 또는 conda env tv 재생성")
        sys.exit(3)
    try:
        import dex_retargeting  # noqa: F401
    except ImportError:
        print("[run_teleop_ws] ERROR: dex_retargeting 미설치 (G1+Dex3-1 hand control 필수)")
        print("                INSTALL_DEX_RETARGETING=1 bash scripts/install.sh")
        sys.exit(4)
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("[run_teleop_ws] ERROR: aiohttp 미설치 (BridgePoseStore ws server 필수)")
        print("                pip install aiohttp")
        sys.exit(5)


def main() -> int:
    wrapper_args, passthrough = _parse_wrapper_args()

    if not wrapper_args.upstream_help:
        _sanity_check()

    teleop_path = _resolve_teleop_path()

    # teleop_hand_and_arm.py 가 from . import ... 를 안 쓰는 단일 스크립트라
    # sys.path 에 그 디렉토리 필요
    sys.path.insert(0, str(teleop_path.parent))

    if wrapper_args.upstream_help:
        passthrough = ["--help"]
    else:
        passthrough = _ensure_sim_defaults(passthrough)

    # BridgePoseStore monkey-patch + port 환경변수 — teleop_hand_and_arm.py import 전에
    if not wrapper_args.upstream_help:
        os.environ["XR_BRIDGE_PORT"] = str(wrapper_args.port)
        _inject_bridge_pose_store()
        print(f"[run_teleop_ws] ws bridge port: {wrapper_args.port}", flush=True)
        print(f"[run_teleop_ws] Galaxy XR Chrome → http://localhost:{wrapper_args.port}/", flush=True)
        print(f"[run_teleop_ws] PC: adb reverse tcp:{wrapper_args.port} tcp:{wrapper_args.port} 필요", flush=True)

    # DDS env 안내
    if os.environ.get("ROS_DOMAIN_ID") != "1":
        print("[run_teleop_ws] WARN: ROS_DOMAIN_ID != 1. 'source scripts/dds_env.sh' 권장", flush=True)

    # argv 재조립
    sys.argv = [str(teleop_path), *passthrough]
    print(f"[run_teleop_ws] sys.argv = {sys.argv}", flush=True)

    # cwd → xr_teleoperate/teleop/ (robot_arm_ik.py 의 '../assets/g1/...' cwd-relative)
    os.chdir(teleop_path.parent)
    print(f"[run_teleop_ws] cwd → {os.getcwd()}", flush=True)

    import runpy
    runpy.run_path(str(teleop_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
