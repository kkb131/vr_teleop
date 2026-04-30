#!/usr/bin/env python3
"""Galaxy XR + televuer pose-only 검증 + Gate 2 정량 계측.

업스트림 example/test_televuer.py 는 teleimager 서버(192.168.123.164)에서 영상을
가져와 vuer로 그리는 구조라 영상 서버 없이는 동작 안 함. 이 스크립트는 영상 의존성을
제거하고 head/wrist/hand pose만 받는 최소 테스트.

핵심: TeleVuer(zmq=False, webrtc=False, display_mode="pass-through")로 부팅하면
영상 스트림 없이도 XR pose 데이터를 정상 수신한다 (televuer.py 주석 §40).

Usage:
  # 1) Smoke 모드 (기본) — 1Hz 로그로 NaN/Hz/좌표 모니터링, Ctrl+C 종료
  python3 setup/test_pose_only.py

  # 2) Measure 모드 — N초간 자동 측정 후 종료, Gate 2 보고용 표 출력
  python3 setup/test_pose_only.py --measure 30

  # 3) Measure + 보고서 append
  python3 setup/test_pose_only.py --measure 30 --report docs/week2_report.md

전제조건:
  - bash setup/gen_certs.sh  (cert.pem/key.pem in ~/.config/xr_teleoperate/)
  - adb reverse tcp:8012 tcp:8012
  - Galaxy XR Chrome → https://localhost:8012/?ws=wss://localhost:8012 + Enter VR
"""

from __future__ import annotations

# argparse를 가장 먼저 — televuer import 시 vuer 내부의 params_proto가 sys.argv를
# 가로채서 우리 인자를 못 읽기 때문. 파싱 결과만 들고 그 뒤에 televuer를 import.
import argparse
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Galaxy XR pose-only 검증 + Gate 2 계측")
    p.add_argument("--measure", type=float, default=None, metavar="SEC",
                   help="N초간 자동 측정 후 종료")
    p.add_argument("--report", type=str, default=None,
                   help="측정 결과를 markdown으로 append할 파일 경로")
    return p.parse_args()


_ARGS = _parse_args()
# argparse 끝난 뒤 sys.argv를 비워서 vuer가 추가 옵션을 못 보도록
sys.argv = sys.argv[:1]

import datetime as dt
import json
import os
import time
from pathlib import Path

import numpy as np

try:
    from televuer import TeleVuer
except ImportError as e:
    print(f"[ERR] cannot import televuer: {e}")
    print("       먼저 'bash setup/install.sh' 수행 후 재시도")
    sys.exit(1)


# ─── helpers ─────────────────────────────────────────────────────────────

def is_pose_initialized(M: np.ndarray) -> bool:
    """SE(3) 매트릭스가 실제 데이터로 채워졌는지 확인.

    televuer는 shared array를 zeros로 초기화하므로 데이터가 아직 안 왔으면
    M[3,3] == 0. 정상 SE(3)는 M[3,3] == 1.
    """
    return bool(np.isclose(M[3, 3], 1.0))


def is_hand_tracked(positions: np.ndarray) -> bool:
    """Hand 25-joint positions가 유효한지 (전부 0이면 lost)."""
    return bool(np.any(np.abs(positions) > 1e-6))


def has_nan(arr: np.ndarray) -> bool:
    return bool(np.isnan(arr).any())


# ─── modes ───────────────────────────────────────────────────────────────

def run_smoke(tv: TeleVuer) -> None:
    """1초마다 상태 한 줄씩 출력. Ctrl+C로 종료."""
    print("\n[smoke] streaming pose at 1Hz log... (Ctrl+C to stop)\n")
    print(f"{'time':>6} | {'Hz':>5} | head | LW | RW | LH | RH | hand_pos[0]")
    print("-" * 80)

    t_start = time.perf_counter()
    t_window = t_start
    n_window = 0
    n_total = 0

    try:
        while True:
            head = tv.head_pose
            lw = tv.left_arm_pose
            rw = tv.right_arm_pose
            lh = tv.left_hand_positions
            rh = tv.right_hand_positions
            n_window += 1
            n_total += 1

            now = time.perf_counter()
            if now - t_window >= 1.0:
                hz = n_window / (now - t_window)
                pos0 = lh[0] if is_hand_tracked(lh) else np.array([0.0, 0.0, 0.0])
                print(
                    f"{now - t_start:6.1f} | "
                    f"{hz:5.1f} | "
                    f"{'OK' if is_pose_initialized(head) else '..'} | "
                    f"{'OK' if is_pose_initialized(lw) else '..'} | "
                    f"{'OK' if is_pose_initialized(rw) else '..'} | "
                    f"{'OK' if is_hand_tracked(lh) else '..'} | "
                    f"{'OK' if is_hand_tracked(rh) else '..'} | "
                    f"[{pos0[0]:+.2f}, {pos0[1]:+.2f}, {pos0[2]:+.2f}]"
                )
                t_window = now
                n_window = 0
            time.sleep(0.005)
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - t_start
        print(f"\n[smoke] stopped. avg Hz = {n_total / elapsed:.1f} over {elapsed:.1f}s")


