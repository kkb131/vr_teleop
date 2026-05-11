# Galaxy XR ws bridge → xr_teleoperate 통합 설계

**작성일**: 2026-05-11
**대상**: Week 4 진입 시점, G1+Dex3 환경 기준 (Week 4-6 UR10e+DG-5F 교체 후에도 동일 패턴 적용)
**목적**: 검증된 Galaxy XR ws bridge(`setup/test_pose_only_ws.py` + `setup/webxr_to_pose.html`)를 [teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py)와 통합하기 위한 옵션 분석 + 권장 우선순위
**가장 큰 검토 포인트**: 카메라 영상(teleimager) 통합 시 unitree 측(`xr_teleoperate` / `teleimager` / `televuer`) 코드 변경 최소화

---

## 0. 컨텍스트

### 0.1 왜 이 통합이 필요한가

Galaxy XR Chrome에서 vuer 0.0.60 client React가 **immersive XR session 진입 후 hand/cam event publish freeze**되는 문제가 확정되었다([xr_teleoperate_setup_issues.md §1.x](xr_teleoperate_setup_issues.md)에 §1.12로 정리 예정).

진단 결과 요약:
- **vuer client publish 가드는 정상** — `D && (!g || o && l || S(...))`에서 D=mode/g=stream/o,l=disableLeft,Right 모두 정상값 (source map 복원으로 확정)
- **`document.hidden` / `xrSession.visibilityState`는 visible 유지** — visibility 가설 기각
- **setInterval은 정상 30Hz fire** — JS timer throttle 가설 기각
- **`useFrame`이 R3F의 frame loop에 의존** — Galaxy XR Chrome immersive 진입 시 일반 RAF가 멈추는데(XR-RAF로 전환됨) vuer 0.0.60의 R3F Canvas가 XR-RAF로 제대로 전환 안 되거나 stale 상태로 남아 `useFrame` 안에서 G 채우기/store 추적이 멈추고, 결과적으로 publish callback 안 들어옴 — 가장 유력한 가설(완전 입증은 minified bundle inspect 필요)
- 이 freeze는 **pose뿐 아니라 vuer scene 안 `WebRTCVideoPlane` 렌더링도 동시에 영향** — 즉 영상 streaming도 같은 경로 의존

검증된 우회: [setup/webxr_to_pose.html](../setup/webxr_to_pose.html)이 `xrSession.requestAnimationFrame`(XR-RAF) 기반 onFrame loop에서 매 프레임 head/hand pose를 추출해 [setup/test_pose_only_ws.py](../setup/test_pose_only_ws.py)의 ws server로 JSON 송신. 사용자 실측 결과 head/LW/RW/LH/RH 모두 OK, hand_pos가 손 움직임 따라 변동(`[-0.03, +0.08, -0.31]` 같은 HMD 상대좌표).

### 0.2 다음 단계의 목표

검증된 ws bridge를 [teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py)에 적용해 **실제 G1+Dex3 sim teleop이 Galaxy XR에서도 Quest 3와 동등 수준으로 동작**하도록 만든다. unitree 측 코드(`xr_teleoperate` / `teleimager` / `televuer`)는 fork/patch보다 wrapper + monkey-patch로 우회를 유지하되, 만약 명백한 개선 방향이면 작은 변경은 허용.

---

## 1. 현재 시스템 구조 (분석 결과)

### 1.1 pose 채널 — TeleVuer / TeleVuerWrapper 인터페이스

