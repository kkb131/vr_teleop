# Galaxy XR 원격조종 시스템 개발 주단위 계획서

**프로젝트**: xr_teleoperate 기반 Galaxy XR + UR10e + DG-5F 원격조종 시스템
**작성일**: 2026년 4월 21일
**총 기간**: 12주 (약 3개월)

---

## 서문: 개발 목적 및 개발 방식 선정 이유

### 개발 목적

현재 연구실의 원격조종 시스템은 Manus Metaglove + Vive Tracker 조합으로 운영 중이며, 이를 **Galaxy XR 단일 디바이스로 대체**하는 것이 목표입니다. Galaxy XR는 다음을 통합 제공합니다:

- 손가락 26-joint tracking (Manus 대체)
- 6DoF 헤드셋/컨트롤러 tracking (Vive Tracker 대체)
- 4K per-eye 스테레오 디스플레이 (로봇 egocentric 카메라 뷰 몰입 표시)
- Eye tracking (향후 gaze-guided manipulation 확장 기반)

단일 디바이스 통합으로 착용 편의성, 캘리브레이션 간소화, 추후 Shared Autonomy 아키텍처와의 통합을 목표로 합니다.

### 왜 xr_teleoperate 기반으로 개발하는가

Galaxy XR용 원격조종 코드를 처음부터 짜는 대신 **검증된 오픈소스 위에 올리는** 방식을 택한 이유:

1. **Production-grade 검증 완료**: Unitree G1/H1/H1_2 실제 로봇에서 데이터 수집까지 구동
2. **Apple Vision Pro, PICO 4 Ultra, Meta Quest 3 호환성 검증됨** → Android XR(Galaxy XR) 이식성 높음
3. **전체 파이프라인 포함**: XR 입력 (televuer) + IK (Pinocchio/CasADi) + 손 retargeting (dex-retargeting) + 멀티카메라 스트리밍 (teleimager) + imitation learning 데이터 수집 (episode_writer)
4. **OpenTeleVision(CoRL 2024)의 후속작**으로 학계·산업계에서 활발히 유지보수
5. **WebXR 기반**이라 Galaxy XR APK 빌드 없이 Chrome 브라우저만으로 동작 가능

### 단계적 접근의 필요성

바로 UR+DG-5F로 이식하지 않고 단계를 나누는 이유:

- **Stage 1 (원본 재현)**: xr_teleoperate와 Galaxy XR의 호환성 검증. 이 단계에서 막히면 전체 전략 재고 필요
- **Stage 2 (로봇 교체, IsaacSim)**: 시뮬레이션에서 UR10e + DG-5F 연동 검증. 실제 로봇 손상 위험 없이 IK, retargeting, 좌표계 변환 디버깅
- **Stage 3 (기존 시스템 통합)**: 검증된 부분만 우리 `ur_rtde servoJ 500Hz pipeline`에 선별적으로 이식. 조종PC/로봇PC 분리 구조 유지
- **Stage 4 (성능 평가)**: Manus+Vive 기존 시스템 대비 정량 비교. 한계와 개선 방향 문서화

단계마다 명확한 **Gate 조건**을 두어 다음 단계 진입 전 검증하는 구조입니다.

### 시스템 구성 (최종 목표)

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│  Galaxy XR   │ WiFi  │    조종 PC        │ LAN   │   로봇 PC     │
│              │ HTTPS │  (Ubuntu 22.04)   │ ZMQ   │  (기존 환경)   │
│  Chrome      │◀─────▶│                   │──────▶│               │
│  + WebXR     │ WSS   │  - televuer       │       │  - ur_rtde    │
│              │       │  - dex-retargeting│       │  - PINK IK    │
│  Hand/Eye/   │       │  - teleimager     │◀──────│  - DG-5F SDK  │
│  Head pose   │       │  - Target Sender  │ state │  - Subscriber │
└──────────────┘       └──────────────────┘       └──────────────┘
                              ▲
                              │ D405 × 3 (egocentric + 양손목)
                              │
                        [RealSense USB 3.0 hub]
