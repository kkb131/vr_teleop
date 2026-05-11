#!/usr/bin/env python3
"""vuer 우회 ws bridge — pose-only 검증.

BridgePoseStore 라이브러리(setup/bridge_pose_store.py)를 thin script 로 래핑.
BridgePoseStore 가 자체 aiohttp ws server (port 8013) + HTTP static 서빙 +
shared array 운영을 모두 담당하므로 이 스크립트는 단지:
- BridgePoseStore 인스턴스 생성 (TeleVuer 와 같은 인자)
- smoke (1Hz 로그) 또는 measure (N초 자동 측정 + 보고서 append) 모드 실행

본 스크립트는 standalone pose 검증용. 실제 teleop 통합은 setup/run_teleop_ws.py
가 BridgePoseStore 를 monkey-patch 로 inject (televuer.TeleVuer 자리에).

Usage:
  # PC측
  adb reverse tcp:8013 tcp:8013
  python3 setup/test_pose_only_ws.py
  # Galaxy XR Chrome → http://localhost:8013/

  # 측정 모드
  python3 setup/test_pose_only_ws.py --measure 30 --report docs/galaxy_xr.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="vuer 우회 ws bridge pose 검증")
    p.add_argument("--port", type=int, default=8013,
                   help="ws server port (XR_BRIDGE_PORT env 와 동등)")
    p.add_argument("--measure", type=float, default=None, metavar="SEC",
                   help="N초간 자동 측정 후 종료")
    p.add_argument("--report", type=str, default=None,
                   help="측정 결과를 markdown 으로 append 할 파일 경로")
    return p.parse_args()


def is_pose_initialized(M: np.ndarray) -> bool:
    return bool(np.isclose(M[3, 3], 1.0))


def is_hand_tracked(positions: np.ndarray) -> bool:
    return bool(np.any(np.abs(positions) > 1e-6))


def has_nan(arr: np.ndarray) -> bool:
    return bool(np.isnan(arr).any())


def run_smoke(store) -> None:
    print("\n[smoke] 1Hz log... (Ctrl+C to stop)\n")
    print(f"{'time':>6} | {'msg/s':>6} | head | LW | RW | LH | RH | hand_pos[0]")
    print("-" * 80)
    t_start = time.perf_counter()
    t_window = t_start
    last_msgs = 0
    try:
        while True:
            now = time.perf_counter()
            if now - t_window >= 1.0:
                stats = store.get_stats()
                cur = stats["msg_count"]
                rate = (cur - last_msgs) / (now - t_window)
                last_msgs = cur
                head = store.head_pose
                lw = store.left_arm_pose
                rw = store.right_arm_pose
                lh = store.left_hand_positions
                rh = store.right_hand_positions
                pos0 = lh[0] if is_hand_tracked(lh) else np.zeros(3)
                print(
                    f"{now - t_start:6.1f} | {rate:6.1f} | "
                    f"{'OK' if is_pose_initialized(head) else '..'} | "
                    f"{'OK' if is_pose_initialized(lw) else '..'} | "
                    f"{'OK' if is_pose_initialized(rw) else '..'} | "
                    f"{'OK' if is_hand_tracked(lh) else '..'} | "
                    f"{'OK' if is_hand_tracked(rh) else '..'} | "
                    f"[{pos0[0]:+.2f}, {pos0[1]:+.2f}, {pos0[2]:+.2f}]"
                )
                t_window = now
            time.sleep(0.05)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t_start
        total = store.get_stats()["msg_count"]
        print(f"\n[smoke] stopped. avg {total / elapsed:.1f} msg/s over {elapsed:.1f}s")


def run_measure(store, duration: float) -> dict:
    print(f"\n[measure] {duration:.0f}초간 자동 측정")
    print("[measure] 가이드: ① 손 자연스럽게 ② 시야 밖→다시 안으로 (recovery) ③ 마지막 5초 정지 (jitter)")
    input("[measure] 준비됐으면 Enter...\n")

    t0 = time.perf_counter()
    t_end = t0 + duration

    timestamps: list[float] = []
    nan_counts = {"head": 0, "lw": 0, "rw": 0, "lh": 0, "rh": 0}
    lost_counts = {"head": 0, "lw": 0, "rw": 0, "lh": 0, "rh": 0}
    lh_lost_at: float | None = None
    longest_recovery = 0.0
    lw_positions: list[np.ndarray] = []

    n = 0
    msg_count_start = store.get_stats()["msg_count"]

    while True:
        now = time.perf_counter()
        if now >= t_end:
            break
        head = store.head_pose
        lw = store.left_arm_pose
        rw = store.right_arm_pose
        lh = store.left_hand_positions
        rh = store.right_hand_positions

        timestamps.append(now)
        n += 1

        for name, arr in (("head", head), ("lw", lw), ("rw", rw), ("lh", lh), ("rh", rh)):
            if has_nan(arr):
                nan_counts[name] += 1

        if not is_pose_initialized(head):
            lost_counts["head"] += 1
        if not is_pose_initialized(lw):
            lost_counts["lw"] += 1
        if not is_pose_initialized(rw):
            lost_counts["rw"] += 1
        if not is_hand_tracked(lh):
            lost_counts["lh"] += 1
            if lh_lost_at is None:
                lh_lost_at = now
        else:
            if lh_lost_at is not None:
                longest_recovery = max(longest_recovery, now - lh_lost_at)
                lh_lost_at = None
            lw_positions.append(lw[:3, 3].copy())
        if not is_hand_tracked(rh):
            lost_counts["rh"] += 1

        time.sleep(0.005)

    elapsed = timestamps[-1] - t0 if timestamps else 0
    msgs_received = store.get_stats()["msg_count"] - msg_count_start
    poll_hz = n / elapsed if elapsed > 0 else 0
    msg_hz = msgs_received / elapsed if elapsed > 0 else 0

    jitter_cm = 0.0
    if lw_positions:
        cutoff = t_end - 5.0
        last5 = [
            p for p, t in zip(lw_positions, timestamps[-len(lw_positions):])
            if t >= cutoff
        ]
        if len(last5) >= 10:
            jitter_cm = float(np.linalg.norm(np.stack(last5).std(axis=0)) * 100.0)

    return {
        "duration_s": round(elapsed, 2),
        "poll_frames": n,
        "ws_msgs_received": msgs_received,
        "poll_hz": round(poll_hz, 1),
        "ws_msg_hz": round(msg_hz, 1),
        "nan_per_field": nan_counts,
        "lost_frames_per_field": lost_counts,
        "recovery_latency_s": round(longest_recovery, 2),
        "wrist_jitter_cm": round(jitter_cm, 2),
    }


def render_markdown(report: dict) -> str:
    ts = dt.datetime.now().isoformat(timespec="seconds")
    msg_hz = report["ws_msg_hz"]
    rec = report["recovery_latency_s"]
    jit = report["wrist_jitter_cm"]
    lost = report["lost_frames_per_field"]
    nan = report["nan_per_field"]
    pass_hz = "OK" if msg_hz >= 30 else "FAIL"
    pass_rec = "OK" if rec < 1.0 else "WARN"
    return f"""