[teleop_hand_and_arm.py:125-135](../xr_teleoperate/teleop/teleop_hand_and_arm.py#L125-L135)에서 `TeleVuerWrapper`가 생성되고, 메인 루프는 이걸 통해 pose를 얻는다.

```python
tv_wrapper = TeleVuerWrapper(
    use_hand_tracking=args.input_mode == "hand",
    binocular=...,
    img_shape=...,
    display_fps=...,
    display_mode=args.display_mode,       # immersive / pass-through / ego
    zmq=...,
    webrtc=...,
    webrtc_url=f"https://{args.img_server_ip}:{cam_cfg['head_camera']['webrtc_port']}/offer",
)
```

[tv_wrapper.py:195](../xr_teleoperate/teleop/televuer/src/televuer/tv_wrapper.py#L195)의 `TeleVuerWrapper`는 내부에서 `self.tvuer = TeleVuer(...)`를 생성하고, `tvuer.head_pose / left_arm_pose / left_hand_positions / left_hand_pinch` 등 property를 읽어 OpenXR→Robot 좌표 변환 + valid 체크 + offset/smoothing 적용 후 [TeleData](../xr_teleoperate/teleop/televuer/src/televuer/tv_wrapper.py#L142) dataclass로 반환(`get_motion_state_data()` 등).

핵심: **`TeleVuerWrapper`는 `TeleVuer` 인스턴스의 property를 read하는 thin layer**. 즉 `TeleVuer` 호환 객체를 만들면 `TeleVuerWrapper`는 그대로 사용 가능.

`TeleVuer`가 노출하는 핵심 property (모두 `multiprocessing.Array` 기반 shared memory):
- `head_pose_shared` (16 float, 4x4 SE(3) column-major)
- `left_arm_pose_shared` / `right_arm_pose_shared` (16 float each)
- `left_hand_position_shared` / `right_hand_position_shared` (25*3 float each)
- `left_hand_orientation_shared` / `right_hand_orientation_shared` (25*9 float each)
- `left_hand_pinch_shared` / `*_pinchValue_shared` / `*_squeeze_shared` / `*_squeezeValue_shared` (controller/hand state)
- property getter: `head_pose`, `left_arm_pose`, `left_hand_positions`, `left_hand_pinch`, ... (numpy ndarray 반환)
- method: `render_to_xr(frame)` (ZMQ 모드일 때 shared memory 업데이트)

### 1.2 영상 채널 — ZMQ vs WebRTC

teleimager는 sim host(별도 docker)의 `image_server.py`에서 카메라 frame을 두 가지 방식으로 publish:

**ZMQ 경로**:
- sim host: `image_server.py` → ZMQ PUB (head=55555, left_wrist=55556, right_wrist=55557)
- PC 측: [image_client.py:715-719](../xr_teleoperate/teleop/teleimager/src/teleimager/image_client.py#L715-L719)의 `ImageClient.get_head_frame()`이 ZMQ subscribe로 frame 받음 → bgr numpy
- 그 다음 [teleop_hand_and_arm.py:255](../xr_teleoperate/teleop/teleop_hand_and_arm.py#L255)에서 `tv_wrapper.render_to_xr(head_img)` 호출 → [televuer.py:201-206](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py#L201-L206)의 `render_to_xr` → shared memory `img2display`에 BGR→RGB → vuer page의 `ImageBackground(self.img2display, ...)`가 헤드셋 안 plane에 그림

**WebRTC 경로** (Week 3 v6 fix 이후 default):
- sim host: [image_server.py:35-38](../xr_teleoperate/teleop/teleimager/src/teleimager/image_server.py#L35-L38)에서 `aiortc.RTCPeerConnection` 사용, [`/offer` HTTP POST endpoint](../xr_teleoperate/teleop/teleimager/src/teleimager/image_server.py#L353) (port 60001/60002/60003)
- PC는 안 거치고 **vuer client React가 직접** `WebRTCVideoPlane(src=webrtc_url)`에서 fetch+RTCPeerConnection으로 sim host에 negotiate → 헤드셋 안에서 video track 직접 render

[run_teleop.py:59-74](../setup/run_teleop.py#L59-L74)가 `--img-server-ip localhost` default로 cert 신뢰 host 일치시킴.

### 1.3 Galaxy XR Chrome에서 두 경로 모두 막힘

- ZMQ 경로: PC에서 `render_to_xr`로 shared memory 업데이트는 정상이지만, **vuer page의 `ImageBackground`도 R3F frame loop 의존 → publish freeze와 같은 메커니즘으로 plane 업데이트 멈춤**
- WebRTC 경로: **vuer client React가 `RTCPeerConnection`을 만드는 useEffect도 R3F XR session lifecycle에 묶여 있어 mount/setup이 늦거나 stale**

즉 **pose뿐 아니라 영상 plane 렌더링도 vuer client React에 의존 → 둘 다 우회가 필요**.

### 1.4 검증된 ws bridge (현재 상태)

| 파일 | 역할 |
|---|---|
| [setup/test_pose_only_ws.py](../setup/test_pose_only_ws.py) | aiohttp ws server (port 8013) — `/`에서 HTML 정적 서빙, `/pose`에서 ws receive. `PoseStore`에 head/hand pose 채움. smoke/measure 모드 |
| [setup/webxr_to_pose.html](../setup/webxr_to_pose.html) | XR-RAF onFrame loop에서 매 프레임 head + 양손 25-joint를 JSON 송신. 자동 reconnect |
| [setup/webxr_check.html](../setup/webxr_check.html) | 진단용 (vuer 무관 WebXR API 동작 검증). visibility / setInterval throttle 카운터 포함 |

`PoseStore`는 현재 thread-safe `np.ndarray` (multiprocessing은 아님). teleop_hand_and_arm.py 통합 시 multiprocessing.Array로 발전시켜야 한다.

---

## 2. 통합 옵션 분석 (4가지 + 임시 1)

각 옵션은 다음 측면에서 평가:
- **변경 위치/양**: 어디를 얼마나 수정
- **unitree 측 코드 변경**: xr_teleoperate / teleimager / televuer 각각
- **장점 / 단점**
- **작업량 추정** (man-day)
- **적합 phase**

---

### 옵션 A — PoseStore를 TeleVuer-compatible shared memory로 (영상 미통합)

**아키텍처**:

```
Galaxy XR Chrome (Galaxy XR HMD)
  └─ webxr_to_pose.html  ─── ws JSON pose ───┐
                                              │
PC docker                                     ▼
  └─ test_pose_only_ws.py (확장)
      └─ BridgePoseStore (multiprocessing.Array, TeleVuer 인터페이스 mimick)
              │   .head_pose_shared, .left_arm_pose_shared, ...
              │   .head_pose (property), .left_arm_pose, ...
              │   .render_to_xr(frame)  # noop or shared-mem write
              ▼
      └─ teleop_hand_and_arm.py (런처 wrapper로 launch)
          └─ TeleVuerWrapper(tvuer=BridgePoseStore)  ← inject
              ↓
          IK / DDS pub  →  IsaacSim G1+Dex3

Sim host docker (변경 없음)
  └─ image_server.py (WebRTC + ZMQ 모두 살아있음)

영상: operator는 desktop chrome 별도 탭에서 https://localhost:60001 보거나 헤드셋 안 영상 포기
```

**변경 위치 / 양**:
- [setup/test_pose_only_ws.py](../setup/test_pose_only_ws.py) — `PoseStore` → `BridgePoseStore` 발전. multiprocessing.Array 변수명을 [televuer.py:138-173](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py#L138-L173)과 100% 일치시킴. TeleVuer가 노출하는 모든 property (`head_pose`, `left_arm_pose`, `left_hand_positions`, `left_hand_orientations`, `left_hand_pinch`, `*_pinchValue`, ...)를 동일 시그니처로 구현. `render_to_xr(frame)`은 noop(또는 향후 옵션 B2로 발전 시 ws binary 송신 진입점). 100-200줄 추가
- 새 파일: `setup/run_teleop_ws.py` — [run_teleop.py](../setup/run_teleop.py)와 같은 wrapper 패턴. 차이는 `_apply_http_monkey_patch` 대신 **`_inject_bridge_pose_provider`**: TeleVuerWrapper 생성 시 `tvuer` 키워드를 우리 BridgePoseStore로 monkey-patch. cwd 변경 + sanity check 동일
- [webxr_to_pose.html](../setup/webxr_to_pose.html) — orientation 송신 추가(현재 position만 보내고 있음. teleop 시 손 회전 정보가 retargeting 필수)

**unitree 측 코드 변경**:
- `xr_teleoperate` (`teleop_hand_and_arm.py` 포함): **0줄 직접 수정**. wrapper의 monkey-patch로 진입 (run_teleop.py의 `_apply_http_monkey_patch` 패턴과 동일)
- `televuer`: **0줄**. BridgePoseStore가 TeleVuer 인터페이스 mimick
- `teleimager`: **0줄** (영상 미통합)

**장점**:
- unitree 측 코드 변경 zero. 매우 깨끗한 통합
- 1-2일 안에 G1 팔 동작 sanity 가능 (Week 4 gate 직전 검증)
- 영상 부분이 없어 작업량/위험 작음

**단점**:
- **operator가 헤드셋 안에서 카메라 영상 못 봄** — 실제 운영 부적합. Quest 3는 immersive 안 영상 + hand sync로 동작하는데 Galaxy XR은 pass-through(실세계)에 손 visualization만. teleop 안전성/직관성 크게 떨어짐
- 영상 별도 모니터링은 사용자 편의성 매우 낮음 (헤드셋 벗고 monitor 봐야 함)

**작업량**: ~1.5 man-day

**적합 phase**: Week 4 sanity check (G1+Dex3가 우리 Galaxy XR으로도 동작은 하는지 정량 확인). **운영 진입 전 단계만**

---

### 옵션 B1 — webxr_to_pose에 WebRTC peer 직접 통합 (영상 헤드셋 내) ⭐ 권장

**아키텍처**:

```
Galaxy XR Chrome
  └─ webxr_to_pose.html (확장)
       ├─ XR-RAF onFrame
       │    ├─ pose extract → ws://localhost:8013/pose (JSON)
       │    └─ WebGL: texImage2D(video) → XR canvas plane render
       │
       └─ RTCPeerConnection (1~3개, 카메라별)
           │
           │  POST /offer {sdp, type}
           ▼
Sim host: image_server.py /offer endpoint (변경 없음)
           │  ← SDP answer
           │
           └─ pc.ontrack → MediaStream → <video> element (off-screen)
                                            ↑
                                            └─ texImage2D source

PC docker
  └─ test_pose_only_ws.py (BridgePoseStore + multiprocessing.Array)
       ↓
  └─ teleop_hand_and_arm.py (run_teleop_ws.py wrapper로 launch, BridgePoseStore inject)
       ↓
       IK / DDS pub  →  IsaacSim G1+Dex3
```

**핵심**: vuer client React가 하던 `WebRTCVideoPlane` 동작을 webxr_to_pose가 직접 수행. 패턴은 vuer가 검증한 그대로(`fetch('/offer', {sdp, type})` → `pc.setRemoteDescription(answer)` → `pc.ontrack` → `MediaStream` → `video.srcObject`). XR canvas에 plane geometry + video texture는 WebGL 표준 (Three.js 없이도 가능).

**변경 위치 / 양**:
- 옵션 A의 변경사항 전부 + 다음
- [webxr_to_pose.html](../setup/webxr_to_pose.html) — WebRTC peer 코드 추가 (~150-200줄):
  - 카메라별 RTCPeerConnection 생성(`addTransceiver('video', {direction:'recvonly'})`)
  - `https://<img_server_ip>:<port>/offer` POST + answer 처리
  - `pc.ontrack` → off-screen `<video>` element + `play()`
  - onFrame loop 안에서 `gl.texImage2D(target, level, internalFormat, ..., video)` 호출 + plane geometry 그림
  - monocular: head_camera 하나 (port 60001)
  - binocular: head 좌/우 layer 또는 stereo single texture (vuer의 `WebRTCStereoVideoPlane`과 동일 패턴 — [televuer.py:434-444](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py#L434-L444) 참고)
  - wrist 카메라는 Week 9에서 picture-in-picture로 다룬다 — 현재 plan에서는 head_camera만

**unitree 측 코드 변경**:
- `xr_teleoperate`: **0줄**
- `televuer`: **0줄**
- `teleimager`: **0줄** (image_server.py의 /offer endpoint 그대로 사용)

**장점**:
- **vuer client React 완전 우회** + 영상도 헤드셋 안 표시 + sim host↔헤드셋 직접(PC 안 거침, latency 최소)
- vuer가 검증한 WebRTC 패턴 그대로 차용 → 위험 낮음
- 옵션 A 통과 후 영상만 incremental 추가 → 점진적 검증
- Phase 3(native APK) 이전까지 영구 backup 가치

**단점**:
- WebGL video texture / RTCPeerConnection JS 작성 (~200줄)
- Galaxy XR Chrome의 WebRTC 안정성 검증 필요 (Quest 3는 vuer 통해 검증됨, Galaxy XR 직접 peer는 미검증)
- cert 신뢰 절차 그대로 적용 (`https://localhost:60001` 등 한 번씩 신뢰) — 사용자 부담 동일

**작업량**: 옵션 A 위에 +3-4 man-day

**적합 phase**: Week 4-6 Gate 4(IsaacSim UR10e+DG-5F 안정 teleop) 통과용 ⭐ **본 plan의 default 권장**

---

### 옵션 B2 — PC server image relay (ZMQ → ws binary)

**아키텍처**:

```
Galaxy XR Chrome
  └─ webxr_to_pose.html (확장)
       └─ ws://localhost:8013 (binary frame in same connection or separate)
           ├─ pose: JSON (기존)
           └─ video: ArrayBuffer (JPEG)
               → createImageBitmap → texImage2D → XR plane

PC docker
  └─ test_pose_only_ws.py (확장)
       ├─ pose receive (기존)
       ├─ ImageClient(sim_host_ip).get_head_frame() polling (~30Hz)
       │      ↓ JPEG encode (필요 시)
       │      ↓
       └─ ws binary push to client

Sim host: image_server.py ZMQ port 55555 (변경 없음, ZMQ 그대로)
```

**변경 위치 / 양**:
- 옵션 A 위에 다음:
- [setup/test_pose_only_ws.py](../setup/test_pose_only_ws.py) — `ImageClient` 호출 + ws send binary frame (~100줄)
- [webxr_to_pose.html](../setup/webxr_to_pose.html) — `ws.onmessage`에서 binary 분기 + `createImageBitmap` + texImage2D (~80줄)

**unitree 측 코드 변경**:
- `xr_teleoperate`: **0줄**
- `televuer`: **0줄**
- `teleimager`: **0줄** (image_client 그대로 사용)

**장점**:
- WebRTC 협상 회피 — 단순 ws binary
- teleimager `ImageClient` 그대로 활용 (Week 1부터 검증됨)
- B1보다 JS 작업 작음(WebGL video는 동일하지만 RTCPeerConnection 협상 없음)

**단점**:
- PC 경유 — same-host docker라 latency는 미미하지만 throughput은 PC가 burst handling
- JPEG decode가 browser 측에서 매 frame 발생 (Quest 3 vuer는 hardware-accelerated video decode 사용 → Galaxy XR도 같은 GPU path를 쓰면 fps 더 안정)
- monocular는 OK인데 stereo binocular의 경우 두 frame을 stride/sync 맞춰 보내야 — B1의 stereo는 sim host의 stereo SDP 그대로 사용

**작업량**: 옵션 A 위에 +2-3 man-day

**적합 phase**: B1이 WebRTC 협상 실패 시(예: 특정 codec/profile mismatch) **fallback**

---

### 옵션 C — vuer client_build chunk JS 직접 패치

**아키텍처**:

```
vuer는 그대로, client_build chunk-Dd3xtWba.js의 useInterval 사용 부분을
xrSession.requestAnimationFrame 기반 publish로 패치
```

**변경 위치 / 양**:
- `/usr/local/lib/python3.10/dist-packages/vuer/client_build/assets/chunks/chunk-Dd3xtWba.js`(또는 동등 chunk) — minified bundle 직접 string 치환 + setup/install.sh에서 자동 적용
- 패치 대상: Hands 컴포넌트의 `useInterval(J, 1e3/a)` 호출을 자체 `xrSession.requestAnimationFrame` 기반으로 교체 + Camera 컴포넌트도 동일
- 또는 vuer 0.0.60을 fork해서 동일 수정 후 wheel build

**unitree 측 코드 변경**:
- `xr_teleoperate`: 0줄(또는 fork 시 setup.py에서 vuer pin 변경)
- `televuer`: 0줄
- `teleimager`: 0줄

**장점**:
- 기존 vuer 인프라 그대로 활용 — 영상도 vuer가 처리(B1처럼 WebRTC 별도 작성 안 함)
- 본질적 fix

**단점**:
- minified bundle 직접 패치는 매우 깊은 작업 + 검증 어려움 + vuer 업그레이드마다 재적용
- vuer fork 시 maintenance burden 큼 + dex-retargeting의 vuer dep와 충돌 가능
- React internals 패치는 부작용 위험 (다른 컴포넌트의 useInterval도 모두 동일 hook을 import할 가능성)
- 정확한 원인이 useInterval인지 R3F XR-RAF transition인지 아직 100% 확신 안 됨 → 패치 후에도 다른 freeze 가능

**작업량**: ~5-10 man-day (수정 + 검증 + maintenance)

**적합 phase**: 권장 안 함. Phase 3 native APK가 어차피 더 깨끗한 해결책

---

### 옵션 D — 운영 모드 분리 (임시방편)

**아키텍처**:
- webxr_to_pose.html(헤드셋, pose만) + desktop chrome (vuer page or sim host WebRTC URL, 영상만, operator의 PC monitor에 띄움)
- 같은 PC에서 두 페이지 동시 운영

**변경 위치 / 양**: 옵션 A와 동일 (영상 작업 zero)

**unitree 측 코드 변경**: 옵션 A와 동일

**장점**:
- 옵션 B1 작업 진행 중 임시 운영 가능
- 영상은 vuer를 통한 immersive 운영이 아니라 단순 desktop 영상 — Galaxy XR Chrome freeze 영향 zero

**단점**:
- operator가 헤드셋 벗어야 영상 봄 — teleop 직관성 매우 낮음
- 짧은 demo 또는 정성 sanity 외 비현실적

**적합 phase**: 옵션 B1 작업 도중 G1 sim sanity 시 임시 — **운영 backup 아님, 검증 보조 용도**

---

## 3. 권장 우선순위 및 로드맵

### 3.1 권장 순서

| Step | 옵션 | 목표 | 작업량 | Gate |
|---|---|---|---|---|
| **1** | **옵션 A** | BridgePoseStore + run_teleop_ws.py wrapper. G1+Dex3 IsaacSim에서 손 동작/팔 동작 sanity (영상 없이) | 1-2일 | Week 4 sanity |
| **2** | **옵션 B1** | webxr_to_pose에 WebRTC peer + head_camera plane. 영상 + pose 동시 운영 | +3-4일 | Gate 4 (UR10e+DG-5F sim teleop) |
| (3) | (B2 fallback) | B1 WebRTC 협상 실패 시 ZMQ relay로 전환 | +2-3일 | - |
| (4) | (C 마지막 backup) | vuer 자체 fix가 정말 필요해지면 | +5-10일 | - |

### 3.2 단계별 구현 로드맵

**Step 1.1 — BridgePoseStore (옵션 A)**
- `setup/test_pose_only_ws.py`의 `PoseStore`를 multiprocessing.Array 기반으로 발전. 변수명/property를 `TeleVuer`(televuer.py:138-173 + property accessor) 100% 동일 시그니처. 새 클래스명: `BridgePoseStore` 또는 `WSPoseTeleVuer` (의미 명확)
- orientation도 추가 (현재 position만) — `left_hand_orientation_shared` (25*9 float, 3x3 rotation matrix flattened column-major)

**Step 1.2 — run_teleop_ws.py wrapper**
- [setup/run_teleop.py](../setup/run_teleop.py) fork
- `_apply_http_monkey_patch` 제거(vuer 안 씀)
- 신규 `_inject_bridge_pose_provider`: `televuer.tv_wrapper.TeleVuer`를 monkey-patch해 우리 BridgePoseStore 반환하도록(또는 직접 `TeleVuerWrapper.__init__`을 patch해서 `self.tvuer = our_bridge` inject)
- `_patch_image_spawn_retry` 제거 (영상 미통합)
- cwd 변경, sanity check, sys.argv 정리 등은 그대로

**Step 1.3 — webxr_to_pose.html에 orientation 송신 추가**
- 25 joint마다 `jp.transform.orientation` (quaternion) → matrix 변환 → 9 float. 또는 quaternion 그대로 송신하고 Python 측에서 변환
- JSON 송신 크기: 25*16 + 25*9 = 625 float per hand → 13KB/frame x 30Hz x 2 hands ≈ 800KB/s — adb reverse USB는 충분

**Step 1.4 — G1 sim sanity 검증**
- run_teleop_ws.py로 G1+Dex3 IsaacSim teleop 시도. 영상 없이 헤드셋 안에서 손 들이밀기 → IsaacSim G1 팔 + Dex3 손가락 따라오는지 시각 확인 (사용자가 IsaacSim 화면 별도 모니터로 볼 것)
- 30+ Hz pose 안정 + 자연스러운 hand sync
- 실패 시 BridgePoseStore의 좌표 변환 정밀 검증 필요 (Quest 3 결과와 정성 비교)

**Step 2.1 — WebRTC peer JS 구현**
- webxr_to_pose.html에 monocular head_camera용 RTCPeerConnection 추가
- offer endpoint: `https://localhost:60001/offer`(웹기 reverse 필요)
- ICE 서버는 비움 (`iceServers: []`, vuer 패턴 그대로)
- `pc.addTransceiver('video', {direction:'recvonly'})` + `createOffer` + `setLocalDescription` + fetch POST + `setRemoteDescription(answer)`
- `pc.ontrack` → `<video>` element 생성 (off-screen, `style.display=none`이라도 OK) + `video.srcObject = stream` + `video.play()`

**Step 2.2 — WebGL video plane**
- WebGL 2 컨텍스트에 plane geometry (단일 quad) + vertex/fragment shader
- onFrame loop 안에서 `gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video)` 매 frame
- XR camera projection 사용해 plane을 viewer 앞 1m 거리에 distance-to-camera 1로 배치 (vuer ImageBackground 패턴과 동일)

**Step 2.3 — binocular stereo (선택, Quest 3 binocular와 일치시키려면)**
- sim host의 binocular WebRTC offer가 stereo-left-right layout으로 single track 송신 (vuer `WebRTCStereoVideoPlane`이 이걸 받아 좌/우 layer로 분리)
- WebGL 측에서 같은 texture를 좌/우 viewport에 다른 UV로 그림 (XR view 0=left, 1=right)

**Step 2.4 — adb reverse 자동화**
- `setup/run_teleop_ws.py`에 `adb reverse tcp:8013 + tcp:60001 (+ 60002 + 60003)` 자동 호출(또는 README에 명시)

**Step 2.5 — Gate 4 sanity (Week 6)**
- UR10e+DG-5F sim과 함께 영상 + pose 통합 teleop 검증
- 30 Hz 안정 + 영상 latency < 100ms + ws message rate ≥ 30/s

### 3.3 Phase 2 UR10e+DG-5F 교체 시 영향

- pose interface는 동일 — BridgePoseStore는 G1/UR10e 모두 동일 코드 (좌표계는 robot side에서 변환)
- teleop_hand_and_arm.py의 IK/DDS 부분만 UR10e용으로 교체 (Week 4-5 작업)
- 우리 wrapper(run_teleop_ws.py)는 그대로 ([standalone/](../../standalone/) 폴더의 UR10e용 IK pipeline과 합쳐 별도 launcher로 발전 가능)

---

## 4. 권장 아키텍처 상세 (Step 1+Step 2 통합)

### 4.1 데이터 흐름도

```
                                Galaxy XR HMD
                                      │
                              [USB adb reverse]
                                      │
                                      ▼
                  ┌────────────── PC docker ───────────────┐
                  │                                         │
   pose JSON      │                                         │  WebRTC SDP/RTP
   (ws msgs)      │                                         │  (adb reverse)
       ▲          │                                         │       ▲
       │          │                                         │       │
       └──────────┘                                         │       │
                                                            │       │
   ┌─────────────────────────────────────────────────┐      │       │
   │ test_pose_only_ws.py                            │      │       │
   │   ┌─────────────────────────┐                   │      │       │
   │   │ aiohttp ws server :8013 │ ──── http GET / ──┤      │       │
   │   │  + http static          │                   │      │       │
   │   └────────────┬────────────┘                   │      │       │
   │                ▼                                │      │       │
   │   ┌──────────────────────────────────┐          │      │       │
   │   │ BridgePoseStore                  │          │      │       │
   │   │  multiprocessing.Array (TeleVuer │          │      │       │
   │   │   interface mimick)              │          │      │       │
   │   └────────────┬─────────────────────┘          │      │       │
   │                ▼                                │      │       │
   │   ┌──────────────────────────────────┐          │      │       │
   │   │ run_teleop_ws.py wrapper         │          │      │       │
   │   │  - cwd → xr_teleoperate/teleop   │          │      │       │
   │   │  - inject BridgePoseStore        │          │      │       │
   │   │  - sanity check (conda env, etc) │          │      │       │
   │   └────────────┬─────────────────────┘          │      │       │
   │                ▼                                │      │       │
   │   ┌──────────────────────────────────┐          │      │       │
   │   │ teleop_hand_and_arm.py (변경 X)  │          │      │       │
   │   │  TeleVuerWrapper(tvuer=ours)     │          │      │       │
   │   │   → IK → DDS publisher           │          │      │       │
   │   └────────────┬─────────────────────┘          │      │       │
   │                ▼                                │      │       │
   │            DDS rt/lowcmd                        │      │       │
   └─────────────────┬───────────────────────────────┘      │       │
                     │                                      │       │
                     ▼                                      │       │
            ┌──────────────────────────┐                    │       │
            │ Sim host docker          │                    │       │
            │  sim_main.py (G1+Dex3)   │ ─── DDS lowstate ──┘       │
            │   ↓                      │                            │
            │  image_server.py         │ ─── WebRTC /offer + RTP ───┘
            │   (ZMQ + WebRTC, 변경 X) │
            └──────────────────────────┘
```

### 4.2 신규 / 수정 파일 목록

| 파일 | 상태 | 변경 |
|---|---|---|
| [setup/test_pose_only_ws.py](../setup/test_pose_only_ws.py) | 수정 | PoseStore → BridgePoseStore(multiprocessing.Array, TeleVuer mimick) |
| [setup/webxr_to_pose.html](../setup/webxr_to_pose.html) | 수정 | orientation 송신 + WebRTC peer + WebGL video plane |
| `setup/run_teleop_ws.py` | 신규 | run_teleop.py 패턴 + BridgePoseStore inject monkey-patch |
| [setup/README.md](../setup/README.md) | 수정 | Step I 신규: Galaxy XR ws bridge teleop 절차 |
| [docs/xr_teleoperate_setup_issues.md](xr_teleoperate_setup_issues.md) | 수정 | §1.12 Galaxy XR vuer freeze + ws bridge 처방 |

### 4.3 TeleVuer interface mimick 변수명 매핑표

[televuer.py:138-173](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py#L138-L173)의 shared 변수와 그에 대응하는 ws 메시지 / property:

| TeleVuer 변수 | 크기/형식 | ws JSON key | property |
|---|---|---|---|
| `head_pose_shared` | 16 float (4x4 col-major) | `head.matrix` | `head_pose` |
| `left_arm_pose_shared` | 16 float | `hand.handedness=left, hand.wrist` | `left_arm_pose` |
| `right_arm_pose_shared` | 16 float | `hand.handedness=right, hand.wrist` | `right_arm_pose` |
| `left_hand_position_shared` | 25*3 float | `hand.positions` | `left_hand_positions` |
| `right_hand_position_shared` | 25*3 float | `hand.positions` | `right_hand_positions` |
| `left_hand_orientation_shared` | 25*9 float | `hand.orientations` (Step 1.3 추가) | `left_hand_orientations` |
| `right_hand_orientation_shared` | 25*9 float | `hand.orientations` | `right_hand_orientations` |
| `left_hand_pinch_shared` | bool | `hand.pinch` (Step 1.3 추가) | `left_hand_pinch` |
| `left_hand_pinchValue_shared` | float | `hand.pinchValue` | `left_hand_pinchValue` |
| `left_hand_squeeze_shared` | bool | `hand.squeeze` | `left_hand_squeeze` |
| `left_hand_squeezeValue_shared` | float | `hand.squeezeValue` | `left_hand_squeezeValue` |
| (right 동일) | | | |

pinch/squeeze는 WebXR 표준에 직접 없으므로 client 측에서 thumb-tip ↔ index-finger-tip 거리 < threshold로 계산하거나, vuer가 사용한 방식([televuer/dist/index.js의 `getHandLandmarks`](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py))을 답습.

---

## 5. unitree 측 코드 변경량 평가

| 패키지 | 옵션 A | 옵션 B1 | 옵션 B2 | 옵션 C |
|---|---|---|---|---|
| `xr_teleoperate` (teleop_hand_and_arm.py 등) | **0줄** | **0줄** | **0줄** | 0줄 (vuer fork면 setup.py 1줄) |
| `televuer` | **0줄** | **0줄** | **0줄** | 0줄 |
| `teleimager` | **0줄** | **0줄** | **0줄** (image_client 재활용) | 0줄 |
| `vuer` (client_build) | **0줄** | **0줄** | **0줄** | **수십~수백 줄 minified 패치** |

→ **옵션 A/B1/B2 모두 unitree 측 직접 코드 수정 없음** (전부 우리 setup/ 폴더의 wrapper + monkey-patch). 옵션 C만 깊은 패치 필요.

옵션 A/B1/B2의 trade-off는 변경량이 아닌 **"vuer 우회 범위 + 영상 처리 방식 + 작업량"**:

| 측면 | A | B1 | B2 |
|---|---|---|---|
| pose 우회 | OK | OK | OK |
| 영상 우회 | 없음 | RTCPeerConnection 직접 | PC ZMQ relay |
| 영상 latency | - | 최소 (직접) | +PC 1-hop |
| WebRTC 협상 부담 | - | client JS 작성 | 없음 |
| JS 작업량 | 작음 | 중간 (200줄) | 작음 (80줄) |
| Python 작업량 | 중간 (100-200줄) | 동일 | +ImageClient 통합 (100줄) |

---

## 6. 위험 요소

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| 1 | WebRTC offer/answer JS 협상에서 sim host의 SDP/codec 형식 mismatch (B1) | 영상 끊김/안 보임 | image_server.py의 `aiortc.codecs.h264` 설정 확인 + Quest 3 vuer가 동작한 SDP 분석. fallback으로 B2 |
| 2 | WebGL video texImage2D 성능 (Galaxy XR Chrome 미검증) | fps 저하 / dropped frames | OffscreenCanvas + GPU texture sharing 또는 EXT_video_texture extension 활용 (벤치 후 결정) |
| 3 | XR-RAF + WebRTC + ws 동시 운영 시 throttling | pose 송신 rate 저하 | onFrame 안 작업을 최소화 + 메인 thread 외부에 WebRTC 처리 |
| 4 | cert 신뢰 절차 변화 가능성 (Chrome update) | 영상 안 보임 | gen_certs.sh + `chrome://flags/#allow-insecure-localhost` 가이드 유지 |
| 5 | BridgePoseStore가 TeleVuer interface와 정확히 일치 안 됨 (pinch/squeeze 계산 차이 등) | 손가락 retargeting 부정확 | dex_retargeting 입력 형식과 비교 검증 + Quest 3 결과 정량 비교 |
| 6 | adb reverse 한 번에 4 port (8013+60001+60002+60003) USB 안정성 | 끊김 | 한 port부터 시작, monocular(60001만)로 단순화 가능 |
| 7 | WebRTC peer 진입 시점에 vuer freeze와 같은 R3F XR-RAF 전환 race가 우리에게도 발생할 가능성 | 영상 안 그려짐 | webxr_check.html은 정상 동작 확인 — XR-RAF 기반이라 같은 메커니즘이면 우리도 정상. 그러나 검증 필요 |

---

## 7. 다음 단계 결정 사항 (사용자 검토 요청)

다음을 확정해 주시면 본격 구현 진입합니다:

1. **권장 순서 (Step 1 옵션 A → Step 2 옵션 B1) 동의 여부**
   - 또는 Step 1 건너뛰고 바로 Step 2부터? (B1이 영상 포함이라 작업 크지만 한 번에 본격 운영 가능)
   - 또는 옵션 A만 끝내고 Quest 3로 영상 + Galaxy XR로 pose 따로 운영하는 hybrid 운영? (현실성 낮음)

2. **영상 카메라 범위**
   - head_camera only (monocular)
   - head_camera binocular(stereo-left-right)
   - head + 양 wrist (3개) — Week 9에서 picture-in-picture로 다루려는 항목

3. **BridgePoseStore의 인터페이스 정확도**
   - TeleVuer 100% mimick (current TeleVuerWrapper 코드 변경 없이 그대로 동작)
   - 또는 TeleVuerWrapper도 fork해서 좌표 변환 단순화? (좌표 변환이 우리 BridgePoseStore에서 이미 적용 가능하므로 wrapper 우회 가능)

4. **운영 후 docs 정리**
   - 본 docs는 설계 문서 — 구현 완료 후 [setup_issues.md §1.12](xr_teleoperate_setup_issues.md)에 짧게 정리하고 본 docs는 reference로 유지하시려는지

5. **timing — Week 4 sanity vs Gate 4 본격**
   - Week 4 안에 Step 1.x 완료 후 Step 2는 Week 5-6에 점진적?
   - 또는 영상이 없으면 Week 4 sanity 자체가 의미 작으니 Step 1+Step 2 묶음으로 Week 5 일주일 통째로?

---

## 부록 A — vuer client freeze 진단 trace 요약

이 문서의 "왜 우회가 필요한가" 결론 근거를 한 줄로:

1. webxr_check.html(자체 진단)에서 navigator.xr / immersive-vr / immersive-ar / hand-tracking 모두 정상 (Galaxy XR Chrome WebXR API 정상)
2. vuer 우회 ws bridge(test_pose_only_ws.py)에서 hand pose 정상 30Hz 수신 (XR-RAF 기반 onFrame이 메커니즘으로 동작)
3. vuer 경로(test_pose_only.py --http)에서 cam=7, hand=2 / 30s = >99% loss (vuer client React publish freeze)
4. setInterval 30Hz 정상 fire(가설 기각), document.hidden=false 유지(가설 기각), xrSession.visibilityState=visible 유지(가설 기각)
5. vuer chunk JS source map 분석에서 publish 가드는 정상 — `D && (...) || S(...)` (D=mode/g=stream/o,l=disable, 모두 정상값)
6. R3F의 `useFrame`(일반 RAF 기반)이 Galaxy XR Chrome immersive 안에서 XR-RAF로 transition 안 되거나 stale 상태로 남는 게 유력 가설

---

## 부록 B — Phase 2 UR10e+DG-5F 교체 시 변경량

본 통합 설계는 **pose interface가 robot-agnostic**:

- BridgePoseStore가 노출하는 변수명/형식은 TeleVuer interface (즉 OpenXR convention). 좌표 변환은 TeleVuerWrapper(또는 우리 fork) 안에서 robot convention으로
- teleop_hand_and_arm.py의 G1_29_ArmIK → UR10e_ArmIK 교체(Week 4-5 작업)는 본 wrapper와 무관
- DG-5F retargeting(Week 5)도 본 wrapper에서 inject되는 hand pose 데이터만 정상이면 dex_retargeting 측은 그대로

→ Week 4-6 UR10e+DG-5F 교체와 본 wrapper 작업은 **병렬 진행 가능**.

---

*문서 끝. 검토 후 §7 "다음 단계 결정 사항" 항목별 답변 주시면 본격 구현 plan으로 진입합니다.*
