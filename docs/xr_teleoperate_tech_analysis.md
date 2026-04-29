# xr_teleoperate 기술 스택 분석 보고서

**작성일**: 2026년 4월 22일
**대상**: xr_teleoperate 내부 구성 기술의 수준, 한계, 개선 방안 분석

---

## 개요

xr_teleoperate는 **6개의 주요 기술 계층**으로 구성됩니다:

1. **XR 입력 취득** (televuer, Vuer 기반 WebXR)
2. **이미지 스트리밍** (teleimager, ZeroMQ + WebRTC)
3. **손 리타게팅** (dex-retargeting, AnyTeleop 계열)
4. **역기구학 IK** (Pinocchio + CasADi)
5. **로봇 통신** (Unitree DDS, unitree_sdk2_python)
6. **데이터 수집 + 학습** (episode_writer + ACT)

각각 학계·산업계에서 검증된 기술을 채택했지만, 2024년 이후 더 발전된 대안이 속속 등장하면서 일부 구성요소는 최적이 아닐 수 있습니다. 하나씩 분석합니다.

---

## 1. XR 입력 취득: televuer (Vuer 기반)

### 채용 기술

**Vuer**는 Ge Yang(MIT) 등이 2024년에 공개한 **Python 기반 WebXR 프레임워크**입니다. 핵심 구조:

- **WebXR Device API**: 브라우저가 VR/AR 기기와 통신하는 W3C 표준. 모든 주요 XR 헤드셋 내장 브라우저에서 지원
- **Three.js / WebGL**: 3D 렌더링 엔진 (브라우저 내 하드웨어 가속)
- **WebSocket**: Python 서버 ↔ 헤드셋 브라우저 간 양방향 통신 (pose 데이터 수신)
- **HTTPS + Self-signed SSL**: WebXR이 HTTPS만 허용해서 인증서 필수

televuer는 Vuer를 Unitree 환경에 맞게 래핑한 버전으로, TeleData 구조체로 head/wrist/hand/controller pose를 통합 제공합니다.

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| 크로스 플랫폼 | ★★★★★ | Vision Pro, Quest 3, PICO 4, Galaxy XR 모두 지원 |
| 설치 난이도 | ★★★★☆ | 헤드셋에 앱 설치 불필요, 브라우저만 있으면 OK |
| 성능 (Native 대비) | ★★★☆☆ | WASM 경유로 Native Unity/OpenXR 대비 ~20-30% 낮음 |
| 안정성 | ★★★☆☆ | 브라우저 업데이트에 취약 (Quest Browser 깨진 사례) |
| 개발 생산성 | ★★★★★ | 헤드셋 빌드/서명 불필요, 바로 반복 테스트 |

### 한계점

**한계 1: 브라우저 벤더 의존성**
WebXR 구현이 브라우저 벤더마다 다르고, 업데이트로 깨질 수 있습니다. 2025년 초 Quest Browser 업데이트로 Vuer hand tracking이 완전히 망가져 Wolvic 브라우저로 우회해야 했던 사례가 있었습니다. Galaxy XR Chrome도 동일 위험이 있습니다.

**한계 2: Eye tracking 접근 제한**
WebXR 표준에는 gaze input이 있지만 데이터 접근이 permission-gated되어 있고, 일부 브라우저는 아직 미지원. Galaxy XR Chrome이 실제로 eye gaze 데이터를 JavaScript로 노출하는지는 실측 필요.

**한계 3: Latency 누적 구조**
취득 체인: Headset sensor → Chrome native → WebXR JS API → WebGL → WebSocket → Python. Native OpenXR 대비 한 단계 더 거침. 실측 20-50ms 추가 지연.

**한계 4: 카메라 raw 데이터 접근 불가**
Galaxy XR의 world-facing 카메라 raw stream에는 WebXR으로 접근 못 함 (프라이버시). HaMeR 같은 고정밀 hand pose 추정을 PC에서 돌리려 해도 카메라 프레임을 얻을 방법이 없음.

**한계 5: SSL 인증서 번거로움**
self-signed cert를 사용자가 매번 수동 신뢰해야 함. 재부팅 후 초기화되기도 함.

