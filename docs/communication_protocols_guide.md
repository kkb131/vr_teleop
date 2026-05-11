# 원격조종 통신 프로토콜 입문 가이드

> **대상**: xr_teleop + unitree_sim_isaaclab을 처음 접하는 사람
> **목적**: DDS / WebRTC / Vuer / ZMQ 가 각각 무엇이고, 전체 파이프라인에서 어떻게 맞물려 돌아가는지 직관적으로 이해하기

---

## 1. 한 장으로 보는 전체 그림

원격조종은 결국 **두 종류의 데이터**가 양방향으로 흐르는 시스템이다.

```
 ┌──────────────┐                                           ┌────────────────────────┐
 │              │  ① 손/머리 자세 (Pose)                    │                        │
 │  VR 헤드셋    │ ──────────────────────────────────────→  │  로봇 (실물 또는       │
 │ (Galaxy XR / │                                           │  Isaac Sim)            │
 │  Quest 3)    │  ② 카메라 영상 (Video)                    │                        │
 │              │ ←──────────────────────────────────────   │                        │
 └──────────────┘                                           └────────────────────────┘
```

이 두 흐름을 가장 적합한 통신 프로토콜로 나눠 처리하는 게 핵심이다.

| 데이터 종류            | 특징                       | 적합한 프로토콜    |
|------------------------|----------------------------|--------------------|
| 손/머리 자세           | 작은 메시지, 30Hz, 양방향  | WebSocket (Vuer)   |
| 카메라 영상            | 큰 메시지, 30Hz, 단방향    | WebRTC 또는 ZMQ    |
| 로봇 모터 명령/상태    | 실시간성 중요, 250~500Hz   | DDS                |
| 사용자 명령(시작/정지) | 가벼운 이벤트              | ZMQ (IPC)          |

이게 바로 "왜 한 가지 프로토콜만 쓰지 않는가?"에 대한 답이다. 데이터 특성마다 잘하는 도구가 다르기 때문에 **4가지를 조합**한다.

---

## 2. 각 프로토콜은 무엇인가? (5분 요약)

### 2.1 Vuer — "VR 헤드셋과 통신하는 웹서버 프레임워크"

- **한 줄 정의**: VR 헤드셋의 브라우저(WebXR)와 PC를 잇는 Python 기반 웹 프레임워크
- **무슨 역할?**
  - PC에서 HTTPS 웹서버를 띄운다 (보통 `https://조종PC_IP:8012`).
  - VR 헤드셋이 그 주소를 브라우저로 열면, **헬멧이 추적한 손/머리 자세**를 실시간 WebSocket으로 PC에 보내준다.
  - 동시에 PC가 **로봇 카메라 영상**을 다시 헬멧 화면에 띄울 수 있다.
- **왜 필요한가?**: VR SDK를 직접 다루지 않고 "그냥 브라우저 열기"만으로 어떤 헤드셋이든 연결 가능. (OpenTeleVision 프로젝트에서 시작)
- **위치**: [teleop/televuer/](../xr_teleoperate/teleop/televuer/)

### 2.2 WebRTC — "브라우저용 실시간 영상 통화 기술"

- **한 줄 정의**: 화상회의(Zoom, Discord)에서 쓰는 그 기술. 매우 낮은 지연(50~100ms)으로 영상을 보낸다.
- **무슨 역할?**: 로봇에 달린 카메라 3대(머리 + 양 손목)를 VR 헤드셋의 브라우저로 직접 스트리밍.
- **왜 필요한가?**:
  - 카메라 영상은 데이터가 크다(JPEG도 한 프레임에 수백 KB).
  - 단순 TCP는 한 프레임이 늦으면 뒤따르는 모든 프레임이 밀린다 → 멀미 유발.
  - WebRTC는 UDP 기반이라 일부 프레임이 늦으면 **버리고 최신 것**을 보여준다 → 멀미 방지.
- **단점**: 신호 교환(signaling) 서버가 따로 필요하고, HTTPS가 강제됨. 설정이 복잡.

### 2.3 ZMQ (ZeroMQ) — "소켓 통신을 쉽게 해주는 라이브러리"

