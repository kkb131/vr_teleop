#!/usr/bin/env python3
"""UDP 도달 진단 — 로봇 PC ↔ 조종 PC.

DDS 가 쓰는 UDP 7400-7700 (CycloneDDS 도메인 1) 에서 어느 포트가 양방향으로
도달하는지 socket 레벨에서 직접 검사. tcpdump / nc / nmap 으로 추적하던 단계를
하나의 스크립트에서, 단계별로 어디서 막히는지 그 자리에서 보이게 함.

모드:
  diag                       — 자기 PC 의 NIC/route/iptables/ufw/rp_filter/listening sockets
  listen --port N            — 단일/다중 포트 수신 + 송신측 host/IP 통계
  send --target IP           — timestamped message 송신, 각 포트 별 결과
  probe --target IP          — 포트 범위에 1개씩 빠르게 송신 (port-scan 용)
  pingpong --peer IP         — 양방향 자동 PING/PONG, 양쪽 PC 동시 실행

포트 표현 (--ports):
  '7660'                       단일
  '7660,7661,7670'             리스트
  '7400-7700'                  범위
  '7400-7700:10'               범위 + step

전형적 진단 시나리오:

  # 1) 양쪽 PC 각각에서 자기 환경 점검
  python3 udp.py diag --target <상대IP>

  # 2) 양방향 한 번에 확정 (양쪽 PC 에서 동시 실행)
  #    DDS 가 안 쓰는 포트 7700 권장 — cyclone bind 충돌 회피
  python3 udp.py pingpong --peer <상대IP> --port 7700

  # 3) 어떤 포트가 막혔는지 좁히기 — 수신측 listen, 송신측 send
  #    조종 PC:
  python3 udp.py listen --ports 7660,7661,7670,7680 --timeout 30
  #    로봇 PC:
  python3 udp.py send --target <조종IP> --ports 7660,7661,7670,7680 --count 5

  # 4) DDS 도메인 1 의 핵심 포트 7660,7661 만 확정 검사
  #    수신측: listen --ports 7660,7661
  #    송신측: send --ports 7660,7661 --src-port 7660  (src 도 DDS 포트로 고정)

해석:
  - listen 결과의 '[OK] :7660' 가 '[--]:7670' 와 다르면 → 포트별 화이트리스트 방화벽
  - pingpong 의 PING 수신 0 → 상대 → 나 차단
  - pingpong 의 PONG 수신 0 → 나 → 상대 차단 (또는 상대 가 응답 못 함)
"""
from __future__ import annotations

import argparse
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime


def parse_ports(spec: str) -> list[int]:
    """'7660' / '7660,7661' / '7400-7700' / '7400-7700:10' 파싱."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            r, _, step_s = part.partition(":")
            step = int(step_s) if step_s else 1
            lo, hi = r.split("-")
            out.extend(range(int(lo), int(hi) + 1, step))
        else:
            out.append(int(part))
    return out


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _run(cmd: list[str] | str, shell: bool = False) -> None:
    try:
        subprocess.run(cmd, shell=shell, check=False, timeout=10)
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {cmd}")


def cmd_diag(args: argparse.Namespace) -> int:
    print("=" * 64)
    print(f" UDP DIAG @ {socket.gethostname()}  ({datetime.now().isoformat(timespec='seconds')})")
    print("=" * 64)

    print("\n--- DDS env ---")
    for k in ["RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "CYCLONEDDS_URI",
              "ROS_DISTRO", "XR_DDS_REMOTE"]:
        print(f"  {k:<22} = {os.environ.get(k, '(unset)')}")

    print("\n--- ip -br addr ---")
    _run(["ip", "-br", "addr"])

    print("\n--- ip route ---")
    _run(["ip", "route"])

    if args.target:
        print(f"\n--- ip route get {args.target} ---")
        _run(["ip", "route", "get", args.target])

    print("\n--- rp_filter (1=strict, 2=loose, 0=off) ---")
    _run(["sysctl", "net.ipv4.conf.all.rp_filter",
          "net.ipv4.conf.default.rp_filter"])

    print("\n--- iptables INPUT (top 20) ---")
    _run("sudo -n iptables -L INPUT -nv --line-numbers 2>/dev/null | head -20 "
         "|| echo '(sudo nopasswd 안되거나 iptables 없음)'", shell=True)

    print("\n--- iptables OUTPUT (top 20) ---")
    _run("sudo -n iptables -L OUTPUT -nv --line-numbers 2>/dev/null | head -20 "
         "|| echo '(sudo nopasswd 안되거나 iptables 없음)'", shell=True)

    print("\n--- ufw status ---")
    _run("sudo -n ufw status verbose 2>/dev/null "
         "|| echo '(ufw 미설치 또는 sudo 필요)'", shell=True)

    print("\n--- listening UDP sockets on 7400-7700 ---")
    _run("ss -tunlp 2>/dev/null | awk 'NR==1; "
         "$5 ~ /:(74|75|76)[0-9][0-9]$/' || true", shell=True)

    if args.target:
        print(f"\n--- ping {args.target} (3 packets) ---")
        _run(["ping", "-c", "3", "-W", "2", args.target])
        print(f"\n--- traceroute -nU --port=7660 {args.target} (UDP, 5 hops max) ---")
        _run(["sh", "-c", f"command -v traceroute >/dev/null && "
              f"traceroute -nU -m 5 --port=7660 {args.target} 2>/dev/null "
              f"|| (command -v tracepath >/dev/null && tracepath -m 5 {args.target}) "
              f"|| echo '(traceroute/tracepath 둘 다 없음)'"])
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    ports = parse_ports(args.ports or str(args.port))
    print(f"[listen] host={socket.gethostname()}  bind={args.bind}  "
          f"ports={ports[:6]}{'...' if len(ports) > 6 else ''} "
          f"(총 {len(ports)})")

    socks: dict[int, tuple[socket.socket, int]] = {}
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((args.bind, p))
            s.setblocking(False)
            socks[s.fileno()] = (s, p)
            print(f"  [OK]   bind {args.bind}:{p}")
        except OSError as e:
            print(f"  [FAIL] bind {args.bind}:{p}  ({e})  "
                  f"— cyclone/sim 가 점유 중일 가능성")

    if not socks:
        print("\n바인딩 가능한 포트가 없음. cyclone/sim 종료 후 재시도.")
        return 2

    received: dict[int, int] = {p: 0 for _, p in socks.values()}
    senders: dict[int, dict[str, int]] = {p: {} for p in received}

    print(f"\n수신 대기 중 (Ctrl+C 또는 {args.timeout or '무한'}s)...\n")
    start = time.time()
    fdmap = {fd: tup for fd, tup in socks.items()}
    try:
        while True:
            ready, _, _ = select.select([s for s, _ in fdmap.values()],
                                        [], [], 1.0)
            for s in ready:
                _, port = fdmap[s.fileno()]
                try:
                    data, addr = s.recvfrom(65535)
                except OSError:
                    continue
                received[port] += 1
                senders[port][addr[0]] = senders[port].get(addr[0], 0) + 1
                try:
                    txt = data.decode("utf-8")[:80].replace("\n", "\\n")
                except UnicodeDecodeError:
                    # binary (RTPS 등) — 앞 24 byte hex + ASCII strings
                    hexs = data[:24].hex()
                    strs = "".join(c if 32 <= ord(c) < 127 else "." for c in
                                   data[:60].decode("latin-1"))
                    txt = f"<bin> hex={hexs} ascii={strs}"
                if received[port] <= args.max_print or received[port] % 50 == 0:
                    print(f"  [{_now()}] :{port:5d} <- {addr[0]}:{addr[1]:<6d}"
                          f"  ({len(data):4d}B)  {txt}")
            if args.timeout and (time.time() - start) > args.timeout:
                break
    except KeyboardInterrupt:
        pass

    print("\n" + "=" * 64)
    print(" 수신 통계")
    print("=" * 64)
    for p in sorted(received):
        n = received[p]
        marker = "[OK]" if n > 0 else "[--]"
        srcs = ", ".join(f"{ip}({c})" for ip, c in senders[p].items()) or "(none)"
        print(f"  {marker} :{p:5d}  {n:6d}개  from {srcs}")
    total = sum(received.values())
    print(f"\n  총 {total}개 / {len(received)}개 포트")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    ports = parse_ports(args.ports or str(args.port))
    host = socket.gethostname()
    print(f"[send] {host} -> {args.target}  ports={ports[:6]}"
          f"{'...' if len(ports) > 6 else ''} (총 {len(ports)})  "
          f"count={args.count}  interval={args.interval}s")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.src_port:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", args.src_port))
            print(f"  source port = {args.src_port}")
        except OSError as e:
            print(f"  [FAIL] src port bind {args.src_port}: {e}")
            return 2
    if args.iface:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                         args.iface.encode())
            print(f"  bound to iface {args.iface}")
        except OSError as e:
            print(f"  [WARN] BINDTODEVICE 실패: {e}  (root 권한 필요)")

    total_ok = 0
    total_fail = 0
    for i in range(args.count):
        for port in ports:
            msg = (f"[UDP-TEST] from={host} seq={i:04d} "
                   f"dst={args.target}:{port} ts={_now()}\n").encode()
            try:
                n = s.sendto(msg, (args.target, port))
                print(f"  [{_now()}] -> {args.target}:{port:<5d}  ({n}B)")
                total_ok += 1
            except OSError as e:
                print(f"  [{_now()}] -> {args.target}:{port:<5d}  FAIL: {e}")
                total_fail += 1
        if i < args.count - 1:
            time.sleep(args.interval)

    print(f"\n송신 완료: {total_ok} OK / {total_fail} FAIL. "
          f"수신측 통계와 비교.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    ports = parse_ports(args.ports)
    host = socket.gethostname()
    print(f"[probe] {host} -> {args.target}  {len(ports)}개 포트 "
          f"({ports[0]}..{ports[-1]})")
    print(f"수신측 권장: python3 udp.py listen --ports {args.ports} "
          f"--timeout {len(ports) * args.interval + 5:.0f}\n")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ok = 0
    fail = 0
    for port in ports:
        msg = (f"[PROBE] from={host} dst_port={port} ts={_now()}\n").encode()
        try:
            s.sendto(msg, (args.target, port))
            print(f"  -> :{port:5d} sent")
            ok += 1
        except OSError as e:
            print(f"  -> :{port:5d} FAIL: {e}")
            fail += 1
        time.sleep(args.interval)

    print(f"\n완료: {ok} 송신 / {fail} 실패. 수신측 listen 결과와 비교하면 "
          f"어떤 포트가 막혔는지 확정.")
    return 0


def cmd_pingpong(args: argparse.Namespace) -> int:
    host = socket.gethostname()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"[FAIL] bind 0.0.0.0:{args.port} - {e}")
        return 2
    s.setblocking(False)

    print(f"[pingpong] {host} <-> {args.peer}  port={args.port}  "
          f"duration={args.duration}s  interval={args.interval}s")
    print(f"  >>> 양쪽 PC 에서 동시에 실행해야 함 <<<\n")

    sent = 0
    ping_recv = 0
    pong_recv = 0
    pending: dict[int, float] = {}
    rtts: list[float] = []
    seen_peers: set[str] = set()

    start = time.time()
    next_send = start
    try:
        while time.time() - start < args.duration:
            now = time.time()
            if now >= next_send:
                seq = sent
                msg = f"PING seq={seq} from={host} ts={now:.6f}".encode()
                try:
                    s.sendto(msg, (args.peer, args.port))
                    pending[seq] = now
                    sent += 1
                    print(f"  [{_now()}] -> PING seq={seq}")
                except OSError as e:
                    print(f"  [{_now()}] -> PING seq={seq} FAIL: {e}")
                next_send = now + args.interval

            ready, _, _ = select.select([s], [], [], 0.05)
            for _ in ready:
                try:
                    data, addr = s.recvfrom(2048)
                except OSError:
                    continue
                seen_peers.add(addr[0])
                txt = data.decode("utf-8", errors="replace")
                if txt.startswith("PING"):
                    ping_recv += 1
                    pong = f"PONG echo=({txt}) by={host} ts={time.time():.6f}".encode()
                    try:
                        s.sendto(pong, addr)
                        print(f"  [{_now()}] <- {addr[0]} PING  "
                              f"| -> PONG")
                    except OSError as e:
                        print(f"  [{_now()}] <- PING but PONG send FAIL: {e}")
                elif txt.startswith("PONG"):
                    pong_recv += 1
                    seq = -1
                    for tok in txt.split():
                        if tok.startswith("seq="):
                            try:
                                seq = int(tok.split("=", 1)[1].rstrip(")"))
                            except ValueError:
                                pass
                            break
                    rtt = None
                    if seq in pending:
                        rtt = (time.time() - pending.pop(seq)) * 1000
                        rtts.append(rtt)
                    if rtt is not None:
                        print(f"  [{_now()}] <- {addr[0]} PONG "
                              f"seq={seq} rtt={rtt:.1f}ms")
                    else:
                        print(f"  [{_now()}] <- {addr[0]} PONG "
                              f"seq={seq} (rtt 추적 안됨)")
                else:
                    print(f"  [{_now()}] <- {addr[0]} (unknown) "
                          f"{txt[:60]}")
    except KeyboardInterrupt:
        pass

    print("\n" + "=" * 64)
    print(" pingpong 결과")
    print("=" * 64)
    print(f"  내가 보낸 PING            : {sent}")
    print(f"  상대로부터 받은 PING      : {ping_recv}")
    print(f"  상대로부터 받은 PONG      : {pong_recv}")
    print(f"  관측된 peer IP            : {sorted(seen_peers) or '(none)'}")
    if rtts:
        print(f"  RTT min/avg/max (ms)      : {min(rtts):.1f} / "
              f"{sum(rtts) / len(rtts):.1f} / {max(rtts):.1f}")

    print()
    if ping_recv > 0 and pong_recv > 0:
        print("  [PASS] 양방향 UDP OK — DDS 가 안 되면 DDS-level 설정 문제")
        return 0
    elif ping_recv > 0 and pong_recv == 0:
        print("  [FAIL-OUT] 상대 PING 은 수신 OK, 내 PING 에 응답 PONG 안 옴")
        print("             → 이 PC OUTPUT 또는 상대 PC INPUT 차단")
        print("             → 상대 측 iptables INPUT / 중간 hop 방화벽 의심")
        return 1
    elif ping_recv == 0 and pong_recv > 0:
        print("  [FAIL-IN] 내 PONG 수신은 OK, 상대 PING 안 옴")
        print("            → 매우 드물지만 상대 OUTPUT 또는 내 INPUT 비대칭 차단")
        return 1
    else:
        if sent == 0:
            print("  [FAIL] 송신 자체가 0 — OUTPUT routing/firewall 문제")
        else:
            print("  [FAIL] 한 패킷도 안 옴")
            print("         → 양방향 차단 또는 상대 PC 에서 pingpong 미실행")
            print("         → 'udp.py diag' 로 양쪽 PC 자체 점검 먼저")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = p.add_subparsers(dest="mode", required=True)

    pd = sp.add_parser("diag",
                       help="자기 PC 의 NIC/route/firewall/listening sockets")
    pd.add_argument("--target", default=None,
                    help="상대 PC IP — ping + route get + traceroute 까지 함께")
    pd.set_defaults(func=cmd_diag)

    pl = sp.add_parser("listen", help="UDP 포트 수신 (단일/다중)")
    pl.add_argument("--port", type=int, default=7660)
    pl.add_argument("--ports", default=None,
                    help="'7660,7661' 또는 '7400-7700' 또는 '7400-7700:10'")
    pl.add_argument("--bind", default="0.0.0.0")
    pl.add_argument("--timeout", type=float, default=0,
                    help="초 (0=Ctrl+C 까지 무한)")
    pl.add_argument("--max-print", type=int, default=20,
                    help="포트당 처음 N 개만 모두 출력 (이후 50개마다)")
    pl.set_defaults(func=cmd_listen)

    ps = sp.add_parser("send", help="UDP 송신")
    ps.add_argument("--target", required=True, help="상대 PC IP")
    ps.add_argument("--port", type=int, default=7660)
    ps.add_argument("--ports", default=None)
    ps.add_argument("--count", type=int, default=5)
    ps.add_argument("--interval", type=float, default=0.5)
    ps.add_argument("--src-port", type=int, default=0,
                    help="송신측 source port 고정 (방화벽이 src port 검사 시 유용)")
    ps.add_argument("--iface", default=None,
                    help="송신 NIC 명시 (SO_BINDTODEVICE, root 필요)")
    ps.set_defaults(func=cmd_send)

    pp = sp.add_parser("probe", help="포트 범위 스캔 (1 패킷씩)")
    pp.add_argument("--target", required=True)
    pp.add_argument("--ports", default="7400-7700:10")
    pp.add_argument("--interval", type=float, default=0.05)
    pp.set_defaults(func=cmd_probe)

    pg = sp.add_parser("pingpong",
                       help="양방향 PING/PONG 자동 — 양쪽 PC 동시 실행")
    pg.add_argument("--peer", required=True, help="상대 PC IP")
    pg.add_argument("--port", type=int, default=7700,
                    help="DDS 안 쓰는 포트 권장 (default 7700)")
    pg.add_argument("--interval", type=float, default=1.0)
    pg.add_argument("--duration", type=float, default=20.0)
    pg.set_defaults(func=cmd_pingpong)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