```

---

## Phase 1: xr_teleoperate 원본 동작 검증 (Week 1-3)

### Week 1: 개발 환경 구축 및 프로젝트 셋업

**목표**: 조종PC에 xr_teleoperate를 클론·빌드하고 로봇 없이 순수 XR 입력만 취득

**Day 1-2: Ubuntu + Conda 환경 세팅**
- 조종PC OS 확인 (Ubuntu 22.04 or 24.04 권장)
- Conda 환경 생성: `conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge`
- 의존성 라이브러리 설치: meshcat, casadi, pinocchio
- unitree_sdk2_python 설치 (DDS 통신 전제 라이브러리)

**Day 3: 리포지토리 클론 및 서브모듈 초기화**
- `git clone https://github.com/unitreerobotics/xr_teleoperate.git`
- `git submodule update --init --depth 1` (televuer, dex-retargeting 체크아웃)
- televuer: `cd teleop/televuer && pip install -e .`
- dex-retargeting: `cd teleop/robot_control/src/dex-retargeting && pip install -e .`

**Day 4: SSL 인증서 생성 및 네트워크 세팅**
- OpenSSL self-signed 인증서 생성 (televuer 요구사항)
- 조종PC와 Galaxy XR를 같은 WiFi 네트워크 연결 확인
- 방화벽 포트 오픈: 8012 (Vuer WebSocket)
- `ifconfig`로 호스트 IP 확인 (예: 192.168.x.x)

**Day 5: Galaxy XR WebXR 호환성 사전 검증** ⚠️
- Galaxy XR Chrome으로 `https://immersive-web.github.io/webxr-samples/` 접속
- "Immersive VR Session with Hands" 샘플 실행 → 26-joint hand tracking 동작 확인
- 인증서 경고 우회 방법 검증 (설정에서 수동 허용)
- **Gate 1**: WebXR hand tracking이 정상 동작하지 않으면 **Plan B 전환** (XRoboToolkit Unity APK)

**Deliverables**:
- 동작하는 conda 환경 (`tv`)
- 인증서 파일 (cert.pem, key.pem)
- Galaxy XR WebXR 호환성 테스트 결과 문서

---

### Week 2: televuer 단독 검증 (로봇 없이 XR 입력만)

**목표**: xr_teleoperate의 XR 입력 레이어만 돌려서 Galaxy XR → 조종PC로 pose 데이터가 오는지 검증

**Day 1-2: televuer 테스트 프로그램 실행**
- `python teleop/televuer/test/_test_televuer.py` 실행
- Galaxy XR Chrome에서 `https://<host_ip>:8012/?ws=wss://<host_ip>:8012` 접속
- "Enter VR" 버튼 활성화 후 hand tracking 모드로 진입
- 터미널에서 TeleData 객체 내용 모니터링

**Day 3: 좌표계 및 데이터 구조 분석**
- TeleData 필드 파싱:
  - `head_pose`: 헤드셋 6DoF
  - `left_wrist_pose`, `right_wrist_pose`: 양손 손목
  - `left_hand_joints`, `right_hand_joints`: 25-joint
  - `controller`: 컨트롤러 모드일 경우
- WebXR 좌표계와 로봇 베이스 프레임의 변환 관계 문서화

**Day 4: tv_wrapper 후처리 로직 파악**
- `_test_tv_wrapper.py` 실행
- Weighted moving filter, coordinate transform 동작 확인
- 데이터 노이즈 수준 정량 측정 (pose variance)

**Day 5: 스트리밍 성능 측정**
- Frequency 측정 (목표: 30-60Hz 안정)
- WiFi latency 측정 (목표: <50ms)
- Galaxy XR hand tracking 정확도 체크 (손가락 끝 이동 범위)

**Deliverables**:
- televuer 정상 동작 로그
- Galaxy XR pose 데이터 스트림 샘플
- Latency/frequency 벤치마크 보고서
- **Gate 2**: 30Hz 이상 안정적 스트리밍 확인

---

### Week 3: 원본 시뮬레이션 전체 파이프라인 실행 (IsaacSim + G1)

**목표**: xr_teleoperate의 원본 예제(G1 + Dex3-1)를 IsaacSim에서 완전히 돌려 End-to-End 검증

**Day 1-2: unitree_sim_isaaclab 설치**
- `git clone https://github.com/unitreerobotics/unitree_sim_isaaclab.git`
- 별도 conda 환경 `unitree_sim_env` 생성 (xr_teleoperate의 `tv` 환경과 분리)
- IsaacLab 의존성 설치 (NVIDIA Isaac Sim 필요)
- GPU 리소스 확인 (RTX 4090/5090이면 충분)