- **한 줄 정의**: TCP 소켓을 PUB/SUB·REQ/REP 같은 패턴으로 감싸 사용하기 편하게 만든 메시지 큐 라이브러리.
- **무슨 역할 2가지?**
  1. **카메라 영상의 백업 채널**: WebRTC가 안 되는 환경에서 ZMQ PUB/SUB로 영상을 보낸다.
  2. **프로세스 간 명령 전달(IPC)**: "녹화 시작/정지" 같은 가벼운 명령을 다른 터미널에서 보낼 때 사용.
- **왜 필요한가?**: 설정이 거의 없다. `socket.bind("tcp://*:55555")` 한 줄로 서버 시작. 같은 PC 안에서 빠르고 안정적.
- **WebRTC와 비교**:
  | 구분         | WebRTC                 | ZMQ                  |
  |--------------|------------------------|----------------------|
  | 지연         | 매우 낮음 (50ms)       | 낮음 (100~200ms)     |
  | 설정 난이도  | 어려움 (HTTPS, STUN)   | 매우 쉬움            |
  | 브라우저 호환| 네이티브 지원          | 별도 렌더링 필요     |
  | 사용처       | VR 헤드셋 직접 표시    | PC 간 영상 전송      |

### 2.4 DDS (Data Distribution Service) — "로봇 산업용 실시간 미들웨어"

- **한 줄 정의**: ROS2의 기본 통신 계층이기도 한, 산업용 실시간 발행-구독(pub/sub) 표준.
- **무슨 역할?**: 로봇과 PC 사이에서 **모터 명령**(보내기)과 **모터 상태**(받기)를 250~500Hz로 주고받음.
- **왜 필요한가?**:
  - 로봇 제어는 "1ms도 늦으면 안 된다"는 결정적(deterministic) 통신이 필요.
  - DDS는 멀티캐스트 자동 검색(discovery)으로 같은 네트워크의 로봇/시뮬을 자동으로 찾아준다.
  - 메시지 스키마가 IDL로 정의돼 있어 타입 안전.
- **Unitree 환경의 핵심**:
  - Unitree 로봇은 자체 SDK(`unitree_sdk2py`)로 DDS 위에서 토픽을 노출한다.
  - **실물 로봇** = DDS Domain ID `0`
  - **Isaac Sim 시뮬레이션** = DDS Domain ID `1`
  - Domain ID만 다르면 같은 PC에서 둘 다 동시에 띄워도 충돌 안 남.

### 2.5 (보너스) IPC vs RPC

- **IPC (Inter-Process Communication)**: 같은 PC 내부의 다른 프로세스에 메시지 보내기. 본 코드에선 ZMQ로 구현.
- 사용 예: `teleop_hand_and_arm.py`가 메인 루프를 돌고, 별도 터미널에서 `python -c "send_cmd('CMD_START')"` 같은 식으로 시작 신호를 보낸다.

---

## 3. 전체 파이프라인 — 데이터가 흘러가는 길

### 3.1 손 자세가 로봇 팔이 되기까지 (제어 흐름, 30Hz)

```
[VR 헤드셋]
  손가락 25개 관절 추적 (WebXR Hand API)
       │
       │  WebSocket (HTTPS)            ← Vuer 가 담당
       ▼
[조종 PC: televuer 웹서버]
  손/머리 자세를 공유 메모리에 저장
       │
       │  파이썬 함수 호출 (같은 프로세스)
       ▼
[TeleVuerWrapper]
  좌표계 변환 (OpenXR → 로봇 좌표계)
       │
       ▼
[teleop_hand_and_arm.py 메인 루프]
  ① 손목 위치(4×4 행렬)를 얻음
  ② 현재 로봇 관절 상태를 DDS에서 읽음 ← rt/lowstate
  ③ 역기구학(IK)으로 목표 관절 각도 계산 (Pinocchio + CasADi)
  ④ 손가락 25관절 → 그리퍼 모터 각도로 리타게팅
       │
       │  DDS Publish                   ← 결정적 실시간 통신
       ▼
[로봇 또는 Isaac Sim]
  rt/lowcmd 토픽 수신 → PD 제어 → 실제 모터 회전
  rt/lowstate 토픽 게시 → 다시 메인 루프로 (피드백)
```

