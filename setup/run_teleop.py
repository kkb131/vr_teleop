#!/usr/bin/env python3
"""xr_teleoperate teleop_hand_and_arm.py 우리 환경용 wrapper.

업스트림 teleop_hand_and_arm.py는 cert/key를 자동 검색해 HTTPS+WSS 강제 부팅하므로
Galaxy XR/Quest 3 Chrome이 self-signed cert를 거부할 때 막힘. Week 2 test_pose_only.py
에서 검증된 동일 기법(televuer.televuer.Vuer를 cert=None 강제 monkey-patch)을 적용해
plain HTTP로 부팅하고, 나머지 인자는 그대로 teleop_hand_and_arm.py에 위임.

Usage:
  source setup/dds_env.sh        # ROS_DOMAIN_ID=1 + cyclonedds
  python3 setup/run_teleop.py --ee dex3 --sim   # default --http가 들어감

  # HTTPS 모드 강제 (vuer cert 사용):
  python3 setup/run_teleop.py --no-http --ee dex3 --sim

  # img-server-ip default도 우리가 127.0.0.1로 덮어씀 (INTEGRATION §1 권장):
  python3 setup/run_teleop.py --ee dex3 --sim
  # ↳ 실제 호출:
  #    teleop_hand_and_arm.py --ee dex3 --sim --img-server-ip 127.0.0.1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _parse_wrapper_args() -> tuple[argparse.Namespace, list[str]]:
    p = argparse.ArgumentParser(
        description="teleop_hand_and_arm.py wrapper (--http monkey-patch + sim defaults)",
        add_help=False,
    )
    p.add_argument("--http", dest="http", action="store_true", default=True,
                   help="(default) plain HTTP 모드: vuer cert/key를 None으로 강제 → HTTP fallback")
    p.add_argument("--no-http", dest="http", action="store_false",
                   help="HTTPS 모드 강제 (vuer가 ~/.config/xr_teleoperate/cert.pem 사용)")
    p.add_argument("--upstream-help", action="store_true",
                   help="업스트림 teleop_hand_and_arm.py --help 표시")
    return p.parse_known_args()


def _apply_http_monkey_patch() -> None:
    """televuer.televuer.Vuer를 cert=None 강제하는 서브클래스로 교체 → plain HTTP 부팅."""
    import televuer.televuer as _tv_mod

    _OrigVuer = _tv_mod.Vuer

    class _PlainHTTPVuer(_OrigVuer):
        def __init__(self, *args, **kwargs):
            kwargs["cert"] = None
            kwargs["key"] = None
            super().__init__(*args, **kwargs)

    _tv_mod.Vuer = _PlainHTTPVuer
    print("[run_teleop] HTTP mode (plain) — vuer cert/key forced to None", flush=True)


def _ensure_sim_defaults(passthrough: list[str]) -> list[str]:
    """teleop_hand_and_arm.py의 default가 우리 sim 환경에 안 맞으니 보정.

    우리 환경: 같은 host의 다른 docker container에서 sim_main.py가 돌고 있어
    image server가 localhost에 떠있음. 사용자가 --img-server-ip를 명시하지
    않으면 우리가 'localhost'로 덮어쓴다.

    'localhost' vs '127.0.0.1': 둘 다 loopback이지만 브라우저 cert cache는
    host name별로 분리해 검증함. 사용자가 cert를 'https://localhost:60001'로
    한 번 신뢰하면 webrtc_url='https://localhost:60001/offer'에서 그 cert가
    재사용됨. '127.0.0.1'을 쓰면 별도 신뢰가 필요해 ws disconnect race 유발.
    """
    if not any(a == "--img-server-ip" or a.startswith("--img-server-ip=") for a in passthrough):
        passthrough = ["--img-server-ip", "localhost", *passthrough]
        print("[run_teleop] inserted --img-server-ip localhost (cert 신뢰 host 일치)", flush=True)
    return passthrough


def _resolve_teleop_path() -> Path:
    here = Path(__file__).resolve().parent
    teleop = here.parent / "xr_teleoperate" / "teleop" / "teleop_hand_and_arm.py"
    if not teleop.exists():
        print(f"[run_teleop] ERROR: {teleop} 없음 — bash setup/install.sh 먼저", file=sys.stderr)
        sys.exit(1)
    return teleop


def _patch_image_spawn_retry() -> None:
    """main_image_*_webrtc/zmq spawn func의 session.upsert가 ws disconnect race로
    'AssertionError: Websocket session is missing'을 던질 때 재시도하도록 monkey-patch.

    원본 spawn func (televuer.py:447-481 근처)은 try/except 없이 한 번만 upsert
    하므로 첫 ws가 짧게 끊기면 영상 plane이 영영 client에 등록 안 됨 → VR scene
    안 빈 공간만 보임. 이 wrapper가 AssertionError를 catch해 ws 재연결 시
    spawn func을 다시 시도.
    """
    import asyncio
    import televuer.televuer as _tv_mod
    _OrigTV = _tv_mod.TeleVuer

    def _wrap(orig_method):
        async def _retried(self, session):
            for attempt in range(20):  # 최대 ~10초
                try:
                    return await orig_method(self, session)
                except AssertionError as e:
                    if "Websocket session is missing" in str(e):
                        print(f"[run_teleop] image spawn retry {attempt + 1}/20 (ws disconnect)",
                              flush=True)
                        await asyncio.sleep(0.5)
                        continue
                    raise
            print("[run_teleop] WARN: image spawn 20회 모두 실패 — VR scene 안 영상 안 보일 수 있음",
                  flush=True)
        _retried.__name__ = getattr(orig_method, "__name__", "_retried")
        return _retried

    patched = []
    for name in (
        "main_image_monocular_webrtc",
        "main_image_binocular_webrtc",
        "main_image_monocular_zmq",
        "main_image_binocular_zmq",
        "main_image_monocular_webrtc_ego",
        "main_image_binocular_webrtc_ego",
        "main_image_monocular_zmq_ego",
        "main_image_binocular_zmq_ego",
    ):
        if hasattr(_OrigTV, name):
            setattr(_OrigTV, name, _wrap(getattr(_OrigTV, name)))
            patched.append(name)
    print(f"[run_teleop] image spawn func wrapped with retry-on-ws-disconnect ({len(patched)} methods)",
          flush=True)


def _sanity_check() -> None:
    """conda env tv 활성화 + 핵심 import 사전 확인 — fail-fast 안내.

    teleop_hand_and_arm.py는 깊은 import chain (pinocchio.casadi, dex_retargeting,
    matplotlib 등)을 거치며, 어디 한 곳이 막히면 traceback이 200줄로 쏟아져
    원인 파악이 어려움. wrapper 시작 시점에 핵심 3개를 미리 시도해 즉시
    명확한 에러로 abort.
    """
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env != "tv":
        print(f"[run_teleop] ERROR: conda env 'tv' not active (current: '{env or '(none)'}')")
        print("            ROS Humble system pinocchio엔 casadi backend가 없어 teleop_hand_and_arm.py가")
        print("            'from pinocchio import casadi' 단계에서 즉시 ImportError로 실패함.")
        print("            아래 순서로 재시도:")
        print("              conda activate tv")
        print("              source setup/dds_env.sh")
        print("              python setup/run_teleop.py --ee dex3 --sim")
        sys.exit(2)
    try:
        import pinocchio.casadi  # noqa: F401
    except ImportError as e:
        print(f"[run_teleop] ERROR: pinocchio.casadi import 실패 — {e}")
        print("            가능 원인:")
        print("              1) ROS PYTHONPATH가 conda site-packages를 가림 (unset PYTHONPATH 후 재시도)")
        print("              2) conda env tv에 pinocchio 미설치 (conda env create -f setup/environment.yml)")
        sys.exit(3)
    try:
        import dex_retargeting  # noqa: F401
    except ImportError:
        print("[run_teleop] ERROR: dex_retargeting 미설치 (G1+Dex3-1 hand control 필수)")
        print("            INSTALL_DEX_RETARGETING=1 bash setup/install.sh")
        sys.exit(4)


def main() -> int:
    wrapper_args, passthrough = _parse_wrapper_args()

    # --upstream-help는 sanity check 없이도 동작해야 함
    if not wrapper_args.upstream_help:
        _sanity_check()

    teleop_path = _resolve_teleop_path()

    # teleop_hand_and_arm.py가 from .를 모르는 직접 실행 스크립트라 sys.path에 그 디렉토리 필요
    sys.path.insert(0, str(teleop_path.parent))

    if wrapper_args.upstream_help:
        passthrough = ["--help"]
    else:
        passthrough = _ensure_sim_defaults(passthrough)

    # monkey-patch는 teleop 모듈 import 전에
    if wrapper_args.http and not wrapper_args.upstream_help:
        _apply_http_monkey_patch()
    # 영상 spawn func에 retry-on-ws-disconnect wrapping (default ON, 부작용 거의 없음)
    if not wrapper_args.upstream_help:
        _patch_image_spawn_retry()

    # DDS env 안내
    if os.environ.get("ROS_DOMAIN_ID") != "1":
        print("[run_teleop] WARN: ROS_DOMAIN_ID != 1. teleop_hand_and_arm.py가 sim 모드에서 "
              "ChannelFactoryInitialize(1)로 명시 호출하므로 동작은 하지만 'source setup/dds_env.sh' 권장",
              flush=True)

    # argv 재조립: teleop_hand_and_arm.py의 argparse가 wrapper 옵션을 모르므로
    # 그것들은 빼고 passthrough만 넘긴다
    sys.argv = [str(teleop_path), *passthrough]
    print(f"[run_teleop] sys.argv = {sys.argv}", flush=True)

    # cwd를 xr_teleoperate/teleop/로 이동 — robot_arm_ik.py가 '../assets/g1/...'
    # 같은 cwd-relative 경로를 쓰기 때문 (그 코드가 'cd teleop && python teleop_hand_and_arm.py'
    # 가정으로 작성됨)
    os.chdir(teleop_path.parent)
    print(f"[run_teleop] cwd → {os.getcwd()}", flush=True)

    # runpy로 __main__처럼 실행 → teleop_hand_and_arm.py의 if __name__ == '__main__' 블록 동작
    import runpy
    runpy.run_path(str(teleop_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
