# Galaxy XR용 WS 브리지 — Vuer 우회 구조 정리

> **대상**: [communication_protocols_guide.md](communication_protocols_guide.md)를 읽은 사람
> **목적**: 왜 Galaxy XR에서 Vuer를 못 쓰고 [test_pose_only_ws.py](../scripts/test_pose_only_ws.py)를 새로 만들었는지, 그리고 두 구조의 차이가 뭔지 정리

---

## 1. 한 줄 요약

| 구분           | 기존 Vuer 기반                         | 새로 만든 WS 브리지                    |
|----------------|----------------------------------------|----------------------------------------|
| 파일           | [test_pose_only.py](../scripts/test_pose_only.py) | [test_pose_only_ws.py](../scripts/test_pose_only_ws.py) + [webxr_to_pose.html](../assets/webxr_to_pose.html) |
| VR쪽 코드      | Vuer가 자동 생성한 React/Three.js 페이지 | 직접 짠 200줄짜리 HTML + WebXR 코드   |
| PC쪽 서버      | Vuer 프레임워크 (TeleVuer가 wrap)      | aiohttp + plain WebSocket             |
| 데이터 전송    | Vuer 자체 프로토콜 (이벤트 객체)       | JSON 메시지 (직접 정의)               |
| Galaxy XR 동작 | **❌ 30초간 7회만 publish 후 멈춤**    | **✅ 정상 동작**                      |

핵심: Vuer 클라이언트(React)가 Galaxy XR Chrome immersive에서 멈추는 버그를 만나서, **Vuer 클라이언트만 통째로 버리고** 자체 HTML로 대체했다. Python 측은 Vuer 자체가 빠졌으니 웹서버도 직접 띄운다.

---

## 2. 왜 Vuer가 Galaxy XR에서 멈췄나?

### Vuer의 평소 동작 (Quest 3 등에서 정상)

```
[VR 헤드셋 브라우저]
  ↓ Vuer 서버에 접속하면 React 앱이 자동으로 다운로드됨
  ↓ Vuer client (React) 가:
  ↓   1. Three.js로 3D 씬을 그림
  ↓   2. WebXR API로 손/머리 자세 추적
  ↓   3. 매 프레임 자세를 Vuer 프로토콜로 직렬화
  ↓   4. Vuer 서버에 WebSocket으로 publish
  ↓
[PC: Vuer Python 서버]
  ↓ on_cam_move / on_hand_move 핸들러 호출
  ↓ 공유 메모리에 자세 저장
  ↓
[teleop_hand_and_arm.py]
  ↓ tv.head_pose, tv.left_arm_pose 등 read
```

### Galaxy XR에서 발생한 증상

[test_pose_only.py](../scripts/test_pose_only.py)의 `--debug` 모드 (159-169 line의 monkey-patch)로 카운터를 찍어보니:

- `on_cam_move` 호출: **immersive 진입 후 7회만**
- `on_hand_move` 호출: **2회만**
- 그 후 30초간 완전히 멈춤
- 헤드셋 화면은 정상 (Three.js 렌더링은 살아 있음)
- WebSocket 연결도 살아 있음 (close 안 됨)

즉, **VR 헤드셋쪽 React 코드 어디선가 publish loop이 죽어버린다**는 것.

### 검증: WebXR 자체는 살아 있다

[webxr_check.html](../assets/webxr_check.html) (Vuer 없이 순수 WebXR API만 사용하는 진단 페이지)로 같은 헤드셋에서 테스트해보니 — **30Hz로 끊김 없이 동작**. 즉:

- WebXR 표준 자체는 Galaxy XR Chrome에서 정상
- Vuer 0.0.60의 React 클라이언트가 Galaxy XR Chrome 환경에서만 죽음
- 정확한 원인은 Vuer 내부지만 디버깅에 시간 쓰는 것보단 우회가 빠르다는 판단

---

## 3. 우회 구조의 핵심 아이디어

> **"Vuer는 결국 두 가지를 한다 — VR쪽에서 자세 추출 + PC쪽으로 전송. 그럼 둘 다 직접 만들면 된다."**

### Vuer가 해주던 것을 우리가 직접 하는 것으로 치환

| Vuer가 해주던 일                              | 우리가 대체한 방법                              |
|-----------------------------------------------|-------------------------------------------------|
| React 페이지를 자동 생성                      | [webxr_to_pose.html](../assets/webxr_to_pose.html) 직접 작성 (258줄) |
| WebXR API 호출 + 프레임 루프                  | `xrSession.requestAnimationFrame(onFrame)` 직접 호출 |
| 손/머리 자세를 Vuer 프로토콜로 직렬화         | JSON 메시지로 직접 직렬화 (`{type:'head', matrix:[...]}`) |
| Three.js 씬 렌더링                            | **생략** (검은 화면만 클리어)                   |
| Vuer 서버 (aiohttp 기반 WebSocket)            | aiohttp WebSocket 직접 띄움                     |
| `TeleVuer.head_pose` 등 NumPy 인터페이스      | `PoseStore` 클래스가 같은 형태로 제공           |