핵심 토픽 (DDS):
- `rt/lowcmd` : PC → 로봇 (모터 목표값)
- `rt/lowstate` : 로봇 → PC (현재 모터값)
- `rt/dex3/left/cmd`, `rt/dex3/right/cmd` : 손 모터 명령
- `rt/reset_pose/cmd` : 시뮬레이션 환경 리셋 (Isaac Sim 전용)

### 3.2 로봇 카메라 영상이 VR 화면에 뜨기까지 (영상 흐름, 30Hz)

```
[로봇 PC에 연결된 카메라 3대]
  머리(480×1280, 양안), 좌 손목(480×640), 우 손목(480×640)
       │
       │  ┌─────────────────────────────────┐
       │  │ 옵션 A : WebRTC                 │
       │  │   포트 60001/60002/60003        │
       │  │   브라우저로 직접 스트리밍      │
       │  │                                  │
       │  │ 옵션 B : ZMQ PUB                │
       │  │   포트 55555/55556/55557        │
       │  │   PC 클라이언트가 받아서        │
       │  │   Vuer 화면에 그려줌            │
       │  └─────────────────────────────────┘
       │
       ▼
[VR 헤드셋 화면]
  display_mode 에 따라:
   - immersive   : 전체 화면이 카메라 영상
   - ego         : 가운데 작은 창에 영상, 주변은 헤드셋 패스스루
   - pass-through: 영상 표시 없음 (헤드셋 자체 카메라 사용)
```

설정 파일 [cam_config_server.yaml](../xr_teleoperate/teleop/teleimager/cam_config_server.yaml)에서 카메라마다 `enable_zmq` / `enable_webrtc`를 true/false로 켜고 끌 수 있다.

### 3.3 사용자 명령 흐름 (이벤트, 부정기적)

```
[다른 터미널 또는 키보드]
  'r' → 시작, 's' → 녹화 토글, 'q' → 종료
       │
       │  ZMQ REQ/REP (IPC 소켓)
       │  또는 sshkeyboard 직접 입력
       ▼
[teleop_hand_and_arm.py]
  상태머신 전이 (READY → RECORD_RUNNING 등)
```

`--ipc` 플래그로 시작하면 ZMQ IPC 모드, 없이 시작하면 sshkeyboard 모드.

---

## 4. "왜 4가지를 다 쓰는가?" — 한 번 더 정리

| 묶음                     | 사용 프로토콜 | 이유                                                          |
|--------------------------|---------------|---------------------------------------------------------------|
| VR 헤드셋과의 통신       | Vuer/WebSocket | 브라우저 표준이라 어떤 헤드셋이든 연결 가능                  |
| 카메라 → VR 직결          | WebRTC        | UDP 기반 저지연, 멀미 방지                                    |
| 카메라 → PC 중계         | ZMQ           | WebRTC 셋업 없이 간단히 영상 받기                              |
| 로봇 모터 제어           | DDS           | 산업 표준, 250Hz+ 결정적 통신, Unitree SDK 표준               |
| 메인 프로세스 ↔ 보조 프로세스 | ZMQ (IPC) | 같은 PC 안 가벼운 명령 전달용                                 |

각 프로토콜은 **자기가 잘하는 데이터**만 처리한다. 한 가지로 통합하려고 하면 어딘가에서는 반드시 손해를 본다.

---

## 5. Isaac Sim 통합 (unitree_sim_isaaclab) 의 핵심 트릭

이 시스템의 가장 영리한 설계 결정 하나:

> **xr_teleoperate 코드는 자기가 실물 로봇을 제어하는지, 시뮬레이션을 제어하는지 모른다.**

왜냐하면 두 경우 모두 **똑같은 DDS 토픽**(`rt/lowcmd`, `rt/lowstate` 등)을 쓰기 때문이다.