### 개선 방안

**개선 A (Quick win): Native Android XR 앱으로 이식**
Jetpack XR SDK + Kotlin으로 native app 개발. APK로 빌드해서 sideload. 장점:
- Latency 20-50ms 감소
- Eye tracking 접근 자유
- 브라우저 업데이트 리스크 제거
- `XR_ANDROID_camera` 확장으로 카메라 raw 접근 가능 (권한 필요)

단점: Unity/Kotlin 개발 공수 (~4주), APK 빌드·배포 필요

**개선 B (Middle ground): WebSocket 대신 WebRTC DataChannel**
Vuer 유지하되 pose 데이터 전송만 WebRTC로 교체. UDP 기반이라 WebSocket(TCP) 대비 lower latency.

**개선 C (Long term): XRoboToolkit 병용**
XRoboToolkit의 Unity Client를 Galaxy XR용으로 빌드. Vuer의 단점을 모두 해소. SII 2026 Best Paper로 안정성 검증됨. 단, 이식 공수가 큼.

---

## 2. 이미지 스트리밍: teleimager (ZeroMQ + WebRTC)

### 채용 기술

teleimager는 2025년 공개된 Unitree 공식 멀티 카메라 스트리밍 서버로, **이중 transport 구조**를 채택했습니다:

- **ZeroMQ (PUB-SUB)**: LAN 내 고품질 전송. TCP 기반. 데이터 수집용
- **WebRTC + H.264/H.265**: VR 헤드셋 저지연 전송. UDP 기반. 조종 피드백용
- **turbojpeg 하드웨어 가속 인코딩**: CPU 부담 감소
- **UVC/OpenCV/RealSense SDK 통합**: 다양한 카메라 드라이버 지원

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| Latency | ★★★★☆ | WebRTC는 glass-to-glass 120-200ms |
| 멀티 카메라 지원 | ★★★★★ | head + wrist L/R 기본 3채널 검증 |
| 대역폭 효율 | ★★★★☆ | H.264 실시간 압축 |
| 확장성 | ★★★★☆ | UVC 기반이라 신규 카메라 쉬움 |
| 문서화 | ★★☆☆☆ | DeepWiki 정도만 있음 |

### 한계점

**한계 1: Depth stream 처리 제한적**
RealSense D405의 depth 정보가 RGB에 비해 활용도가 낮음. depth를 그대로 네트워크 전송하지 않고 PC 측에서 별도 처리 필요. 3D GS 같은 응용에 바로 연결 어려움.

**한계 2: 동기화 보장 없음**
3대 카메라의 타임스탬프 정렬이 sub-frame 수준으로 강하게 보장되지 않음. 양 손목 카메라와 egocentric 간 시간차가 수십ms 발생 가능.

**한계 3: 스테레오 처리는 SBS(Side-By-Side) 수동 처리**
Egocentric 스테레오를 위해 D405 좌우 이미지를 side-by-side로 이어붙여 전송. 진정한 stereo video stream이 아니라 임시 방편. VR 헤드셋 쪽에서 분할 렌더링 필요.

**한계 4: Jitter 제어 약함**
WebRTC 자체는 congestion control이 있지만 bitrate 동적 조정이 공격적이지 않음. WiFi 품질 저하 시 품질 급락.

**한계 5: NVIDIA CloudXR 대비 성능 갭**
CloudXR은 AV1 + RTX GPU 인코딩으로 <100ms 달성 가능. teleimager는 이 수준 아님.

### 개선 방안

**개선 A (Quick win): NVENC GPU 인코딩으로 전환**
기봉님의 RTX 4090/5090을 활용. teleimager 인코더를 libx264 → NVENC H.264/H.265로 교체. 인코딩 latency 50% 감소 예상.

**개선 B (Middle ground): AV1 코덱 도입**
Android XR Chrome 136+이 WebRTC H.265와 AV1 지원. H.264 대비 동일 화질에서 대역폭 30-40% 절감 가능. 단, AV1 인코딩은 최신 GPU만 가능.