핵심은 **데이터 형식을 기존 `TeleVuer`와 똑같이 맞췄다는 것** — `PoseStore.snapshot()`이 `head_pose (4×4)`, `left_hand_positions (25×3)` 등 동일 shape을 돌려주므로, 후속 IK/리타게팅 코드를 그대로 쓸 수 있다.

---

## 4. 두 구조 다이어그램 비교

### 기존 Vuer 구조

```
[Galaxy XR Chrome]
  └─ React App (Vuer가 자동 생성)
       ├─ Three.js 렌더링
       ├─ WebXR API 호출
       └─ Vuer 프로토콜로 자세 publish ❌ 7회 후 멈춤
                  │
                  │ WebSocket (Vuer 내부 프로토콜)
                  ▼
[PC: Vuer 서버 (TeleVuer wrap)]
  ├─ on_cam_move 핸들러
  ├─ on_hand_move 핸들러
  └─ 공유 메모리에 NumPy 배열로 저장
                  │
                  │ tv.head_pose 등 property 접근
                  ▼
[test_pose_only.py main loop]
```

### 새 WS 브리지 구조

```
[Galaxy XR Chrome]
  └─ webxr_to_pose.html (자체 작성)
       ├─ WebXR API 호출 (XRSession.requestAnimationFrame)
       ├─ frame.getViewerPose() → head matrix
       ├─ frame.getJointPose() × 25 → hand positions
       └─ JSON으로 publish ✅ 30Hz 정상
                  │
                  │ WebSocket (plain JSON)
                  ▼
[PC: aiohttp WS 서버 (test_pose_only_ws.py)]
  ├─ ws_handler: JSON 파싱
  └─ PoseStore.update_head / update_hand
                  │
                  │ STORE.snapshot() 호출
                  ▼
[test_pose_only_ws.py main loop]
```

차이의 본질: **Vuer가 담당하던 "VR쪽 React 코드"가 우리 250줄짜리 HTML로, "PC쪽 Vuer 서버"가 aiohttp 100줄로 대체**됐다. 메인 루프 로직은 동일.

---

## 5. JSON 프로토콜 (직접 정의)

`webxr_to_pose.html`이 PC로 보내는 메시지 두 가지:

### Head 메시지
```json
{
  "type": "head",
  "ts": 1234567.89,                        // performance.now() ms
  "matrix": [16 floats, column-major]      // SE(3)
}
```
- 출처: `frame.getViewerPose(xrRefSpace).transform.matrix`
- 좌표계: WebXR `local-floor` reference space (바닥 기준)

### Hand 메시지
```json
{
  "type": "hand",
  "ts": 1234567.89,
  "handedness": "left" | "right",
  "wrist": [16 floats],                    // wrist joint의 SE(3) matrix
  "positions": [[x,y,z], ...] // 25개      // 25개 관절 위치
}
```
- 25개 관절 순서는 `JOINT_NAMES` 배열 (HTML 102~113 line)에 정의 — **vuer/televuer 기대 순서와 동일하게 맞춤**
- 그래야 후속 hand retargeting 코드를 수정 없이 재사용 가능

---

## 6. 데이터 흐름 추적 — 한 메시지의 일생

손가락 하나를 움직였을 때:

```
1. [Galaxy XR Chrome, onFrame() loop, 60Hz]
   xrSession.requestAnimationFrame 콜백이 호출됨
        ↓
2. [같은 곳]
   for src of frame.session.inputSources:
       for joint of 25:
           jp = frame.getJointPose(joint, xrRefSpace)
           positions[i] = [jp.transform.position.x, y, z]
        ↓
3. [같은 곳]
   ws.send(JSON.stringify({type:'hand', handedness:'left', wrist:..., positions:...}))
        ↓
4. [네트워크: localhost (adb reverse로 USB 터널링)]
   WebSocket TEXT frame, ~3KB
        ↓
5. [PC: aiohttp ws_handler async loop]
   payload = json.loads(msg.data)
   STORE.update_hand("left", payload["wrist"], payload["positions"])
        ↓
6. [PoseStore (lock 보호)]
   self.left_arm_pose[:] = wrist          # 16 floats
   self.left_hand_positions[:] = flat     # 75 floats
   self.msg_count += 1
        ↓
7. [메인 루프, 200Hz polling]
   snap = STORE.snapshot()
   snap["lh"] → (25,3) reshape
   if not is_hand_tracked(snap["lh"]): lost_counts += 1
        ↓
8. [측정 또는 smoke 출력]
```

**핵심**: 4단계의 네트워크 hop만 **WebSocket → aiohttp** 로 단순화됐을 뿐, 5단계 이후의 NumPy 배열 형태는 [test_pose_only.py](../scripts/test_pose_only.py)와 100% 동일하다. 이는 의도된 설계다.

---

