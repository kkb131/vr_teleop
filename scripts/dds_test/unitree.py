#!/usr/bin/env python3
"""DDS 양 PC 통신 진단 스크립트 (unitree_sdk2py + CycloneDDS).

sim_main.py 가 쓰는 DDS 스택 (`unitree_sdk2py.core.channel` →
ChannelFactoryInitialize → CycloneDDS) 과 동일한 경로로 publish/subscribe
해서, rt/lowstate 가 안 보일 때 어디서 끊겼는지 좁히는 용도.

세 모드:
  info  — 현재 env, cyclonedds.xml 내용, CycloneDDS 가 실제 선택한 NIC/주소
          (Tracing config=fine) 출력
  pub   — rt/dds_test 토픽에 hostname#counter@timestamp 를 1Hz 송신
  sub   — rt/dds_test 토픽 수신 (timeout 초 대기, 받은 개수 / 보낸 host 표시)

전형적 사용:
  # 1) 양쪽 PC 각각에서 환경 sanity check
  python3 scripts/dds_test.py info

  # 2) 로봇 PC (송신) ↔ 조종 PC (수신)
  #    로봇 PC:
  python3 scripts/dds_test.py pub
  #    조종 PC:
  python3 scripts/dds_test.py sub

  # 3) 방향 바꿔서도 확인 (방화벽이 한 방향만 막혀 있을 때 구분)
  #    조종 PC: pub  /  로봇 PC: sub

해석:
  - info 의 'selected interface' IP 가 cyclonedds.xml 의 <Peers> 가 가리키는
    네트워크와 같은 서브넷이어야 함. docker0/172.17.x 면 NIC 자동선택 실패.
  - pub 은 패킷이 안 빠질 일이 거의 없음 (송신은 거의 항상 성공). pub 측
    터미널에 ' -> ...' 가 계속 찍히면 OK.
  - sub 이 0개면: discovery 실패 (포트 7660 계열) 또는 user data 차단 (7661).
    tcpdump 로 어느 쪽 패킷이 안 오는지 추가 확인.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime


def _print_kv(k: str, v: str) -> None:
    print(f"  {k:<22} = {v}")


def _read_env() -> dict:
    keys = ["RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "CYCLONEDDS_URI",
            "CYCLONEDDS_HOME", "XR_DDS_REMOTE"]
    return {k: os.environ.get(k, "(unset)") for k in keys}


def cmd_info(args: argparse.Namespace) -> int:
    print("=" * 60)
    print(" DDS 환경 (이 PC)")
    print("=" * 60)
    env = _read_env()
    for k, v in env.items():
        _print_kv(k, v)

    print("\n" + "-" * 60)
    print(" cyclonedds.xml 내용 (CYCLONEDDS_URI 가 가리키는 파일)")
    print("-" * 60)
    uri = env["CYCLONEDDS_URI"]
    if uri.startswith("file://"):
        path = uri[len("file://"):]
        try:
            with open(path) as f:
                print(f.read())
        except OSError as e:
            print(f"  [ERR] {path} 읽기 실패: {e}")
    else:
        print("  CYCLONEDDS_URI 가 file:// 형식이 아님 → xml 미적용 가능성")

    print("-" * 60)
    print(" Local NICs (ip -br addr)")
    print("-" * 60)
    subprocess.run(["ip", "-br", "addr"], check=False)

    print("\n" + "-" * 60)
    print(" CycloneDDS Tracing — 실제 선택된 NIC/주소")
    print("-" * 60)
    # 기존 URI 뒤에 tracing config 를 inline 으로 append.
    # CycloneDDS 는 comma-separated URI 를 순서대로 merge.
    trace_xml = ('<CycloneDDS><Domain id="any"><Tracing>'
                 '<Verbosity>config</Verbosity>'
                 '<OutputFile>stderr</OutputFile>'
                 '</Tracing></Domain></CycloneDDS>')
    new_uri = f"{uri},{trace_xml}" if uri != "(unset)" else trace_xml
    os.environ["CYCLONEDDS_URI"] = new_uri

    # ChannelFactoryInitialize 가 participant 를 만드는 순간 cyclone 이 config
    # 를 stderr 로 dump. stderr 를 그대로 흘려보낸다.
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    except ImportError as e:
        print(f"  [ERR] unitree_sdk2py import 실패: {e}")
        return 2

    domain = int(env["ROS_DOMAIN_ID"]) if env["ROS_DOMAIN_ID"].isdigit() else 1
    print(f"  ChannelFactoryInitialize({domain}) 호출 — 아래 'config:' 라인 주목\n")
    ChannelFactoryInitialize(domain)
    time.sleep(1.0)  # tracing 출력이 flush 되도록
    print("\n  (위 출력에서 'selected interface' / 'address' 라인의 IP 확인)")
    return 0


def cmd_pub(args: argparse.Namespace) -> int:
    from unitree_sdk2py.core.channel import (ChannelFactoryInitialize,
                                             ChannelPublisher)
    from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_

    domain = int(os.environ.get("ROS_DOMAIN_ID", "1"))
    ChannelFactoryInitialize(domain)
    pub = ChannelPublisher(args.topic, String_)
    pub.Init()

    host = socket.gethostname()
    period = 1.0 / max(args.rate, 0.1)
    print(f"[pub] topic={args.topic}  host={host}  rate={args.rate}Hz  "
          f"domain={domain}")
    print(f"[pub] Ctrl+C 로 종료\n")

    i = 0
    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            msg = String_(data=f"{host}#{i:06d}@{ts}")
            pub.Write(msg)
            print(f"  -> {msg.data}", flush=True)
            i += 1
            time.sleep(period)
    except KeyboardInterrupt:
        print(f"\n[pub] 종료. 총 {i}개 송신")
    finally:
        pub.Close()
    return 0


def cmd_sub(args: argparse.Namespace) -> int:
    from unitree_sdk2py.core.channel import (ChannelFactoryInitialize,
                                             ChannelSubscriber)
    from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_

    domain = int(os.environ.get("ROS_DOMAIN_ID", "1"))
    ChannelFactoryInitialize(domain)

    stats = {"n": 0, "hosts": {}, "first_t": None, "last_t": None}

    def cb(msg: String_) -> None:
        stats["n"] += 1
        now = time.time()
        if stats["first_t"] is None:
            stats["first_t"] = now
        stats["last_t"] = now
        data = msg.data
        # data 예: hostname#000123@HH:MM:SS.mmm
        host = data.split("#", 1)[0] if "#" in data else "?"
        stats["hosts"][host] = stats["hosts"].get(host, 0) + 1
        if stats["n"] <= args.max_print or stats["n"] % 50 == 0:
            print(f"  <- [{stats['n']:6d}] {data}", flush=True)

    sub = ChannelSubscriber(args.topic, String_)
    sub.Init(cb, 32)

    print(f"[sub] topic={args.topic}  domain={domain}  "
          f"timeout={args.timeout}s  (Ctrl+C 로 즉시 종료)\n")

    start = time.time()
    try:
        while time.time() - start < args.timeout:
            time.sleep(0.5)
            elapsed = time.time() - start
            if stats["n"] == 0 and int(elapsed) % 5 == 0 and elapsed > 4:
                print(f"  [.. {int(elapsed)}s 경과, 아직 0개 수신]", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        sub.Close()

    print("\n" + "=" * 60)
    print(f" 수신 결과 — 총 {stats['n']}개")
    print("=" * 60)
    if stats["n"] > 0:
        dur = (stats["last_t"] or 0) - (stats["first_t"] or 0)
        rate = stats["n"] / dur if dur > 0 else 0.0
        print(f"  duration       = {dur:.2f}s ({rate:.1f} Hz)")
        print(f"  hosts          = {stats['hosts']}")
        print("  [OK] DDS 통신 정상")
        return 0
    else:
        print("  [FAIL] 0개 수신")
        print("  체크 순서:")
        print("    1) pub 측 터미널에 ' -> ...' 가 찍히고 있는지")
        print("    2) 양쪽 PC info 의 'selected interface' IP 가 통신용 NIC 인지")
        print("    3) tcpdump -ni any 'udp portrange 7400-7700' 양방향 확인")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)

    p_info = sub.add_parser("info", help="env + xml + CycloneDDS 선택 NIC 출력")
    p_info.set_defaults(func=cmd_info)

    p_pub = sub.add_parser("pub", help="rt/dds_test 토픽 publish")
    p_pub.add_argument("--topic", default="rt/dds_test")
    p_pub.add_argument("--rate", type=float, default=1.0, help="Hz (default 1)")
    p_pub.set_defaults(func=cmd_pub)

    p_sub = sub.add_parser("sub", help="rt/dds_test 토픽 subscribe")
    p_sub.add_argument("--topic", default="rt/dds_test")
    p_sub.add_argument("--timeout", type=float, default=30.0,
                       help="자동 종료까지 초 (default 30)")
    p_sub.add_argument("--max-print", type=int, default=20,
                       help="처음 N개만 모두 출력, 이후엔 50개마다 (default 20)")
    p_sub.set_defaults(func=cmd_sub)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
