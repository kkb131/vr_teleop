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
    p.add_argument("--http", action="store_true",
                   help="HTTPS 대신 plain HTTP로 서버 부팅 (Galaxy XR Chrome이 self-signed cert를 "
                        "거부할 때 우회용; localhost는 W3C 사양상 HTTP도 secure context로 인정됨)")
    p.add_argument("--debug", action="store_true",
                   help="vuer CAMERA_MOVE/HAND_MOVE 핸들러 호출 카운트 + 첫 이벤트 구조 dump + "
                        "기존 try/except가 묻는 예외 traceback 출력 (Lost frames 100%% 디버깅용)")
    p.add_argument("--show-hands", action="store_true",
                   help="main_pass_through의 Hands 컴포넌트를 hideLeft=False, hideRight=False로 "
                        "monkey-patch (Quest 3 Chrome에서 hideLeft=True가 stream까지 막는 케이스 우회)")
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
    import televuer.televuer as _tv_mod
    from televuer import TeleVuer
except ImportError as e:
    print(f"[ERR] cannot import televuer: {e}")
    print("       먼저 'bash setup/install.sh' 수행 후 재시도")
    sys.exit(1)


def _force_plain_http() -> None:
    """televuer가 vuer.Vuer를 호출할 때 cert/key를 무시하고 None을 전달하도록 monkey-patch.

    televuer __init__(line 71-89)이 항상 cert_file/key_file을 non-None 경로로 채워서
    Vuer(cert=...)를 부르는데, vuer.base.py:119는 `if not self.cert:` 분기에서 plain HTTP
    TCPSite로 떨어진다. 따라서 Vuer 호출 시점에서 cert/key를 None으로 강제 치환하면 OK.
    """
    _OrigVuer = _tv_mod.Vuer

    class _PlainHTTPVuer(_OrigVuer):
        def __init__(self, *args, **kwargs):
            kwargs["cert"] = None
            kwargs["key"] = None
            super().__init__(*args, **kwargs)

    _tv_mod.Vuer = _PlainHTTPVuer
    print("[init] HTTP mode (plain) — cert/key forced to None")


# ── debug counters (cross-process shared) ─────────────────────────────────
import multiprocessing as _mp

DEBUG_COUNTERS = {
    "cam":      _mp.Value("i", 0),
    "hand":     _mp.Value("i", 0),
    "cam_err":  _mp.Value("i", 0),
    "hand_err": _mp.Value("i", 0),
}
# 샘플 dump를 child process에서 한 번만 출력하도록 제어하는 flag
DEBUG_SAMPLED = {"cam": _mp.Value("b", 0), "hand": _mp.Value("b", 0)}


def _install_debug_handlers() -> None:
    """TeleVuer.on_cam_move / on_hand_move를 클래스 레벨에서 monkey-patch.

    핵심: TeleVuer.__init__이 self.vuer.add_handler(self.on_cam_move)를 부르는
    시점에 patch된 메서드가 등록되어야 함. 인스턴스 생성 후 add_handler를 덮어쓰면
    이미 fork된 child process에는 도달 못 함. 따라서 클래스 메서드 자체를 교체.
    """
    _OrigTV = _tv_mod.TeleVuer
    _orig_cam = _OrigTV.on_cam_move
    _orig_hand = _OrigTV.on_hand_move

    async def _cam_debug(self, event, session, fps=60):
        with DEBUG_COUNTERS["cam"].get_lock():
            DEBUG_COUNTERS["cam"].value += 1
        # 첫 호출 시 event.value 구조 한 번만 dump
        with DEBUG_SAMPLED["cam"].get_lock():
            if not DEBUG_SAMPLED["cam"].value:
                DEBUG_SAMPLED["cam"].value = 1
                print(f"[debug] on_cam_move first event.value: {repr(event.value)[:500]}",
                      flush=True)
        try:
            with self.head_pose_shared.get_lock():
                self.head_pose_shared[:] = event.value["camera"]["matrix"]
        except Exception:
            with DEBUG_COUNTERS["cam_err"].get_lock():
                DEBUG_COUNTERS["cam_err"].value += 1
                if DEBUG_COUNTERS["cam_err"].value <= 3:
                    import traceback
                    traceback.print_exc()

    async def _hand_debug(self, event, session, fps=60):
        with DEBUG_COUNTERS["hand"].get_lock():
            DEBUG_COUNTERS["hand"].value += 1
        with DEBUG_SAMPLED["hand"].get_lock():
            if not DEBUG_SAMPLED["hand"].value:
                DEBUG_SAMPLED["hand"].value = 1
                v = event.value
                keys = list(v.keys()) if hasattr(v, "keys") else type(v).__name__
                print(f"[debug] on_hand_move first event.value keys: {keys}", flush=True)
                if hasattr(v, "keys"):
                    for k in keys:
                        sub = v[k]
                        sub_repr = repr(sub)[:200] if not hasattr(sub, "__len__") else f"<len={len(sub)}>"
                        print(f"[debug]   {k}: {type(sub).__name__} {sub_repr}", flush=True)
        try:
            await _orig_hand(self, event, session, fps)
        except Exception:
            with DEBUG_COUNTERS["hand_err"].get_lock():
                DEBUG_COUNTERS["hand_err"].value += 1
                if DEBUG_COUNTERS["hand_err"].value <= 3:
                    import traceback
                    traceback.print_exc()

    _OrigTV.on_cam_move = _cam_debug
    _OrigTV.on_hand_move = _hand_debug
    print("[debug] handler monkey-patch installed (class-level)")


