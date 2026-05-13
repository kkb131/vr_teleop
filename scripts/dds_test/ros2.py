#!/usr/bin/env python3
"""ROS2 토픽 pub/sub 진단 — 로봇 PC ↔ 조종 PC.

rclpy + std_msgs/String 으로 양방향 통신 확인. udp.py 가 socket 레벨 OK 인데
ros2 가 안 되면 RMW/DDS 설정 문제. udp.py 까지 통과한 다음 이걸로 검증.

모드:
  info  — env + ros2 daemon/node/topic 상태
  pub   — /dds_test 토픽에 hostname#counter@ts 를 1Hz 송신
  sub   — /dds_test 토픽 수신, 송신 host 별 통계 + 실측 rate

전형적 사용:

  # 양쪽 PC 동일 셸에서: env 셋업 후
  source scripts/dds_env.sh
  python3 scripts/dds_test/ros2.py info

  # 로봇 PC (송신)
  python3 scripts/dds_test/ros2.py pub --rate 5

  # 조종 PC (수신)
  python3 scripts/dds_test/ros2.py sub --timeout 20

해석:
  - sub 의 'hosts' 에 송신 PC hostname 이 보이면 양방향 DDS OK
  - 0 수신 + udp.py pingpong 은 PASS → RMW/DOMAIN/URI 양쪽 mismatch
  - info 의 'ros2 topic list' 가 비어있고 daemon 도 죽어있으면 daemon 재시작
    (ros2 daemon stop && ros2 daemon start)
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def cmd_info(args: argparse.Namespace) -> int:
    print("=== env ===")
    for k in ["RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "CYCLONEDDS_URI",
              "ROS_DISTRO", "XR_DDS_REMOTE"]:
        print(f"  {k:<22} = {os.environ.get(k, '(unset)')}")
    print(f"  {'hostname':<22} = {socket.gethostname()}")

    for label, cmd in [
        ("ros2 daemon status", ["ros2", "daemon", "status"]),
        ("ros2 node list", ["ros2", "node", "list"]),
        ("ros2 topic list -t", ["ros2", "topic", "list", "-t"]),
        ("ros2 topic info /dds_test --verbose",
         ["ros2", "topic", "info", "/dds_test", "--verbose"]),
    ]:
        print(f"\n--- {label} ---")
        try:
            subprocess.run(cmd, check=False, timeout=10)
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] '{' '.join(cmd)}' 가 10초 안에 안 끝남 "
                  f"(daemon 죽었거나 discovery 진행 중)")
        except FileNotFoundError:
            print(f"  [FAIL] ros2 CLI 없음 — ROS2 환경 source 안된 셸일 수 있음")
            return 2
    return 0


def cmd_pub(args: argparse.Namespace) -> int:
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as e:
        print(f"[FAIL] rclpy import 실패: {e}")
        print("       ROS2 환경을 source 한 셸에서 실행하세요 "
              "(/opt/ros/<distro>/setup.bash)")
        return 2

    class Pub(Node):
        def __init__(self):
            super().__init__("dds_test_pub")
            self.pub = self.create_publisher(String, args.topic, 10)
            self.host = socket.gethostname()
            self.i = 0
            self.timer = self.create_timer(1.0 / args.rate, self.tick)
            self.get_logger().info(
                f"publishing on {args.topic} at {args.rate}Hz "
                f"(host={self.host})"
            )

        def tick(self):
            msg = String()
            msg.data = f"{self.host}#{self.i:06d}@{_now()}"
            self.pub.publish(msg)
            self.get_logger().info(f"-> {msg.data}")
            self.i += 1

    rclpy.init()
    node = Pub()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info(f"총 {node.i}개 송신")
        node.destroy_node()
        rclpy.shutdown()
    return 0


def cmd_sub(args: argparse.Namespace) -> int:
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as e:
        print(f"[FAIL] rclpy import 실패: {e}")
        return 2

    class Sub(Node):
        def __init__(self):
            super().__init__("dds_test_sub")
            self.sub = self.create_subscription(String, args.topic, self.cb, 10)
            self.n = 0
            self.hosts: dict[str, int] = {}
            self.first_t: float | None = None
            self.last_t: float | None = None
            self.get_logger().info(
                f"subscribed to {args.topic} (host={socket.gethostname()})"
            )

        def cb(self, msg):
            self.n += 1
            now = time.time()
            if self.first_t is None:
                self.first_t = now
            self.last_t = now
            data = msg.data
            host = data.split("#", 1)[0] if "#" in data else "?"
            self.hosts[host] = self.hosts.get(host, 0) + 1
            if self.n <= args.max_print or self.n % 50 == 0:
                self.get_logger().info(f"<- [{self.n:6d}] {data}")

    rclpy.init()
    node = Sub()
    start = time.time()
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.5)
            if args.timeout and (time.time() - start) > args.timeout:
                break
    except KeyboardInterrupt:
        pass

    print("\n" + "=" * 64)
    print(" 수신 결과")
    print("=" * 64)
    print(f"  topic            : {args.topic}")
    print(f"  총 수신          : {node.n}")
    print(f"  송신 hosts       : {node.hosts or '(없음)'}")
    if node.n > 0 and node.first_t and node.last_t:
        dur = node.last_t - node.first_t
        if dur > 0:
            print(f"  실측 rate        : {node.n / dur:.2f} Hz "
                  f"({node.n} / {dur:.1f}s)")
        print("\n  [PASS] DDS / ROS2 통신 OK")
        rc = 0
    else:
        print("\n  [FAIL] 0개 수신")
        print("  체크:")
        print("    1) pub 측 터미널에 '-> ...' 가 찍히고 있는지")
        print("    2) udp.py pingpong 으로 UDP 자체 양방향 확인")
        print("    3) 'ros2.py info' 의 env (RMW/DOMAIN/URI) 양쪽 동일한지")
        print("    4) sim 과 같은 셸 환경에서 'cyclonedds.xml' 의 <Peers> 가 "
              "양쪽 IP 를 모두 포함하는지")
        rc = 1

    node.destroy_node()
    rclpy.shutdown()
    return rc


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = p.add_subparsers(dest="mode", required=True)

    pi = sp.add_parser("info", help="env + ros2 daemon/node/topic 상태")
    pi.set_defaults(func=cmd_info)

    ppub = sp.add_parser("pub", help="/dds_test 토픽 publish")
    ppub.add_argument("--topic", default="/dds_test")
    ppub.add_argument("--rate", type=float, default=1.0, help="Hz (default 1)")
    ppub.set_defaults(func=cmd_pub)

    psub = sp.add_parser("sub", help="/dds_test 토픽 subscribe")
    psub.add_argument("--topic", default="/dds_test")
    psub.add_argument("--timeout", type=float, default=0,
                      help="초 (0=Ctrl+C 까지)")
    psub.add_argument("--max-print", type=int, default=20,
                      help="처음 N개 모두 출력, 이후 50개마다")
    psub.set_defaults(func=cmd_sub)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