def run_measure(tv: TeleVuer, duration: float) -> dict:
    """N초간 자동 측정 후 dict 리턴.

    측정 항목:
      - mean_freq_hz:        평균 폴링 주파수 (10초 sliding window 기반)
      - nan_per_field:       각 필드의 NaN 발생 프레임 수
      - lost_frames_per_field: pose 초기화 안 됨/hand 추적 끊김 프레임 수
      - recovery_latency_s:  hand가 끊긴 후 다시 잡히기까지 가장 긴 구간
      - wrist_jitter_cm:     left_wrist 위치 표준편차 (사용자가 손 멈춰야 의미)
    """
    print(f"\n[measure] {duration:.0f}초간 자동 측정")
    print("[measure] 가이드: ① 손 자연스럽게 움직이기 ② 한 번 시야 밖으로 뺐다 다시 들이밀기")
    print("[measure]         ③ 마지막 5초간 손 정지 (jitter 측정용)")
    input("[measure] 준비됐으면 Enter...\n")

    t0 = time.perf_counter()
    t_end = t0 + duration

    # 시계열 수집
    timestamps: list[float] = []
    nan_counts = {"head": 0, "lw": 0, "rw": 0, "lh": 0, "rh": 0}
    lost_counts = {"head": 0, "lw": 0, "rw": 0, "lh": 0, "rh": 0}
    lh_lost_seen_at: float | None = None
    longest_recovery = 0.0
    lw_positions: list[np.ndarray] = []

    n = 0
    while True:
        now = time.perf_counter()
        if now >= t_end:
            break
        head = tv.head_pose
        lw = tv.left_arm_pose
        rw = tv.right_arm_pose
        lh = tv.left_hand_positions
        rh = tv.right_hand_positions

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
            if lh_lost_seen_at is None:
                lh_lost_seen_at = now
        else:
            if lh_lost_seen_at is not None:
                gap = now - lh_lost_seen_at
                longest_recovery = max(longest_recovery, gap)
                lh_lost_seen_at = None
            lw_positions.append(lw[:3, 3].copy())  # translation only
        if not is_hand_tracked(rh):
            lost_counts["rh"] += 1

        time.sleep(0.005)

    elapsed = timestamps[-1] - t0 if timestamps else 0
    mean_hz = n / elapsed if elapsed > 0 else 0.0

    # last 5s jitter
    jitter_cm = 0.0
    if lw_positions:
        cutoff = t_end - 5.0
        # match positions to their timestamps (1:1 correspondence in collection order)
        last5 = [
            p for p, t in zip(lw_positions, timestamps[-len(lw_positions) :])
            if t >= cutoff
        ]
        if len(last5) >= 10:
            arr = np.stack(last5)
            jitter_cm = float(np.linalg.norm(arr.std(axis=0)) * 100.0)

    return {
        "duration_s": round(elapsed, 2),
        "frames": n,
        "mean_freq_hz": round(mean_hz, 1),
        "nan_per_field": nan_counts,
        "lost_frames_per_field": lost_counts,
        "recovery_latency_s": round(longest_recovery, 2),
        "wrist_jitter_cm": round(jitter_cm, 2),
    }


# ─── reporting ───────────────────────────────────────────────────────────

def render_markdown(report: dict) -> str:
    ts = dt.datetime.now().isoformat(timespec="seconds")
    hz = report["mean_freq_hz"]
    rec = report["recovery_latency_s"]
    jit = report["wrist_jitter_cm"]
    lost = report["lost_frames_per_field"]
    nan = report["nan_per_field"]
    pass_hz = "✅" if hz >= 30 else "❌"
    pass_rec = "✅" if rec < 1.0 else "⚠️"
    return f"""
## Gate 2 측정 — {ts}

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | {hz} Hz | ≥ 30 Hz | {pass_hz} |
| Recovery latency | {rec} s | < 1.0 s | {pass_rec} |
| Wrist jitter (정지 5초) | {jit} cm | 보고만 | — |
| 측정 시간 | {report["duration_s"]} s | — | — |
| 프레임 수 | {report["frames"]} | — | — |

**Lost frames per field** (전체 중): head={lost["head"]} / lw={lost["lw"]} / rw={lost["rw"]} / lh={lost["lh"]} / rh={lost["rh"]}
**NaN frames per field**: head={nan["head"]} / lw={nan["lw"]} / rw={nan["rw"]} / lh={nan["lh"]} / rh={nan["rh"]}
"""


def append_report(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(f"# Week 2 Gate 2 측정 보고서\n{content}")
    else:
        with path.open("a") as f:
            f.write(content)


# ─── main ────────────────────────────────────────────────────────────────

def main() -> int:
    args = _ARGS
    print("[init] TeleVuer (pose-only: zmq=False, webrtc=False, pass-through)...")
    tv = TeleVuer(
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
    print("       https://localhost:8012/?ws=wss://localhost:8012")
    print("       (self-signed cert 경고 → '고급 → 진행')")
    print("       'Enter VR' 또는 'pass-through' 버튼 클릭 후 손 들이밀기")
    input("[init] PC에서 Enter 누르면 폴링 시작... ")

    try:
        if args.measure is not None:
            report = run_measure(tv, args.measure)
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
            run_smoke(tv)
    finally:
        try:
            tv.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
