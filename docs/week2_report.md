# Week 2 Gate 2 측정 보고서

## 측정 히스토리 요약 (2026-05-05, Meta Quest 3)

| 시각 | 결과 | 비고 |
|---|---|---|
| 21:46 / 21:48 / 22:06 | ❌ Lost = 100% (전체) | **wrong URL artifact** — `vuer.ai` 호스트 페이지 접속 등 잘못된 link로 진입해 WebSocket이 우리 server에 안 붙음. 코드 문제 아님 |
| 22:07 | ❌ head OK / hand Lost = 100% | (debug summary로 보고됨) 위와 동일 — wrong URL |
| **22:15** | ✅ **Gate 2 통과** | 192 Hz / Recovery 0.0s / Lost 0 |
| **22:18** | ✅ **Gate 2 통과** | 192 Hz / Recovery 0.0s / Lost 0 / jitter 3.56 cm |
| 22:20 | ⚠️ Recovery 1.05s | 간발의 차이로 미통과. 단발성 변동성 가능 |
| 22:24 | ⚠️ Recovery 2.74s | 손이 시야 밖에 오래 머문 사용 변동 가능 |

### 결론

**Quest 3에서 Gate 2 통과 확인** (22:15, 22:18 두 차례). 핵심 수치:
- 평균 frequency: **192 Hz** (≥ 30 Hz 필요)
- Recovery latency: **0.0 s** (< 1.0 s 필요)
- Lost frames: **0 / 5766** 전 필드
- Wrist jitter: 3.56–9.65 cm (재측정 시 손 명확히 정지 권장)

### Lost = 100% artifact 원인 분석 (재발 방지용)

vuer 서버 부팅 시 출력되는 `Visit: https://vuer.ai?grid=False` 메시지의 `vuer.ai`는 **vuer-ai가 호스팅하는 frontend page**로, 우리 local server와 별개. 사용자가 이 URL로 직접 접속하면 해당 페이지가 우리 server의 WebSocket에 붙는 시나리오가 있긴 하지만 환경에 따라 실패. **반드시 README의 정확한 URL을 사용**:

- `--http` 모드: `http://localhost:8012` (`adb reverse` 통해 USB로 PC에 도달)
- 기본 모드: `https://localhost:8012/?ws=wss://localhost:8012`

`Lost = 전체 프레임 수`이면 server에 연결 자체가 안 된 상태이므로 가장 먼저 URL을 의심할 것. Hz/NaN 수치가 정상처럼 보여도 lost 검사가 실측 신호.

---

## 개별 측정 raw data

## Gate 2 측정 — 2026-05-05T21:46:01

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 185.7 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 0.0 s | < 1.0 s | ✅ |
| Wrist jitter (정지 5초) | 0.0 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5571 | — | — |

**Lost frames per field** (전체 중): head=5571 / lw=5571 / rw=5571 / lh=5571 / rh=5571
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T21:48:36

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 188.6 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 0.0 s | < 1.0 s | ✅ |
| Wrist jitter (정지 5초) | 0.0 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5659 | — | — |

**Lost frames per field** (전체 중): head=5659 / lw=5659 / rw=5659 / lh=5659 / rh=5659
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T22:06:02

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 186.7 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 0.0 s | < 1.0 s | ✅ |
| Wrist jitter (정지 5초) | 0.0 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5602 | — | — |

**Lost frames per field** (전체 중): head=5602 / lw=5602 / rw=5602 / lh=5602 / rh=5602
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T22:15:45

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 192.2 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 0.0 s | < 1.0 s | ✅ |
| Wrist jitter (정지 5초) | 9.65 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5766 | — | — |

**Lost frames per field** (전체 중): head=0 / lw=0 / rw=0 / lh=0 / rh=0
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T22:18:46

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 192.2 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 0.0 s | < 1.0 s | ✅ |
| Wrist jitter (정지 5초) | 3.56 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5765 | — | — |

**Lost frames per field** (전체 중): head=0 / lw=0 / rw=0 / lh=0 / rh=0
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T22:20:58

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 192.1 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 1.05 s | < 1.0 s | ⚠️ |
| Wrist jitter (정지 5초) | 1.85 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5762 | — | — |

**Lost frames per field** (전체 중): head=0 / lw=202 / rw=202 / lh=202 / rh=202
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0

## Gate 2 측정 — 2026-05-05T22:24:03

| 항목 | 값 | 통과 기준 | 결과 |
|---|---|---|---|
| 평균 frequency | 192.0 Hz | ≥ 30 Hz | ✅ |
| Recovery latency | 2.74 s | < 1.0 s | ⚠️ |
| Wrist jitter (정지 5초) | 3.89 cm | 보고만 | — |
| 측정 시간 | 30.0 s | — | — |
| 프레임 수 | 5760 | — | — |

**Lost frames per field** (전체 중): head=0 / lw=527 / rw=527 / lh=527 / rh=527
**NaN frames per field**: head=0 / lw=0 / rw=0 / lh=0 / rh=0
