#!/usr/bin/env python3
"""vuer 우회 ws pose server — Galaxy XR Chrome에서 vuer client publish 멈춤 우회.

배경: Galaxy XR Chrome immersive 진입 시 vuer 0.0.60 client가 hand/cam event를
30초간 7회/2회만 publish하고 멈춤. webxr_check.html(자체 XR-RAF 기반)은 정상 동작
확인됨. 따라서 vuer client React 자체를 우회하고 자체 ws server에 직접 송신하는
구조를 도입.

구성:
- HTTP server (port 8013): webxr_to_pose.html 정적 서빙
- WebSocket server (port 8013/pose): client로부터 JSON pose 메시지 수신
- 매 메시지마다 PoseStore에 update
- main thread에서 1Hz smoke 로그 또는 N초 measure (test_pose_only.py와 같은 형식)

JSON 프로토콜:
  {"type": "head", "ts": <ms>, "matrix": [16 floats column-major]}
  {"type": "hand", "ts": <ms>, "handedness": "left"|"right",
   "wrist": [16 floats], "positions": [25 × [x,y,z]]}

Usage:
  # PC측
  adb reverse tcp:8013 tcp:8013
  python3 setup/test_pose_only_ws.py
  # Galaxy XR Chrome → http://localhost:8013/  → Enter VR/AR

  # 측정 모드
  python3 setup/test_pose_only_ws.py --measure 30 --report docs/galaxy_xr.md
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

try:
    from aiohttp import web, WSMsgType
except ImportError:
    print("[ERR] aiohttp 미설치. conda activate tv 또는 pip install aiohttp")
    sys.exit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="vuer 우회 ws pose server")
    p.add_argument("--port", type=int, default=8013)
    p.add_argument("--measure", type=float, default=None, metavar="SEC",
                   help="N초간 자동 측정 후 종료")
    p.add_argument("--report", type=str, default=None,
                   help="측정 결과를 markdown으로 append할 파일 경로")
    return p.parse_args()


# ── shared pose store ──────────────────────────────────────────────────
class PoseStore:
    """test_pose_only.py의 TeleVuer property들과 같은 형식의 데이터."""

    def __init__(self):
        self._lock = threading.Lock()
        self.head_pose = np.zeros(16, dtype=np.float64)
        self.left_arm_pose = np.zeros(16, dtype=np.float64)
        self.right_arm_pose = np.zeros(16, dtype=np.float64)
        self.left_hand_positions = np.zeros(25 * 3, dtype=np.float64)
        self.right_hand_positions = np.zeros(25 * 3, dtype=np.float64)
        self.msg_count = 0  # client → server 메시지 누적
        self.last_msg_time = 0.0

    def update_head(self, matrix: list[float]) -> None:
        with self._lock:
            self.head_pose[:] = matrix
            self.msg_count += 1
            self.last_msg_time = time.perf_counter()

    def update_hand(self, handedness: str, wrist: list[float],
                    positions: list[list[float]]) -> None:
        flat = np.array(positions, dtype=np.float64).reshape(-1)
        with self._lock:
            if handedness == "left":
                self.left_arm_pose[:] = wrist
                self.left_hand_positions[:] = flat
            else:
                self.right_arm_pose[:] = wrist
                self.right_hand_positions[:] = flat
            self.msg_count += 1
            self.last_msg_time = time.perf_counter()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "head": self.head_pose.copy().reshape(4, 4, order="F"),
                "lw": self.left_arm_pose.copy().reshape(4, 4, order="F"),
                "rw": self.right_arm_pose.copy().reshape(4, 4, order="F"),
                "lh": self.left_hand_positions.copy().reshape(25, 3),
                "rh": self.right_hand_positions.copy().reshape(25, 3),
                "msgs": self.msg_count,
            }


STORE = PoseStore()


# ── ws / http handlers ────────────────────────────────────────────────
async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(f"[ws] client connected from {request.remote}", flush=True)
    parse_errors = 0
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    t = payload.get("type")
                    if t == "head":
                        STORE.update_head(payload["matrix"])
                    elif t == "hand":
                        STORE.update_hand(
                            payload["handedness"],
                            payload["wrist"],
                            payload["positions"],
                        )
                except Exception as e:
                    parse_errors += 1
                    if parse_errors <= 3:
                        print(f"[ws] parse error: {e}", flush=True)
            elif msg.type == WSMsgType.ERROR:
                print(f"[ws] connection error: {ws.exception()}", flush=True)
                break
    finally:
        print(f"[ws] client disconnected (parse_errors={parse_errors})", flush=True)
    return ws


async def index_handler(_request: web.Request) -> web.FileResponse:
    p = Path(__file__).parent / "webxr_to_pose.html"
    if not p.exists():
        return web.Response(status=404, text=f"missing {p}")
    return web.FileResponse(p)


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/pose", ws_handler)
    return app


# ── pose helpers (test_pose_only.py와 동일) ──────────────────────────
def is_pose_initialized(M: np.ndarray) -> bool:
    return bool(np.isclose(M[3, 3], 1.0))


def is_hand_tracked(positions: np.ndarray) -> bool:
    return bool(np.any(np.abs(positions) > 1e-6))


def has_nan(arr: np.ndarray) -> bool:
    return bool(np.isnan(arr).any())


# ── modes ───────────────────────────────────────────────────────────
def run_smoke() -> None:
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
                snap = STORE.snapshot()
                cur = snap["msgs"]
                rate = (cur - last_msgs) / (now - t_window)
                last_msgs = cur
                pos0 = snap["lh"][0] if is_hand_tracked(snap["lh"]) else np.zeros(3)
                print(
                    f"{now - t_start:6.1f} | {rate:6.1f} | "
                    f"{'OK' if is_pose_initialized(snap['head']) else '..'} | "
                    f"{'OK' if is_pose_initialized(snap['lw']) else '..'} | "
                    f"{'OK' if is_pose_initialized(snap['rw']) else '..'} | "
                    f"{'OK' if is_hand_tracked(snap['lh']) else '..'} | "
                    f"{'OK' if is_hand_tracked(snap['rh']) else '..'} | "
                    f"[{pos0[0]:+.2f}, {pos0[1]:+.2f}, {pos0[2]:+.2f}]"
                )
                t_window = now
            time.sleep(0.05)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t_start
        total = STORE.msg_count
        print(f"\n[smoke] stopped. avg {total / elapsed:.1f} msg/s over {elapsed:.1f}s")


def run_measure(duration: float) -> dict:
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
    msg_count_start = STORE.msg_count

    while True:
        now = time.perf_counter()
        if now >= t_end:
            break
        snap = STORE.snapshot()
        head, lw, rw = snap["head"], snap["lw"], snap["rw"]
        lh, rh = snap["lh"], snap["rh"]

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
    msgs_received = STORE.msg_count - msg_count_start
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


# ── server thread ─────────────────────────────────────────────────────
async def _serve(port: int, ready: threading.Event) -> None:
    runner = web.AppRunner(make_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[server] http://localhost:{port}/  (webxr_to_pose.html)", flush=True)
    print(f"[server] ws://localhost:{port}/pose", flush=True)
    ready.set()
    while True:
        await asyncio.sleep(3600)


def _server_thread(port: int, ready: threading.Event) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_serve(port, ready))
    except KeyboardInterrupt:
        pass


def main() -> int:
    args = _parse_args()
    ready = threading.Event()
    t = threading.Thread(target=_server_thread, args=(args.port, ready), daemon=True)
    t.start()
    ready.wait(timeout=5.0)

    print()
    print("[init] Galaxy XR Chrome:")
    print(f"       http://localhost:{args.port}")
    print("       'Enter VR' 또는 'Enter AR' 클릭 후 손 들이밀기")
    print(f"       (PC: adb reverse tcp:{args.port} tcp:{args.port} 필요)")
    input("[init] Enter 누르면 폴링 시작... ")

    try:
        if args.measure is not None:
            report = run_measure(args.measure)
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
            run_smoke()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