def _patch_hands_show() -> None:
    """main_pass_through의 Hands(hideLeft=True, hideRight=True)를 False/False로 교체.

    가설: vuer 0.0.60 + Quest 3 Chrome에서 hideLeft/Right=True가 시각화뿐만 아니라
    stream까지 막아 HAND_MOVE 이벤트가 server로 안 옴. vuer docstring상으로는
    'hides the hand, but still streams the data'이지만 실제 동작 차이를 검증.
    """
    from vuer.schemas import Hands, MotionControllers
    import asyncio
    _OrigTV = _tv_mod.TeleVuer

    async def _patched_main_pass_through(self, session):
        if self.use_hand_tracking:
            session.upsert(
                Hands(
                    stream=True,
                    key="hands",
                    hideLeft=False,    # ← changed from True
                    hideRight=False,   # ← changed from True
                ),
                to="bgChildren",
            )
        else:
            session.upsert(
                MotionControllers(
                    stream=True,
                    key="motionControllers",
                    left=True,
                    right=True,
                ),
                to="bgChildren",
            )
        while True:
            await asyncio.sleep(1.0 / self.display_fps)

    _OrigTV.main_pass_through = _patched_main_pass_through
    print("[init] main_pass_through patched: Hands(hideLeft=False, hideRight=False)")


if _ARGS.http:
    _force_plain_http()
if _ARGS.debug:
    _install_debug_handlers()
if _ARGS.show_hands:
    _patch_hands_show()


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
    if args.http:
        print("[init] Galaxy XR Chrome:")
        print("       http://localhost:8012")
        print("       (HTTP 평문 — localhost는 W3C secure context 예외, cert 경고 없음)")
    else:
        print("[init] Galaxy XR Chrome:")
        print("       https://localhost:8012/?ws=wss://localhost:8012")
        print("       (self-signed cert 경고 → '고급 → 진행')")
        print("       cert 경고 자체가 안 뜨면 --http 옵션으로 재시도")
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
        if args.debug:
            cam = DEBUG_COUNTERS["cam"].value
            hand = DEBUG_COUNTERS["hand"].value
            cam_e = DEBUG_COUNTERS["cam_err"].value
            hand_e = DEBUG_COUNTERS["hand_err"].value
            print()
            print("─── debug summary ───")
            print(f"  on_cam_move  calls={cam:>6}  errors={cam_e:>4}")
            print(f"  on_hand_move calls={hand:>6}  errors={hand_e:>4}")
            print()
            if cam == 0 and hand == 0:
                print("  → 시나리오 B (전체): vuer client가 어떤 이벤트도 server로 안 보냄.")
                print("    원인: WebXR session 자체가 client에서 시작 안 됐거나 stream=True 무시.")
                print("    다음 시도: Quest 3에서 'Enter VR' 정확히 눌렀는지, hand-tracking 권한 허용했는지 확인.")
            elif cam > 0 and hand == 0:
                print("  → 시나리오 B (hand 한정): WebXR session OK / head_pose 정상.")
                print("    그러나 HAND_MOVE 이벤트가 server에 안 옴 — Hands 컴포넌트 stream 미작동.")
                print("    다음 시도: --show-hands 추가 (hideLeft/Right=False로 monkey-patch)")
            elif cam_e >= cam * 0.9 and cam > 0:
                print("  → 시나리오 A: 이벤트 들어오는데 event.value 구조가 코드 가정과 다름.")
                print("    위 traceback과 'first event.value' dump를 보고 핸들러 보정 필요.")
            elif (cam > 0 or hand > 0) and cam_e + hand_e == 0:
                print(f"  → 핸들러 호출 + 파싱 정상 (cam={cam}, hand={hand}, errors=0).")
                print("    lost가 여전히 100%이면 시나리오 C: Process 분리 / shared array 미공유.")
            else:
                print("  → 분류 불가. 위 카운터/traceback을 공유해주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