**Day 3: 시뮬레이션 런칭**
- `python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint --enable_dex3_dds --robot_type g129`
- 시뮬레이션 창 클릭으로 active 상태 전환
- 터미널 출력 "controller started, start main loop..." 확인

**Day 4: xr_teleoperate 원본 실행 및 teleop 테스트**
- 별도 터미널에서 `conda activate tv`
- `python teleop/teleop_hand_and_arm.py --arm G1_29 --hand dex3 --xr-mode hand`
- Galaxy XR에서 VR 진입 후 팔 자세를 로봇 초기 자세에 정렬
- 터미널에서 `r` 키 입력 후 teleoperation 시작
- G1 로봇이 사용자 손 움직임을 모사하는지 IsaacSim 창에서 확인

**Day 5: 데이터 기록 기능 테스트**
- `s` 키로 episode recording 시작/중지
- HDF5 파일 생성 확인
- `episode_writer.py` 동작 방식 코드 레벨 이해

**Deliverables**:
- IsaacSim에서 G1 로봇이 Galaxy XR 입력에 따라 움직이는 영상
- End-to-End latency 측정치
- **Gate 3**: 원본 시스템 완전 동작 시 Phase 2로 진입

---

## Phase 2: IsaacSim에서 UR10e + DG-5F 교체 검증 (Week 4-6)

### Week 4: URDF 교체 및 IK 이식

**목표**: `robot_arm_ik.py`의 G1 URDF를 UR10e URDF로 교체하고 시뮬레이션에서 IK 동작 확인

**Day 1: UR10e URDF 및 DG-5F URDF 준비**
- `assets/` 디렉토리에 URDF 파일 복사
  - `ur10e.urdf` (universal_robot ROS 패키지에서 획득)
  - `tesollo_dg5f.urdf` (기존 보유분 활용)
- Collision mesh, visual mesh 경로 수정
- Pinocchio로 로드 테스트: `pin.RobotWrapper.BuildFromURDF(...)`

**Day 2-3: robot_arm_ik.py 수정**
- 단일 팔용으로 구조 변경 (기존은 dual-arm)
- Wrist target frame 이름 교체:
  - 기존: `left_wrist_yaw_link`, `right_wrist_yaw_link`
  - 변경: `tool0` (UR 표준)
- Joint limits, velocity limits 재설정 (UR10e 사양 기반)
- Lower body lock 로직 제거 (UR은 모바일 베이스 없음)
- CasADi optimization objective 단순화

**Day 4: IK 단위 테스트 스크립트 작성**
- 임의의 wrist target 입력 → 관절 각도 출력
- Meshcat 뷰어로 시각화
- Singularity 회피 동작 확인
- Workspace 경계 근처 동작 테스트

**Day 5: IsaacSim용 UR10e 시뮬레이션 환경 구축**
- IsaacSim에서 UR10e USD 로드 (NVIDIA 공식 제공)
- DG-5F는 USD 변환 필요 (URDF → USD 컨버터 사용)
- 기본 장면: 테이블 + UR10e + DG-5F + 테스트 객체 (실린더)

**Deliverables**:
- 수정된 `robot_arm_ik_ur10e.py`
- IK 단위 테스트 성공 로그
- IsaacSim UR10e 시뮬레이션 환경

---

### Week 5: DG-5F dex-retargeting config 작성

**목표**: MANO 손 모델 → DG-5F 5손가락 관절 매핑 완성

**Day 1: DG-5F 기구학 분석**
- DG-5F 공식 스펙 문서 리뷰
- 손가락별 DoF 확인 (thumb, index, middle, ring, pinky)
- Fingertip frame 이름 목록화
- 관절 한계 표 정리

**Day 2-3: dex-retargeting config YAML 작성**
- `configs/tesollo_dg5f.yml` 신규 작성
  - `retargeting_type`: `vector` (fingertip 위치 매칭)
  - `urdf_path`: DG-5F URDF
  - `target_link_names`: 5개 fingertip link
  - `target_link_human_indices`: MANO 키포인트 인덱스 (4, 8, 12, 16, 20)
  - `target_joint_names`: DG-5F 관절 이름
  - `scaling_factor`: 손 크기 비율 (DG-5F가 사람 손보다 클 경우 ~1.0-1.3)