**개선 C (New feature): Depth stream 별도 channel 추가**
RGB는 WebRTC로, Depth는 ZeroMQ로 분리 전송. PC에서 point cloud 복원 후 3D overlay에 활용 (기봉님의 3D GS 계획과 연결).

**개선 D (Long term): NVIDIA CloudXR.js 전환**
상용 수준 초저지연. Android XR 공식 지원. 단, NVIDIA 생태계 락인 발생.

---

## 3. 손 리타게팅: dex-retargeting

### 채용 기술

**dex-retargeting은 AnyTeleop 프로젝트(RSS 2023, NVIDIA+UCSD)의 오픈소스 파생**으로, dexsuite 조직이 유지 관리합니다. 핵심 알고리즘:

- **MANO 손 모델**: 학계 표준 매개변수 기반 손 모델 (Max Planck)
- **Pinocchio 기반 URDF 로봇 기구학**: 관절 각도 → fingertip 위치 FK
- **3종 Optimizer**:
  - **PositionOptimizer**: fingertip 위치 3D 좌표를 직접 매칭 (L2 loss)
  - **VectorOptimizer**: fingertip 간 상대 벡터 매칭 (손 크기 차이에 강건)
  - **DexPilotOptimizer**: DexPilot(NVIDIA 2020) 아이디어 계승, pinch 동작 특화
- **Nonlinear optimization (IPOPT via CasADi)**: 관절 한계 제약 준수

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| 알고리즘 완성도 | ★★★★☆ | RSS 2023에서 검증, 9개 이상 그리퍼 지원 |
| 속도 | ★★★★☆ | per-frame 수 ms (CPU), 실시간 적합 |
| 새 로봇 추가 난이도 | ★★★☆☆ | YAML config 작성 필요, fingertip 매핑 수동 |
| 정확도 | ★★★☆☆ | DexMachina(2025) 대비 뒤처짐 |
| 유지보수 | ★★★★☆ | numpy 2.x 호환, 최근 업데이트 활발 |

### 한계점

**한계 1: Interpenetration (자기충돌) 보장 없음**
손가락끼리 또는 손과 물체 사이 interpenetration이 발생할 수 있음. DexFlow(2025) 논문에서 **기존 dex-retargeting 대비 penetration depth 90% 감소** 성과 보고 — 반대로 말하면 기존 구현은 심각한 interpenetration 문제가 있음.

**한계 2: Object-aware retargeting 부재**
물체의 형상이나 접촉 정보를 고려하지 않음. 같은 손 동작이라도 "컵 잡기" vs "볼트 돌리기"에서 최적 손가락 배치가 다른데 구분 못 함.

**한계 3: MANO ↔ 로봇 손 형태 차이 미흡 처리**
DG-5F는 MANO 기반 사람 손과 관절 수·길이·비율이 다름. scaling_factor YAML 튜닝만으로는 완전히 해결 안 됨. 특히 thumb opposition(엄지 마주치기) 재현 어려움.

**한계 4: Config 작성이 수공예**
새 로봇 핸드 추가 시 fingertip link 이름, MANO joint 인덱스 매핑, optimization weight를 수동으로 작성. DG-5F 초기 setup에 실제로 3-5일 소요 예상.

**한계 5: Velocity/acceleration 고려 안 함**
매 프레임 독립 최적화. 시간 일관성 보장 안 됨. 결과적으로 jitter 발생해 후처리 filter 필요.

### 개선 방안

**개선 A (Quick win): Temporal smoothing 추가**
출력에 exponential moving average 또는 Savitzky-Golay filter 적용. dex-retargeting 코드 최소 수정으로 가능.

**개선 B (Middle ground): DexMachina 방식 2-stage retargeting**
DexMachina(NeurIPS 2025)는 Stage 1에서 충돌 없는 joint 해 구하고, Stage 2에서 rollout으로 smoothing. dex-retargeting 결과에 2-stage refinement 후처리 추가.

