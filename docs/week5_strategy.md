# Week 5 진입 전략 (Strategy only — plan 별도)

> Week 4 Gate 4 통과 (Quest 3 기준, [week4_report.md](week4_report.md)) 후 Week 5 진입 방향. **구체 plan 은 사용자 선택 후 별도 plan mode 에서**.

## 1. 12 주 원본 계획 vs 현재 상태

CLAUDE.md weekly plan (Phase 1 종료 시점 기준):

| Week | 원본 계획 | 현재 상태 |
|---|---|---|
| 4 | URDF + IK 를 UR10e 용으로 교체 | ✅ 완료 (commit `c18cf51`) |
| **5** | **DG-5F dex-retargeting config 작성** | ✅ **Week 4 에서 선행 완료** (U1 + U5++) |
| 6 | IsaacSim 에서 UR10e+DG-5F 통합 (Gate 4) | ✅ **Week 4 에서 선행 통과** (사용자 visual 확인) |
| 7 | 조종 PC / 로봇 PC 분리 프로토콜 | 미진입 (Phase 3) |
| 8 | 실로봇 초기 통합 (저속) | 미진입 (Phase 3) |

→ **원본 Week 5–6 작업이 Week 4 에서 선행 완료** 됨 (sim docker 가 Week 3 마지막에 완성된 덕분). **Week 5 를 새로 정의**해야 함.

## 2. Week 5 재정의 — 3 가지 우선순위 트랙

원본 계획상 Week 5–6 의 sim refinement 시간이 압축되어 **약 2 주 여유** 발생. 이를 다음 3 트랙 중 1–2 개에 배분.

### Track A — Week 4 closeout + Galaxy XR 본기 검증 (1–2 일)

**가치**: 본 프로젝트 최종 타겟이 Samsung Galaxy XR. Quest 3 검증만으로는 unvalidated.

작업 항목:
- A1. Galaxy XR + USB-C 연결 + `adb reverse tcp:8013/60001/60003` setup 검증
- A2. `run_teleop_ur10e_ws.py` 실측 — Galaxy XR Chrome → ws bridge → DG-5F 동작 확인
- A3. fist↔spread inversion 발생 시 DexPilot convention toggle (mediapipe ↔ manus matrix row 1 sign)
- A4. Galaxy XR 측 vuer scene 영상 표시 (ws bridge 는 hand pose only — 영상 별도 검증)
- A5. week4 closeout — Gate 4 사용자 measurement 양식 ([day5_e2e_spike.md §3](week4/day5_e2e_spike.md)) 정량 채움

**위험도**: 낮음. 코드는 이미 작성됐고 실측 + 미세 조정만.

### Track B — Recording infrastructure 진입 (3–5 일)

**가치**: 12 주 계획 후반 (Phase 4) imitation learning 진입의 사전 작업. 데이터 수집 인프라가 없으면 Week 10+ 측정 자체 불가.

작업 항목:
- B1. `teleop_hand_and_arm.py` 의 `EpisodeWriter` (ACT/LeRobot 호환) 분석 — Quest 3 entry 와 호환되는지
- B2. `run_teleop_ur10e.py` 에 `--record` 분기 추가 — sim 측 sim_state subscribe + hand/arm trajectory 저장
- B3. recording 형식: ACT 호환 (`color_*`, `qpos`, `qvel`, sim_state JSON)
- B4. recording 단위 테스트: 5 초 sample 저장 → HDF5 / npz 파일 검증
- B5. replay 도구 — 저장된 trajectory 를 sim 에 다시 publish (Phase 4 Diffusion Policy 사전 작업)

**위험도**: 중간. EpisodeWriter 의 UR10e+DG-5F 적응이 어느 정도 작업 필요. ACT trajectory format 정확성 검증.

### Track C — Phase 3 사전 설계 (Real robot bridge) (2–4 일)

**가치**: Phase 3 (Week 7-9) 진입 시 필요한 **DDS ↔ ur_rtde + DG-5F Modbus** 변환 layer 설계.