- AnyTeleop 논문 참고해 optimization weight 튜닝

**Day 4: hand_retargeting.py에 DG-5F 타입 추가**
```python
class HandType(Enum):
    INSPIRE_HAND = 1
    UNITREE_DEX3 = 2
    BRAINCO = 3
    TESOLLO_DG5F = 4   # 추가
```
- `_load_config()` 메서드에 DG-5F 분기 추가
- 관절 인덱스 순서 매핑 테이블 작성

**Day 5: Retargeting 단독 테스트**
- 시뮬레이션 없이 retargeting만 테스트
- 손을 주먹 쥐기 / 펼치기 / 포인팅 동작 → DG-5F 관절 각도 출력
- Meshcat으로 DG-5F 움직임 시각화
- 부자연스러운 각도 발생 시 config 재튜닝

**Deliverables**:
- `configs/tesollo_dg5f.yml`
- Retargeting 단위 테스트 통과
- 대표 손동작 5가지에 대한 DG-5F qpos 출력 기록

---

### Week 6: UR10e + DG-5F IsaacSim 전체 통합 테스트

**목표**: Galaxy XR로 IsaacSim 내 UR10e + DG-5F를 조종할 수 있는지 End-to-End 검증

**Day 1-2: teleop_hand_and_arm.py 수정**
- UR10e + DG-5F 모드 추가 (`--arm UR10E --hand DG5F`)
- IK → 관절 명령 flow를 IsaacSim ROS2 bridge 또는 직접 Python API로 전달
- Unitree DDS 호출부를 IsaacSim 전용 wrapper로 치환

**Day 3: 좌표계 정렬 및 캘리브레이션**
- Galaxy XR WebXR 좌표계 → UR10e base_link 좌표계 변환 행렬 확립
- Wrist 초기 자세를 로봇의 home pose에 매핑
- Pose tracking enable 직전 "align pose" 단계 추가 (기존 로직 재사용)

**Day 4: 시뮬레이션 teleop 연속 동작 테스트**
- 단순 pick 태스크: 테이블 위 실린더 집기
- Wrist 이동 + 손 쥐기 동작 조합
- 성능 측정:
  - End-to-End latency (headset pose → sim robot 반응)
  - Tracking error (desired vs actual TCP pose)
  - 손가락 retargeting 품질 (주관 평가)

**Day 5: 버그 수정 및 안정화**
- 발견된 이슈 해결 (좌표계 flip, 관절 wrap-around, IK 발산 등)
- 코드 refactoring
- 설정값 YAML로 분리 (하드코딩 제거)

**Deliverables**:
- IsaacSim에서 Galaxy XR + UR10e + DG-5F 조종 영상 (3종 태스크 이상)
- 성능 측정 보고서
- 이슈 트래커 (해결/미해결 목록)
- **Gate 4**: 시뮬레이션 안정 동작 시 실로봇 이식 진행

---

## Phase 3: 실제 시스템 이식 및 분리 아키텍처 구현 (Week 7-9)

### Week 7: 조종PC/로봇PC 분리 아키텍처 설계 및 구현

**목표**: xr_teleoperate의 모놀리식 구조를 분리하여 기존 `ur_rtde servoJ 500Hz pipeline`과 통합

**Day 1: 프로토콜 설계**
- 조종PC → 로봇PC 송신 메시지 스키마 정의
  - `timestamp`: 동기화용
  - `wrist_target_pose`: 4×4 SE(3) 행렬
  - `gripper_qpos`: DG-5F 관절 각도 벡터
  - `teleop_state`: ENABLE/DISABLE/EMERGENCY_STOP
- 로봇PC → 조종PC 피드백 메시지 (추후 시각화용)
  - `actual_tcp_pose`, `joint_states`, `ft_wrench`
- Serialization: ZeroMQ PUB-SUB + MessagePack (JSON 대비 저지연)

**Day 2-3: 조종PC 측 Target Sender 모듈 구현**
- 신규 파일: `teleop/robot_control/robot_arm_ur10e_sender.py`
- 기존 `robot_arm.py`의 구조는 참고하되 DDS 부분 완전 제거
- televuer → tv_wrapper → (간단 변환) → ZMQ publish 구조
- `robot_hand_dg5f_sender.py`도 동일 패턴