**개선 C (연구 방향): DexFlow 방식 object-centric refinement**
DexFlow(2025)는 물체 인지 기반 refinement로 penetration 90% 감소. 기봉님의 FoundationPose + Grounding DINO 파이프라인과 결합해서 object-aware retargeting 가능. Key insertion 같은 정밀 작업에 특히 유리.

**개선 D (Long term): Learning-based retargeting**
Optimization 기반이 아닌 neural network로 end-to-end retargeting. Inference 수백 μs로 더 빠름. 학습 데이터 필요하므로 장기 과제.

---

## 4. 역기구학 IK: Pinocchio + CasADi

### 채용 기술

- **Pinocchio 3.1**: INRIA Stack-of-Tasks 팀이 개발한 **고성능 rigid body 동역학 라이브러리**. C++ 코어에 Python 바인딩. Forward kinematics, Jacobian 계산 등 수 μs 수준
- **CasADi**: 심볼릭 미분 + 비선형 최적화 프레임워크. IPOPT 솔버 백엔드 활용
- **NLP 형태의 IK**: desired wrist pose ↔ current FK pose 오차 최소화 + 관절 한계 제약

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| 수치적 안정성 | ★★★★★ | Pinocchio는 학계 표준 |
| 속도 | ★★★★☆ | 수 ms per solve, 실시간 적합 |
| 가용성 | ★★★★★ | Open source, 활발한 개발 |
| Singularity 처리 | ★★★☆☆ | CasADi가 도움 주지만 완벽하지 않음 |
| Dual-arm coordination | ★★★☆☆ | Unitree 휴머노이드 특화 구조 |

### 한계점

**한계 1: Task priority 구조 없음**
Pinocchio 생태계에서 **pink 라이브러리**가 task-based IK를 제공하지만 xr_teleoperate는 pink를 사용하지 않음. Position task + posture task + CoM task를 우선순위로 풀지 못함. 단일 비용함수 가중합 방식이라 튜닝 어려움.

**한계 2: 충돌 회피 미내장**
Self-collision, obstacle avoidance가 IK 단계에 없음. 별도 collision checker 필요. cuMotion 같은 GPU 가속 solver 대비 뒤처짐.

**한계 3: 단일 스레드**
여러 pose target을 병렬로 못 품. cuMotion은 수백 trajectory를 GPU에서 동시 최적화.

**한계 4: 초기값 민감성**
Nonlinear optimization 특성상 초기값이 나쁘면 local minimum 또는 발산. xr_teleoperate는 이전 프레임 q를 initial guess로 씀 (reasonable heuristic).

**한계 5: UR10e 같은 6DoF arm에는 overkill**
6DoF arm은 analytical IK 솔루션이 존재 (ikfast). Numerical optimization이 과잉. 단, 성능 손해는 미미.

### 개선 방안

**개선 A (Quick win): pink 라이브러리로 전환**
Stack-of-Tasks pink는 Pinocchio 기반 task-priority IK. Frame task + posture task + damping task 구성으로 singularity robust. 기봉님의 기존 PINK pipeline과도 호환.

**개선 B (Middle ground): cuMotion 통합**
NVIDIA cuMotion은 RTX GPU에서 수십 ms에 collision-aware 최적 경로 계산. MoveIt2 플러그인 제공. UR10e에 이미 공식 지원. 기봉님이 이미 계획 중인 부분.

**개선 C (Special case): UR10e는 analytical IK 사용**
ikfast로 생성한 UR10e 전용 analytical solver는 수 μs에 8개 해 모두 반환. 과제 특성상 충분. dex-retargeting만 numerical 사용.

---

## 5. 로봇 통신: Unitree DDS / unitree_sdk2_python

### 채용 기술

- **CycloneDDS / Fast-DDS**: ROS 2가 쓰는 표준 통신 미들웨어. Unitree가 robot-PC ↔ onboard computer 간 채택
- **Topic 기반 pub-sub**: `rt/lowcmd` (publish, 250Hz), `rt/arm_sdk` (motion mode), `rt/lowstate` (subscribe, 500Hz)
- **LowCmd / LowState IDL 메시지**: motor별 q, dq, tau, kp, kd 지령 포함

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| Real-time 성능 | ★★★★★ | 500Hz 안정, industrial-grade |
| 확장성 | ★★★★☆ | DDS는 스케일 잘 됨 |
| Unitree lock-in | ★☆☆☆☆ | IDL 메시지가 Unitree 전용 |
| Python 바인딩 완성도 | ★★★★☆ | unitree_sdk2_python 활발 |