## 7. 두 스크립트의 코드 레벨 비교

### 데이터 접근 방식

```python
# test_pose_only.py (Vuer 기반)
tv = TeleVuer(use_hand_tracking=True, ...)
head = tv.head_pose                # property가 shared array를 reshape해서 리턴
lw   = tv.left_arm_pose
lh   = tv.left_hand_positions

# test_pose_only_ws.py (WS 브리지)
snap = STORE.snapshot()             # lock 잡고 dict로 묶어서 리턴
head = snap["head"]
lw   = snap["lw"]
lh   = snap["lh"]
```

shape도, 의미도 동일. 이름만 짧게 줄였다.

### 측정 항목 (둘 다 동일)

- `mean_freq_hz` (WS 브리지에선 `ws_msg_hz`로 이름만 바뀜) — 30Hz 이상이면 통과
- `nan_per_field` — NaN 발생 프레임 수
- `lost_frames_per_field` — 자세가 비어있는 프레임 수 (`M[3,3] != 1`)
- `recovery_latency_s` — 손이 시야 밖으로 나갔다 다시 잡히기까지 시간 (1초 이내 통과)
- `wrist_jitter_cm` — 마지막 5초 정지 상태에서 손목 위치 표준편차

---

## 8. 실행 방법

```bash
# 1. PC측
adb reverse tcp:8013 tcp:8013                           # USB 포트포워딩
python3 scripts/test_pose_only_ws.py                      # smoke 모드
python3 scripts/test_pose_only_ws.py --measure 30 \
        --report docs/galaxy_xr.md                      # 30초 측정 + 보고서

# 2. Galaxy XR 헤드셋
Chrome으로 http://localhost:8013/ 접속
"Enter VR" 또는 "Enter AR" 버튼 클릭
손을 시야 안에 들이밀기

# 3. PC 콘솔에서 1Hz로 진단 로그 확인
#    msg/s, head/LW/RW/LH/RH 상태, hand_pos[0] 좌표
```

기존 Vuer 버전은 포트가 `8012`, HTTPS 인증서가 필요했고 — 새 WS 브리지는 `8013`, plain HTTP로 충분 (localhost는 W3C secure context 예외 적용되어 WebXR 사용 가능).

---

## 9. 트레이드오프

### 잃은 것

- **VR 화면에 카메라 영상 표시 불가** — Vuer가 했던 Three.js 렌더링이 빠짐. 실제 텔레오퍼레이션엔 카메라 영상이 필수.
- **Vuer ecosystem과 단절** — Vuer 컴포넌트(Hands, Sphere 등) 사용 불가.

### 얻은 것

- **Galaxy XR에서 작동** — 가장 큰 가치.
- **디버깅 가능** — 코드가 250줄이라 Chrome DevTools로 onFrame 안에 breakpoint 찍어 한 줄씩 따라갈 수 있다. Vuer 내부는 minify된 React라 추적 불가능.
- **의존성 감소** — vuer, params_proto 등 불필요. aiohttp 하나면 끝.
- **프로토콜이 명확** — JSON이라 wireshark/tcpdump로 한눈에 보임. 향후 다른 디바이스/언어 클라이언트 추가도 쉬움.

---

## 10. 다음 단계 (텔레오퍼레이션 본 시스템에 통합하려면)

현재 `test_pose_only_ws.py`는 측정용. 실제로 [teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py)에 붙이려면:

1. **`PoseStore`를 `TeleVuer`처럼 보이게 wrap** — `head_pose`, `left_arm_pose` 등 property로 노출
2. **카메라 영상 표시 분리** — WebRTC로 직접 보내거나, webxr_to_pose.html에 `<video>` 태그 추가해 별도 스트림 받기
3. **좌표계 변환 추가** — 현재는 WebXR raw 좌표. `tv_wrapper.py`의 OpenXR→Robot 변환 (T_ROBOT_OPENXR 등) 적용 필요
4. **손가락 25관절 → robot hand 모터** — 기존 hand retargeting 코드는 그대로 재사용 가능 (입력 shape이 동일하므로)

즉, "Vuer 클라이언트만" 우회한 거라 후단 파이프라인은 그대로 살아있다는 게 이 설계의 장점.

---

## 부록: 왜 이런 식으로 우회하는 게 가능한가?

WebXR은 **W3C 표준 API**다. 즉 어떤 브라우저든 `navigator.xr` 이 있으면 같은 API로 손/머리를 추적할 수 있다. Vuer가 하던 일도 결국 이 표준 API 호출의 wrapper에 불과하다. 따라서 Vuer가 죽으면 표준 API를 직접 쓰면 그만이다 — 이건 Vuer만의 특수 기능이 아니다.

같은 원리로 만약 미래에 Vive Focus, Pico 4 등 다른 헤드셋에서도 Vuer 호환성 문제가 생기면, 같은 `webxr_to_pose.html`을 그대로 쓰면 된다 (WebXR 표준 준수 헤드셋 한정).