**Day 4: 로봇PC 측 Subscriber 통합**
- 기봉님의 기존 `ur_rtde servoJ 500Hz` 프로세스에 ZMQ subscriber 추가
- 수신된 target pose → PINK IK → servoJ 호출 체인 구성
- DG-5F 수신 → Tesollo SDK 호출
- Safety Monitor (기존 4-level) 유지
- 통신 끊김 시 현재 자세 hold 로직 추가

**Day 5: 통합 시뮬레이션 (로봇 없이 프로토콜만)**
- 조종PC에서 dummy target 송신
- 로봇PC에서 수신 + 로그 출력만
- Round-trip latency 측정
- 메시지 loss 체크

**Deliverables**:
- 조종PC sender 모듈 2개
- 로봇PC subscriber 통합 코드
- 프로토콜 spec 문서 (`protocol_v1.md`)

---

### Week 8: 실로봇 초기 통합 (저속 모드)

**목표**: 실제 UR10e + DG-5F 하드웨어에서 Galaxy XR 조종 동작. 안전 우선

**Day 1: 하드웨어 체크리스트**
- UR10e teach pendant로 수동 동작 확인
- DG-5F 캘리브레이션 상태 확인
- Emergency stop 버튼 위치 및 동작 확인
- 작업 공간 내 장애물 제거
- 관찰자 1명 상주 (Emergency stop 담당)

**Day 2: UR10e 조종 테스트 (손은 제외)**
- 속도 scale 10% (매우 느리게)
- Wrist tracking만 enable, hand retargeting은 disable
- Galaxy XR로 팔만 움직여서 UR10e 모사 확인
- 관절 속도 제한 검증 (과속 방지)
- 30분 이상 연속 운용해도 drift 없는지 확인

**Day 3: DG-5F 조종 테스트 (팔은 고정)**
- UR10e를 특정 자세로 고정
- DG-5F만 Galaxy XR 손 움직임으로 조종
- 기본 동작 5가지 검증: open, close, pinch, point, thumb up
- 손가락 간 충돌 방지 확인

**Day 4: 통합 teleop (저속)**
- 속도 scale 30%로 상향
- 팔 + 손 동시 조종
- 태스크 1: 빈 공간 이동 (물체 접촉 없음)
- 태스크 2: 간단한 pick 시도 (가벼운 물체)
- 각 태스크 3회 이상 반복 성공 확인

**Day 5: 속도 점진적 상향 및 안정화**
- 속도 scale 50%, 70%, 100% 순차 확대
- 각 단계에서 안전 테스트 재수행
- Drift, 지연, jitter 정량 기록

**Deliverables**:
- 실로봇 teleop 영상 (3종 태스크)
- 안전 테스트 결과
- 안정 동작 가능한 최대 속도 scale

---

### Week 9: 멀티 카메라 스트리밍 통합 (teleimager)

**목표**: 3대 D405(egocentric + 양손목) 스트림을 Galaxy XR에 실시간 표시

**Day 1: D405 하드웨어 세팅**
- Egocentric 카메라 마운트 고정 (로봇 전방 관찰 위치)
- 양 손목 카메라 UR10e 손목 장착 (기존 기구 활용)
- Jetson AGX Orin 또는 조종PC에 USB 3.0 hub 경유 연결
- 각 D405의 serial number 확인 및 launch config 등록

**Day 2: teleimager 설정 수정**
- Egocentric: RGB stereo(SBS) 1280×480 @ 30fps
- Wrist L/R: Mono RGB 640×480 @ 30fps (대역폭 절감)
- 인코딩: H.264 + NVENC 가속
- WebRTC 세션 설정

**Day 3: Galaxy XR 측 영상 수신 및 렌더링**
- televuer 내 video display plane 설정
- Egocentric: 양 눈 각각에 스테레오 렌더링 (depth perception)
- Wrist: 상단 좌/우 picture-in-picture
- 레이아웃 조정 (사용자 시야 방해 최소화)

**Day 4: 대역폭 및 지연 최적화**
- WiFi 대역폭 측정 (3대 동시 송신 시)
- Wrist 카메라 해상도/fps 하향 조정 여지 확인
- Glass-to-glass latency 측정 (카메라 → 디스플레이)
- 목표: <200ms