### 한계점

**한계 1: UR/DG-5F에 전혀 쓸모 없음**
이 부분이 xr_teleoperate의 **가장 심각한 lock-in**. Unitree 생태계 밖에서는 전부 재작성 필요.

**한계 2: Safety Monitor가 Unitree 전용**
Motion mode weight transition, lower body lock 등은 G1/H1 로봇 전용 로직. UR10e에 부적합.

### 개선 방안

이 부분은 기봉님 환경(UR+DG-5F)에서는 **전면 교체 필수**. 주 계획서에 이미 반영된 대로:

- 조종PC는 televuer → retargeting → ZMQ publish (target pose)
- 로봇PC는 ZMQ subscribe → 기존 ur_rtde + PINK pipeline 유지

---

## 6. 데이터 수집 + 학습: episode_writer + ACT

### 채용 기술

- **episode_writer.py**: HDF5 포맷으로 (observation, action, reward) 시퀀스 저장. LeRobot 호환
- **ACT (Action Chunking Transformer, RSS 2023)**: Tony Zhao(Stanford) 등의 imitation learning 알고리즘
  - Transformer encoder-decoder 구조
  - **Action chunking (k=60-100)**: k스텝 future action을 한 번에 예측 → compounding error 감소
  - **CVAE (Conditional VAE)**: human demonstration 내 multimodal 행동 처리
  - **Temporal ensembling**: 추론 시 겹치는 action chunk 평균으로 smoothing

### 기술 수준 평가

| 항목 | 수준 | 비고 |
|---|---|---|
| 데이터 효율성 | ★★★★☆ | 10분 demo로 80-90% 성공률 |
| 모델 크기 | ★★★★☆ | 수천만 파라미터, 추론 빠름 |
| 학습 안정성 | ★★★☆☆ | Diffusion Policy보다 불안정 |
| SOTA 대비 성능 | ★★★☆☆ | 2023 모델, 이후 발전이 더 큼 |

### 한계점

**한계 1: Multimodal 행동 분포 약함**
CVAE는 사용하지만 Diffusion Policy 대비 multimodal 능력 떨어짐. 동일 상황에서 여러 정답이 가능할 때(예: 물체 어느 쪽으로든 집어도 OK) ACT는 averaging으로 수렴 → 부자연스러운 동작.

**한계 2: Long-horizon 태스크에 약함**
Action chunk 범위(k=60-100)를 넘어서는 장기 계획 못 함. Key insertion 같은 multi-step 태스크에는 한계.

**한계 3: Force/torque 입력 미지원**
기본 구조는 visual + proprioceptive만 씀. F/T 입력 추가하려면 개별 수정. 기봉님의 F/T 시각화 계획과 별도로, 제어 입력으로 F/T 사용하려면 개조 필요.

**한계 4: VLA 시대에 뒤처짐**
2024년 이후 OpenVLA, π0, GR00T N1.5 등 Vision-Language-Action 모델이 등장. 자연어 명령을 받고 일반화 능력이 훨씬 높음. ACT는 task-specific.

**한계 5: Diffusion Policy 대비 성능 차이**
Diffusion Policy(2023, Shuran Song 팀)가 ACT 대비 **평균 46.9% 높은 성공률** 보고. 2024-2025년 robot manipulation 논문은 대부분 Diffusion 계열 baseline.

### 개선 방안

**개선 A (Quick win): Diffusion Policy로 교체**
episode_writer 출력(HDF5)을 그대로 사용 가능. LeRobot 프레임워크에 Diffusion Policy 구현 포함되어 있음. 전환 공수 작고 성능 향상 큼.

**개선 B (Middle ground): F/T 입력 추가 커스텀**
ACT 또는 Diffusion Policy의 observation encoder에 F/T 6-dim 추가. Key insertion 같은 contact-rich 태스크에 필수.