```
실물 로봇 모드:
  teleop_hand_and_arm.py --domain 0
       ↓ DDS (Domain 0)
  실제 Unitree 로봇 (SDK가 동일 토픽 발행/구독)

시뮬레이션 모드:
  teleop_hand_and_arm.py --sim    ← ChannelFactoryInitialize(1) 호출
       ↓ DDS (Domain 1)
  unitree_sim_isaaclab (Isaac Sim 안에서 동일 토픽 발행/구독)
```

Domain ID만 갈아끼우면 동일한 코드가 양쪽에서 그대로 동작한다. 이는 다음을 가능하게 한다:
- 실물 로봇 없이 노트북에서 IK/리타게팅/녹화 파이프라인 전체 디버깅
- 모방학습 데이터 수집을 시뮬에서 먼저, 그다음 실물에서
- CI/CD에서 시뮬로 자동 회귀테스트

자세한 빌드/실행은 [SIM_UR10E_DG5F_BUILD_GUIDE.md](SIM_UR10E_DG5F_BUILD_GUIDE.md) 참고.

---

## 6. 핵심 파일 빠른 참조

| 파일                                                                                  | 한 줄 설명                                       |
|---------------------------------------------------------------------------------------|--------------------------------------------------|
| [teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py)             | 메인 진입점. 30Hz 제어 루프 전체 오케스트레이션 |
| [televuer/tv_wrapper.py](../xr_teleoperate/teleop/televuer/src/televuer/tv_wrapper.py)| Vuer 데이터를 받아 좌표계 변환                   |
| [televuer/televuer.py](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py)    | Vuer 웹서버 본체. WebSocket 핸들러               |
| [teleimager/image_client.py](../xr_teleoperate/teleop/teleimager/src/teleimager/image_client.py) | ZMQ로 카메라 프레임 수신                |
| [teleimager/cam_config_server.yaml](../xr_teleoperate/teleop/teleimager/cam_config_server.yaml)  | 카메라별 ZMQ/WebRTC 포트 설정          |
| [robot_control/robot_arm.py](../xr_teleoperate/teleop/robot_control/robot_arm.py)     | DDS로 로봇 팔 모터 명령/상태 처리                |
| [robot_control/robot_hand_unitree.py](../xr_teleoperate/teleop/robot_control/robot_hand_unitree.py) | DDS로 Unitree Dex3 손 제어             |
| [utils/ipc.py](../xr_teleoperate/teleop/utils/ipc.py)                                 | ZMQ 기반 프로세스 간 명령/하트비트                |

---

## 7. 디버깅 시 자주 막히는 곳 체크리스트

- **VR 헤드셋이 손 자세를 안 보낸다** → Vuer 웹서버 HTTPS 인증서 문제. 헤드셋 브라우저에서 직접 접속해보고 인증서 경고 우회.
- **로봇이 안 움직인다 (실물)** → DDS 네트워크 인터페이스 확인. `--network-interface eth0` 명시 필요할 수 있음.
- **시뮬과 실물이 동시에 동작한다** → Domain ID가 같음. 시뮬은 반드시 `--sim` (Domain 1).
- **카메라가 검은 화면** → cam_config_server.yaml 의 `enable_zmq`/`enable_webrtc` 둘 다 false인지, 또는 image_server가 안 떠있는지 확인.
- **녹화 명령이 안 먹힌다** → `--ipc`로 시작했는지, 아니면 sshkeyboard 모드인지 확인.

---

## 8. 한 발 더 — 추천 학습 순서

1. 이 문서로 큰 그림 파악
2. [run_teleop_internals.md](run_teleop_internals.md) — 메인 루프 한 줄씩 읽기
3. [xr_teleoperate_tech_analysis.md](xr_teleoperate_tech_analysis.md) — 기술적 깊이
4. 실제로 시뮬 모드로 띄워보고 `tcpdump` / `wireshark` / `ros2 topic echo`로 토픽 흐름 관찰
5. DDS 토픽 직접 발행해보기 (`python -c "from unitree_sdk2py... ChannelPublisher(...)"`)

각 프로토콜은 별도로 공부할 가치가 있는 큰 주제지만, **이 시스템 안에서의 역할만 알면 코드를 읽고 수정할 수 있다**는 점이 출발점이다.