**Day 5: 통합 End-to-End 테스트**
- Teleop + 멀티 카메라 동시 운용
- 1시간 연속 운영 안정성 체크
- 사용자 피로도/멀미 주관 평가

**Deliverables**:
- teleimager 설정 파일
- 3대 스트리밍 영상 캡처
- Latency/대역폭 벤치마크
- **Gate 5**: 실로봇 + 멀티카메라 통합 안정 동작

---

## Phase 4: 성능 평가 및 개선점 분석 (Week 10-12)

### Week 10: Manus+Vive 기존 시스템과 정량 비교

**목표**: Galaxy XR 시스템의 성능을 기존 시스템과 객관적으로 비교

**Day 1: 평가 프로토콜 설계**
- 평가 태스크 3종 선정 (기존 시스템에서도 수행 가능한 것)
  - 태스크 A: Pick and place (쉬움)
  - 태스크 B: 정렬된 물체 순서대로 이동 (중간)
  - 태스크 C: Key insertion 또는 유사한 precision 작업 (어려움)
- 측정 metric 정의
  - 완료 시간
  - 성공률 (10회 중 성공 횟수)
  - Tracking error (desired vs actual TCP)
  - 관절 속도 profile (smoothness)
  - 사용자 NASA-TLX (주관 부하)

**Day 2-3: 기존 Manus+Vive 시스템 데이터 수집**
- 태스크 A, B, C 각 10회 반복
- 사용자 2명 이상 (가능하면 연구실 동료 참여)
- 전 세션 녹화 + 로봇 로그 기록

**Day 4: Galaxy XR 시스템 데이터 수집**
- 동일 프로토콜로 수행
- 동일 사용자(학습 편향 고려 순서 balanced)
- 모든 세션 녹화

**Day 5: 통계 분석**
- Paired t-test 또는 Wilcoxon
- 유의미한 차이 있는 metric 식별
- Visualization (boxplot, trajectory overlay 등)

**Deliverables**:
- 평가 프로토콜 문서
- 원시 데이터 (HDF5/CSV)
- 비교 보고서 초안

---

### Week 11: 병목 분석 및 개선점 도출

**목표**: 성능이 부족한 원인을 식별하고 개선 방안을 제시

**Day 1: Latency 분해 분석**
- 전체 파이프라인을 단계별로 분해
  - Galaxy XR 센싱 → Chrome 처리 → WebSocket 전송 → televuer 수신 → tv_wrapper → retargeting/IK → ZMQ 전송 → ur_rtde → 로봇 반응
- 각 단계별 시간 소요 측정 (타임스탬프 기반)
- Critical path 식별

**Day 2: Tracking precision 분석**
- Galaxy XR hand tracking 노이즈 정량화
- Jitter 주파수 스펙트럼 분석
- 필터 파라미터 재튜닝 여지 탐색
- 1cm 수준 정확도의 한계가 어떤 태스크에 영향 주는지 매핑

**Day 3: 사용자 인터뷰 및 피드백 수집**
- 주관 경험 정리 (어느 동작이 어려웠는지)
- 멀미, 피로도, 손 피로 등 physical issue
- 비주얼 피드백 부족 여부 (F/T 시각화 없는 영향)
- UI/UX 개선 제안

**Day 4: 개선 항목 우선순위화**
- Impact(효과) × Effort(구현비용) 매트릭스
- Quick win 항목 식별 (Week 12에서 적용)
- 중장기 과제 별도 분류 (Phase 5 이상)

**Day 5: 개선안 문서화**
- 각 개선 항목별:
  - 문제 기술
  - 원인 분석
  - 해결 방안
  - 예상 효과
  - 구현 공수

**Deliverables**:
- Latency 분해 리포트
- 사용자 피드백 정리
- 개선 항목 우선순위 매트릭스

---

### Week 12: Quick Win 적용 및 최종 보고

**목표**: 빠르게 적용 가능한 개선사항을 반영하고 전체 프로젝트 wrap-up

**Day 1-2: Quick Win 개선 적용**
- Week 11에서 도출된 high-impact / low-effort 항목 2-3개 구현
- 예상 가능한 항목들:
  - Pose 필터 재튜닝 (moving average window 조정)
  - 데드존 도입 (미세 떨림 차단)
  - Hybrid 입력 모드 (precision task 시 컨트롤러 자동 전환)
  - 속도 scaling (작업 영역 진입 시 자동 감속)