**개선 C (연구 방향): VLA 기반 fine-tuning**
OpenVLA 또는 π0 같은 foundation model을 DG-5F + UR10e 데이터로 fine-tune. 일반화 능력 대폭 향상. 단, 데이터 수집 규모 커야 함.

**개선 D (기봉님 로드맵 연결): Shared Autonomy용 학습**
기봉님의 Residual Copilot은 VLA 위에 residual RL head 올리는 구조. xr_teleoperate로 수집한 demo를 VLA 학습에 활용하고, RL 학습은 별도 pipeline.

---

## 종합 평가

### 강점 요약

xr_teleoperate는 **2023-2024년 오픈소스 텔레오퍼레이션 SOTA를 조합한 practical system**입니다:

- Vuer로 크로스 플랫폼 XR 지원
- AnyTeleop 계열 dex-retargeting으로 다양한 손 지원
- Pinocchio 기반 IK로 수치적 안정성
- teleimager로 멀티 카메라 스트리밍 통합
- ACT로 imitation learning baseline 제공

즉 **각 계층에서 RSS/CoRL 급 논문에서 검증된 기술**만 조합해서 **실제로 돌아가는 시스템**으로 만들었다는 점이 핵심 가치입니다.

### 약점 요약

| 계층 | 주요 약점 | 심각도 |
|---|---|---|
| Vuer/televuer | 브라우저 의존성, Native 대비 20-50ms 추가 latency | 중 |
| teleimager | Depth 처리 약함, 동기화 보장 없음 | 중 |
| dex-retargeting | Interpenetration, object-aware 부재 | 중 |
| Pinocchio IK | Pink 미사용, GPU 가속 없음 | 낮 |
| Unitree DDS | 생태계 lock-in | 상 (UR 환경) |
| ACT | 2023년 기준 SOTA, 현재는 뒤처짐 | 중 |

### 우선순위별 개선 권장

**Phase 1 (즉시 반영 가능, Quick win)**

1. **Diffusion Policy로 학습 알고리즘 교체** — LeRobot에 구현 내장, 같은 데이터로 성능 향상 기대
2. **teleimager NVENC 전환** — RTX 4090/5090 활용해 latency 감소
3. **dex-retargeting 출력에 temporal smoothing** — EMA 또는 Savgol filter 추가

**Phase 2 (중기, 1-2개월 공수)**

4. **pink 기반 task-priority IK 도입** — xr_teleoperate의 robot_arm_ik.py를 pink 스타일로 재작성
5. **teleimager stereo/depth 채널 분리** — 기봉님의 3D GS 계획과 연결
6. **F/T 시각화 AR overlay** — 이미 별도 Phase로 계획 중

**Phase 3 (장기, 연구 과제)**

7. **Native Android XR app으로 Vuer 교체** — latency 최소화, eye tracking 풀 활용
8. **DexFlow 방식 object-aware retargeting** — FoundationPose와 결합
9. **VLA foundation model 기반 Shared Autonomy** — 기봉님의 Residual Copilot 구현

### 기봉님 프로젝트와의 연결

현재 xr_teleoperate를 바탕으로 해야 하는 12주 계획을 감안할 때, **Phase 1 개선은 바로 적용 가능**하고 Phase 2는 Week 10-12의 개선 기간에 자연스럽게 편입됩니다. Phase 3는 기봉님이 이미 연구 방향으로 설계한 Residual Copilot, GazeSAM + cuMotion, F/T visualization과 정확히 일치하니, xr_teleoperate를 1단계로 완성한 후 점진적으로 확장하는 구조가 가장 실현 가능합니다.

결론적으로 xr_teleoperate 채택은 **기술적으로 안전한 선택**이며, 드러난 한계들은 대부분 기봉님이 이미 인지하고 계신 확장 과제들과 맞닿아 있습니다. 각 한계가 어떤 새 기술로 대체되어야 하는지 이해하고 출발하면, 12주 후의 Phase 5+ 확장 시 바로 연결할 수 있습니다.

---

*끝.*