## Galaxy XR ws-bridge 측정 — {ts}

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| ws message rate | {msg_hz} Hz | >= 30 Hz | {pass_hz} |
| polling rate | {report["poll_hz"]} Hz | (참고) | - |
| Recovery latency | {rec} s | < 1.0 s | {pass_rec} |
| Wrist jitter (정지 5초) | {jit} cm | 보고만 | - |
| 측정 시간 | {report["duration_s"]} s | - | - |
| polling frames | {report["poll_frames"]} | - | - |
| ws messages | {report["ws_msgs_received"]} | - | - |

**Lost frames per field**: head={lost["head"]} / lw={lost["lw"]} / rw={lost["rw"]} / lh={lost["lh"]} / rh={lost["rh"]}
**NaN frames per field**: head={nan["head"]} / lw={nan["lw"]} / rw={nan["rw"]} / lh={nan["lh"]} / rh={nan["rh"]}
"""


def append_report(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(f"# Galaxy XR ws-bridge 측정 보고서\n{content}")
    else:
        with path.open("a") as f:
            f.write(content)


def main() -> int:
    args = _parse_args()
    # port override via env (BridgePoseStore가 XR_BRIDGE_PORT를 읽음)
    os.environ["XR_BRIDGE_PORT"] = str(args.port)

    # BridgePoseStore import 후 인스턴스화 — ws server 자동 시작
    from bridge_pose_store import BridgePoseStore
    store = BridgePoseStore(
        use_hand_tracking=True,
        binocular=False,
        img_shape=(480, 640),
        display_fps=30.0,
        display_mode="pass-through",
        zmq=False,
        webrtc=False,
    )

    print()
    print("[init] Galaxy XR Chrome:")
    print(f"       http://localhost:{args.port}")
    print("       'Enter VR' 또는 'Enter AR' 클릭 후 손 들이밀기")
    input("[init] Enter 누르면 폴링 시작... ")

    try:
        if args.measure is not None:
            report = run_measure(store, args.measure)
            md = render_markdown(report)
            print(md)
            print("\n[measure] JSON:")
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if args.report:
                p = Path(args.report)
                p.parent.mkdir(parents=True, exist_ok=True)
                append_report(p, md)
                print(f"[measure] appended → {p}")
        else:
            run_smoke(store)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    # script directory를 sys.path 에 추가 (bridge_pose_store import 위해)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