**Day 3: 개선 후 재평가**
- Week 10과 동일 프로토콜로 재측정
- Before/After 정량 비교
- 의미있는 개선 확인

**Day 4: 최종 프로젝트 보고서 작성**
- Executive summary
- 전체 개발 과정
- 성능 평가 결과
- 발견된 한계
- 후속 개발 로드맵 제안
  - Phase 5 후보: F/T 시각화 (AR overlay)
  - Phase 6 후보: GazeSAM + cuMotion 통합
  - Phase 7 후보: Shared Autonomy (Residual Copilot) 통합

**Day 5: 코드 정리 및 문서화**
- 코드 리팩토링, 주석 보완
- README 작성 (재현 가능하도록)
- 설치 가이드, 사용법 문서
- Git 태그 v1.0 릴리스

**Deliverables**:
- 개선 적용된 최종 시스템
- Before/After 비교 데이터
- 최종 프로젝트 보고서
- v1.0 릴리스 코드 + 문서

---

## 주요 Gate 조건 요약

| Gate | 시점 | 조건 | 실패 시 |
|---|---|---|---|
| Gate 1 | Week 1 말 | Galaxy XR Chrome에서 WebXR hand tracking 동작 | XRoboToolkit Unity APK 방식으로 Plan B 전환 |
| Gate 2 | Week 2 말 | televuer로 pose 데이터 30Hz 이상 안정 수신 | 네트워크/인증서 디버깅, 필요시 ngrok 터널 |
| Gate 3 | Week 3 말 | IsaacSim에서 G1 원본 teleop 동작 | unitree_sim_isaaclab 설치/설정 재확인 |
| Gate 4 | Week 6 말 | IsaacSim에서 UR10e+DG-5F 안정 teleop | 원인에 따라 해당 주차 연장 |
| Gate 5 | Week 9 말 | 실로봇+멀티카메라 통합 안정 동작 | 하드웨어/대역폭 재검토 |

---

## 리소스 요구사항

### 하드웨어
- Galaxy XR 1대 (+ 컨트롤러 권장)
- 조종PC: Ubuntu 22.04, RTX 4090/5090, WiFi 6E AP
- 로봇PC: 기존 환경 유지
- UR10e + DG-5F: 기존 보유
- RealSense D405 × 3대
- USB 3.0 hub (고품질, 자체 전원 공급)

### 소프트웨어 라이센스
- Unity 6 LTS (Plan B 시): 개인 사용 무료
- NVIDIA Isaac Sim: 무료 (학술용)
- 나머지 오픈소스: MIT/BSD/Apache2

### 인력
- 주 개발: 기봉님
- 보조: Emergency stop 담당 1명 (Week 8 실로봇 테스트 시)
- 평가 피험자: 2명 이상 (Week 10)

---

## 주요 리스크 요약

| 리스크 | 발생 확률 | 영향 | 대응 |
|---|---|---|---|
| Galaxy XR WebXR 호환성 문제 | 중 | 상 | Gate 1에서 조기 검출, Plan B 준비 |
| Vuer 브라우저 업데이트로 깨짐 | 중 | 중 | Vuer 버전 고정 (0.0.60), 대체 브라우저 확보 |
| DG-5F retargeting 자연스러움 부족 | 중 | 중 | Week 5에서 반복 튜닝, AnyTeleop 참고 |
| IsaacSim USD 변환 어려움 | 중 | 중 | NVIDIA 공식 변환기 + 커뮤니티 도움 활용 |
| 실로봇 충돌/손상 | 낮 | 상 | 저속 진행, Emergency stop, 관찰자 상주 |
| Latency 부족 (>300ms) | 중 | 상 | 유선 네트워크, 인코딩 최적화, 해상도 조정 |
| Hand tracking 정밀도 부족 | 상 | 중 | Hybrid 입력 모드, 향후 Residual Copilot 의존 |

---

## 향후 확장 로드맵 (Phase 5 이상)

- **Phase 5**: F/T 센서 시각화 AR overlay (Impedance Control 가시화)
- **Phase 6**: Eye-tracking + SAM3 + cuMotion gaze-guided manipulation
- **Phase 7**: Shared Autonomy (Residual Copilot) 통합
- **Phase 8**: VLA 자율화 연동 및 imitation learning 데이터 수집 운영

---

*끝.*