작업 항목:
- C1. `standalone/core/ur_robot.py` (기존 RTDE backend) 분석 — DDS rt/lowcmd 를 ur_rtde servoJ 로 변환
- C2. DG-5F Modbus interface (`src/dg5f_ros2/`) — DDS rt/dg5f/cmd 를 Modbus write_holding_registers 로 변환
- C3. 새 brigde script: `scripts/dds_to_real.py` — 양방향 변환 (state ← real, cmd → real)
- C4. 안전: workspace boundary + IK fail handling — Quest 3 가 reach 밖 보내면 last_valid q 유지
- C5. 저속 운영 mode (`--max-vel 0.2 rad/s`) — Phase 3 Week 8 의 초기 안전 운영용

**위험도**: 높음. real robot 접근 필요 — 본 docker 에서 시뮬레이션 단계만 작성 가능. 실 검증은 Phase 3.

## 3. Track 비교 표

| Track | 우선순위 | 작업 기간 | 위험도 | Phase 3 사전 가치 | Week 4 마무리 가치 |
|---|---|---|---|---|---|
| **A** Galaxy XR + closeout | **High** | 1–2 일 | 낮음 | 직접 안 됨 | **직접** ✅ |
| **B** Recording infra | Medium | 3–5 일 | 중간 | 데이터 수집 사전 | 직접 안 됨 |
| **C** Real robot bridge | Medium | 2–4 일 | 높음 | **직접** ✅ | 직접 안 됨 |

## 4. 추천 진행 방향 (3 옵션)

### 옵션 R1 — A + B (보수적, Phase 3 진입 늦춤)
**Week 5 = A (Galaxy XR closeout) → B (Recording)** | **Week 6 = C (Real robot bridge)**
- 본 docker / sim 단계 완전 마무리 → Phase 3 진입
- 장점: 안전한 단계적 진행. 데이터 수집 인프라 충분 검증
- 단점: Phase 3 진입이 Week 7 로 미뤄짐

### 옵션 R2 — A + C (공격적, Phase 3 빠른 진입) **[Recommended]**
**Week 5 = A → C** | **Week 6 = Phase 3 real robot 초기 통합**
- Galaxy XR closeout + real bridge 사전 설계 → Week 6 부터 real robot
- 장점: 원본 12 주 계획 (Week 7-8 real robot) 일정 빠른 진입
- 단점: Recording 은 Week 10+ 까지 미뤄짐 (imitation learning 사전 작업 늦음)

### 옵션 R3 — B 만 집중 (Phase 4 imitation learning 우선)
**Week 5–6 = B 깊게** | **Week 7 = C → Phase 3 진입**
- ACT / Diffusion Policy 사전 작업 충분 시간
- 장점: 후반 데이터 수집 / 정책 학습 안정
- 단점: Phase 3 진입 늦음. Galaxy XR 검증 미진행 위험

## 5. 결정 필요 항목 (사용자)

다음 결정 후 별도 plan mode 에서 Week 5 detailed plan 작성:

1. **트랙 선택**: R1 / R2 / R3 / 다른 조합
2. **Galaxy XR 실측 가능성**: 본기 보유 + USB-C + adb 사전 조건 충족? (Track A 진행 가능 여부)
3. **Real robot 접근 시점**: 본 docker 에서 bridge 설계만 vs 실 robot 환경 접근? (Track C 깊이)
4. **Recording 형식**: ACT 호환 (HDF5) / LeRobot (parquet) / 자체 (npz) — Track B 진입 시
5. **Phase 3 진입 일정**: Week 6 (옵션 R2) vs Week 7 (옵션 R1/R3)

## 6. 미해결 항목 — 트랙 무관 처리 필요

Week 4 에서 이월된 미해결 issue (track 와 별도로 진행):

| ID | 항목 | 처리 시점 |
|---|---|---|
| O1 | Galaxy XR 본기 실측 | Track A (Week 5 시작) |
| O2 | DexPilot convention 확정 (mediapipe vs manus) | Track A 의 A3 |
| O3 | UR10e workspace boundary + IK fail handling | Track C 의 C4 또는 별도 |
| O4 | wrist 카메라 (60003) vuer scene 표시 | Week 9 multi-camera (이월 그대로) |
| O5 | UR10e init pose 사용자 튜닝 정합성 | Track A 또는 사용자 자체 결정 |

## 7. 다음 단계

본 전략 검토 후 사용자가:
1. 트랙 (R1 / R2 / R3) 선택
2. 또는 다른 우선순위 제시

→ 그 결과로 **plan mode 진입**해 Week 5 detailed plan 작성 (각 작업 단위 분해 + spike + 검증 절차).
