# XR 렌더링 커스터마이징 — 학습된 함정 모음

> Galaxy XR Chrome + WebXR + 자체 ws bridge ([assets/webxr_to_pose.html](../assets/webxr_to_pose.html)) 구조에서 sim 영상 / pose 렌더링을 직접 작성하면서 얻은 실용 노트.
> Three.js (R3F) 같은 high-level 프레임워크가 자동 처리해주던 부분을 raw WebGL + WebXR 로 다룰 때 반복적으로 마주친 함정들. 앞으로 렌더링 커스터마이징 (wrist 카메라 PiP, gaze indicator, F/T overlay, etc.) 시 사전 점검 리스트로 사용.

---

## 1. WebXR per-eye rendering 의 기본 (가장 흔한 실수)

### 함정
- vertex shader 에서 projection matrix 만 곱하고 view matrix 를 빼먹는 경우. `gl_Position = u_proj * vec4(a_pos, 1.0)` 같은 형태.
- 좌우 눈마다 다른 **off-axis frustum** (IPD 보정용 비대칭 절두체) 이 적용되는데 view matrix 가 없으면 plane 이 좌우 눈에 수평으로 살짝 어긋나게 그려짐 → 양 눈 fuse 시 미세한 부자연스러움.

### 올바른 패턴
```glsl
uniform mat4 u_proj;    // view.projectionMatrix
uniform mat4 u_view;    // view.transform.inverse.matrix
uniform mat4 u_model;   // 객체의 world transform (head-locked 면 viewer pose)
void main() {
  gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
}
```

### 한쪽 눈만 감으면 OK 인데 양 눈은 어색하면 → 위 문제 의심
- 정적 화면도 미세하게 어색 → 영구 IPD 오차
- Three.js (R3F) 는 per-eye view matrix 를 자동 처리해서 Quest 3 + vuer 에선 안 보였던 함정. 직접 WebGL 사용 시 의식적으로 적용 필요.

cf. commit `0b017f9` ("per-eye view matrix 추가 — Galaxy XR stereo desync 해소")

---

## 2. head-locked / world-anchored 객체의 좌표 처리

### head-locked plane (사용자 머리 따라가는 HUD 스타일)
- vertex 는 **head-local space** (머리 정면 -z, ±W/2 / ±H/2) 에 정의
- model matrix = `viewerPose.transform.matrix` (head → world)
- 매 frame model matrix 갱신 → plane 이 head 따라 움직이면서 양 눈에 일관되게 보임

### world-anchored 객체 (공간에 고정)
- vertex 는 **reference space (xrRefSpace) 좌표** 에 직접 정의
- model matrix = identity (또는 객체별 transform)
- 머리 움직여도 객체는 공간에 고정

### 한 가지 안티패턴
- view space (eye 기준) 에 vertex 두고 projection 만 곱하기 — § 1 의 함정과 동일. 가능하면 항상 head-local 또는 world space 사용.

cf. [webxr_to_pose.html `_drawVideoPlane`](../assets/webxr_to_pose.html)

---

## 3. Video texture upload 는 view loop 밖에서 frame 당 1회만

### 함정
- onFrame 의 `for (const view of viewerPose.views)` 안에서 매번 `gl.texSubImage2D(... videoEl)` 호출하는 코드.
- 좌안 draw 와 우안 draw 사이 (수 ms) 에 video decoder 가 다음 frame 으로 advance 하면 **좌안=frame N / 우안=frame N+1** → 빠른 motion 시 잔상으로 인식.

### 올바른 패턴
```js
// onFrame:
if (viewerPose) {
  _uploadVideoFrame();              // 1) texture upload 1회
  for (const view of viewerPose.views) {
    gl.viewport(...);
    _drawVideoPlane(view, model);   // 2) per-eye uniform + draw 만
  }
}
```

### Three.js 와 비교
- R3F 는 texture 갱신을 render loop 시작에서 1회만 함 — Quest 3 + vuer 에선 자동.
- raw WebGL + WebXR 사용 시 직접 분리.

cf. commit `334bfd4` ("video texture upload 를 view loop 밖으로 — 잔상 해소")

---

## 4. Hidden video element 의 decode throttling

### 함정
- `<video style="display:none">` 으로 video element 를 화면에서 숨기면 일부 Chromium 모바일 빌드 (Galaxy XR Chrome 포함 가능) 가 decoder 를 throttle → 영상 frame rate 저하 / lag.

### 회피
```html
<video autoplay playsinline muted
       style="position:absolute; left:-1px; top:-1px;
              width:1px; height:1px; opacity:0; pointer-events:none;"></video>
```
- `display:none` 이 아니라 0-size visible. opacity 0 + 1px 로 화면 영향 없음.
- `playsinline` / `muted` 는 모바일 브라우저 autoplay 정책상 필수.

cf. commit `334bfd4` 의 두 번째 변경

---

## 5. Pass-through (immersive-ar) 의 alpha clearing

### 핵심 3 가지
1. WebGL context: `getContext('webgl2', { xrCompatible: true, alpha: true, premultipliedAlpha: false })`
2. session: `requestSession('immersive-ar', { optionalFeatures: [...] })`
3. 매 frame: `gl.clearColor(0, 0, 0, 0); gl.clear(...)` → OS 가 alpha=0 영역에 카메라 영상 합성

### immersive-vr vs immersive-ar
- VR: 검은 배경, 외부 monitor 로 디버깅 시 불편
- AR: pass-through 활성, 외부 환경 보면서 plane 렌더링 가능 → **개발 / 디버깅 시 AR 권장**
- 단, OS pass-through 자체의 refresh rate / 화질은 디바이스 한계 (Galaxy XR 에선 코드로 개선 불가)

### Galaxy XR Chrome UI 특이사항
- vuer 의 pass-through 버튼은 페이지 하단에 위치 — 화면 스크롤해야 보임 (초기 디버깅 시 "버튼이 없다" 고 오인하기 쉬움)

cf. [webxr_to_pose.html startSession](../assets/webxr_to_pose.html)

---

## 6. WebRTC latency / smoothness 옵션 (Chromium 클라이언트)

### 두 줄로 큰 효과
```js
pc.ontrack = (event) => {
  try { event.track.contentHint = 'motion'; } catch (e) {}   // decoder smoothness 우선
  try {
    if ('playoutDelayHint' in event.receiver) {
      event.receiver.playoutDelayHint = 0;                    // jitter buffer 최소화
    }
  } catch (e) {}
  videoEl.srcObject = event.streams[0];
  videoEl.play();
};
```

### 각 옵션 의미
- `track.contentHint = 'motion'` — H.264 decoder 가 detail 보다 fluid motion 우선. 빠른 motion 의 blocky artifact 완화. (vs `'detail'`, `'text'`)
- `receiver.playoutDelayHint = 0` — Chromium 확장 API. WebRTC default jitter buffer (100-200ms) 를 최소화. latency + "버퍼링 거리는" 감각 동시 개선. 미지원 브라우저는 silent fallback.

### 서버 측 (aiortc) 의 추가 검토 대상
- encoder `framerate` / `bit_rate` / `keyframe interval (g)` — 빠른 motion 시 압축 quality 부족이 stutter 로 보임
- 다만 upstream 코드 (`image_server.py`) 수정은 0-line change 정책 — 별도 patch 또는 monkey-patch 형태로 검토

cf. commit `bb75010` ("WebRTC playoutDelayHint=0 + contentHint=motion — 끊김 / lag 완화")

---

## 7. WebXR animation frame loop / session lifecycle

### 진입 순서 (절대 빠뜨리면 안 됨)
```js
const canvas = document.createElement('canvas');
const gl = canvas.getContext('webgl2', { xrCompatible: true, alpha: true });
await gl.makeXRCompatible();
const session = await navigator.xr.requestSession('immersive-ar', {
  optionalFeatures: ['hand-tracking', 'local-floor'],
});
session.updateRenderState({ baseLayer: new XRWebGLLayer(session, gl) });
const refSpace = await session.requestReferenceSpace('local-floor');
session.requestAnimationFrame(onFrame);

function onFrame(time, frame) {
  session.requestAnimationFrame(onFrame);   // 자기 자신 재등록 — 빠뜨리면 1 frame 만 돌고 멈춤
  const layer = session.renderState.baseLayer;
  gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
  gl.clearColor(0, 0, 0, 0);                 // pass-through 면 alpha=0
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  const pose = frame.getViewerPose(refSpace);
  if (pose) {
    for (const view of pose.views) {
      const vp = layer.getViewport(view);
      gl.viewport(vp.x, vp.y, vp.width, vp.height);
      // per-eye draw
    }
  }
}
```

### 일반 RAF vs XR-RAF
- immersive session 진입 후 `window.requestAnimationFrame` 은 **중단** 됨 (브라우저가 throttle).
- 반드시 `xrSession.requestAnimationFrame(onFrame)` 사용.
- 따라서 immersive 진입 후 일반 RAF 기반 로직 (vuer 0.0.60 R3F 의 publish loop 등) 이 동작 안 하는 게 정상 — 우리 ws bridge 우회 동기의 원인.

cf. [docs/galaxy_xr_ws_bridge_integration.md](galaxy_xr_ws_bridge_integration.md) §3 (vuer freeze 원인 분석)

---

## 8. Hand pose / head pose 좌표계 변환

### XR joint pose 의 좌표계
- `frame.getJointPose(joint, xrRefSpace).transform.matrix` — column-major 4x4
- `transform.position` / `transform.orientation` 도 사용 가능
- TeleVuer 가 기대하는 layout: `wrist[4x4]` + `positions[25 × 3]` + `orientations[25 × 9]` (3x3 column-major flatten: `[m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]]`)

### 25 joint 순서 (vuer / televuer 호환)
```
wrist,
thumb-metacarpal, thumb-phalanx-proximal, thumb-phalanx-distal, thumb-tip,
index-finger-{metacarpal, phalanx-proximal, phalanx-intermediate, phalanx-distal, tip},
middle-finger-{...}, ring-finger-{...}, pinky-finger-{...}
```

### handedness
- `inputSource.handedness` — `'left' | 'right' | 'none'`
- inputSource 마다 한 손씩 보고됨 — 양손이면 두 inputSource

cf. [webxr_to_pose.html `JOINT_NAMES`](../assets/webxr_to_pose.html), [bridge_pose_store.py](../scripts/bridge_pose_store.py)

---

## 9. 검증된 가설 vs 기각된 가설 (디버깅 히스토리)

Galaxy XR 에서 vuer 0.0.60 freeze 디버깅 과정에서 다음 가설들을 차례로 검증/기각:

| 가설 | 결과 | 측정 방법 |
|-----|------|----------|
| `chrome://flags` 의 WebXR 옵션 미설정 | 기각 — 옵션 OK, vuer freeze 별개 | 직접 flags 확인 |
| `document.visibilityState = hidden` 으로 publish loop throttle | 기각 — 계속 visible | `document.addEventListener('visibilitychange')` log |
| `xrSession.visibilityState` 가 hidden | 기각 — 계속 visible | `xrSession.visibilityState` poll |
| `setInterval` throttle | 기각 — 30/s 안정 유지 | webxr_check.html 의 1Hz counter |
| `window.requestAnimationFrame` 이 immersive 진입 후 멈춤 | **확정** — 144 frame 후 0 으로 떨어짐 | 같은 counter |
| R3F frame loop (`useFrame`) 의 XR-RAF 전환 실패 | 강한 가설 (vuer 측 코드 변경 없이 검증 어려움) | — |

### 교훈
- vuer 0.0.60 의 React 기반 publish loop 은 일반 RAF 의존 → immersive 진입 후 동작 보장 X.
- 우리 ws bridge ([bridge_pose_store.py](../scripts/bridge_pose_store.py)) 는 XR-RAF 기반 [webxr_to_pose.html](../assets/webxr_to_pose.html) 와 직접 짝지어 동작 → vuer 의존 완전 우회.

cf. [docs/week3_report.md](week3_report.md) Day 4-7

---

## 10. Python 측 monkey-patch 시 import 캐싱 함정

직접 rendering 과는 별개지만 ws bridge 통합 시 매우 자주 마주칠 패턴.

### 함정
- `from X import Y` 는 import 시점에 import 한 모듈의 local namespace 에 `Y` 가 캐시됨.
- 이후 `X.Y = OtherClass` 만 patch 하면 이미 import 한 다른 모듈의 local `Y` 는 안 바뀜.

### 우리 사례 (TeleVuer → BridgePoseStore 교체)
`tv_wrapper.py:2` 가 `from .televuer import TeleVuer` 로 직접 import. patch 대상이 한 군데가 아니라 **세 군데**:
- `televuer.televuer.TeleVuer` (원본 정의)
- `televuer.tv_wrapper.TeleVuer` (캐시된 local name)
- `televuer.TeleVuer` (패키지 `__init__.py` re-export)

### 진단 방법
- `ss -tlnH | grep -E ":(원본_port|새_port)"` — 원본 server 가 여전히 binding 하면 patch 무효

cf. commit `1429474` ("BridgePoseStore monkey-patch 무효 — 3 군데 모두 patch")

---

## 11. 외부 config 분리 (Python ↔ HTML 동시 참조)

### 패턴
- 단일 YAML ([scripts/config.yaml](../scripts/config.yaml)) 을 Python ([bridge_pose_store.py](../scripts/bridge_pose_store.py)) 이 import 시 로딩 + `/config` HTTP endpoint 로 JSON export.
- HTML ([webxr_to_pose.html](../assets/webxr_to_pose.html)) 은 페이지 로드 시 `fetch('/config')` 로 받아 적용.
- URL 쿼리 (`?webrtc_port=...`) 는 항상 override 우선.

### 장점
- 무선 환경 전환 시 `webrtc.host` 한 곳 변경으로 양쪽 일관 적용.
- 디버깅용 URL 쿼리 override 로 코드 수정 없이 빠른 실험 가능.

cf. commit `d79deac` ("scripts/config.yaml 단일 source")

---

## 12. 우리 코드의 핵심 위치 (앞으로 작업 시 참조)

| 역할 | 파일 | 핵심 함수 / 영역 |
|-----|------|----------------|
| WebXR rendering 진입 | [assets/webxr_to_pose.html](../assets/webxr_to_pose.html) | `startSession`, `onFrame` |
| Shader / draw | 같은 파일 | `_initRenderResources`, `_uploadVideoFrame`, `_drawVideoPlane` |
| WebRTC peer | 같은 파일 | `_connectWebRTC`, `pc.ontrack` |
| ws pose 전송 | 같은 파일 | `wsSend`, onFrame 의 hand/head 블록 |
| Python ws server | [scripts/bridge_pose_store.py](../scripts/bridge_pose_store.py) | `BridgePoseStore` 클래스 |
| TeleVuer monkey-patch | [scripts/run_teleop_ws.py](../scripts/run_teleop_ws.py) | `_inject_bridge_pose_store` |
| 공통 config | [scripts/config.yaml](../scripts/config.yaml) | — |
| 영상 server (upstream, 미수정) | [xr_teleoperate/teleop/teleimager/src/teleimager/image_server.py](../xr_teleoperate/teleop/teleimager/src/teleimager/image_server.py) | `WebRTC_PublisherThread`, `BGRArrayVideoStreamTrack` |
| 영상 config (upstream, 미수정) | [xr_teleoperate/teleop/teleimager/cam_config_server.yaml](../xr_teleoperate/teleop/teleimager/cam_config_server.yaml) | — |

---

## 13. 앞으로 작업 시 사전 점검 리스트

새 렌더링 기능 추가 (wrist cam PiP / gaze indicator / F/T bar / etc.) 시:

1. **per-eye view matrix 적용했는가** — 아니면 § 1 의 stereo desync 발생
2. **객체 좌표를 head-local 또는 world space 로** — view space + projection-only 조합 피하기
3. **texture / 상태 갱신은 view loop 밖** — § 3
4. **video / 외부 input 은 visible (0-size opacity 0) 로** — § 4
5. **immersive-ar 진입 시 alpha=0 clear** — § 5
6. **WebRTC 트랙은 `contentHint='motion'` + `playoutDelayHint=0`** — § 6
7. **XR-RAF 만 사용** — 일반 RAF 의존 코드 (setTimeout 기반 loop, third-party RAF 등) 의식적으로 제거 — § 7
8. **config 는 YAML 단일 source + URL 쿼리 override** — § 11
9. **upstream unitree 코드는 0-line change** — 필요 시 monkey-patch / wrapper / 별도 patch 파일로 분리. patch 시 import 캐싱 함정 (§ 10) 인지

---

## 14. 더 깊이 다루지 않은 영역 (필요 시 별도 조사)

- foveated rendering (Galaxy XR 의 eye-tracking foveation API)
- WebXR depth sensing (`depth-sensing` feature) — pass-through 영상에 occlusion 적용
- stereo camera (binocular sim camera) 의 좌/우 분리 텍스처 매핑
- WebGL2 multiview extension (`WEBGL_multiview2`) — 한 번에 양 눈 렌더링 (Galaxy XR Chrome 지원 여부 미확인)
- WebCodecs API 직접 사용 (WebRTC 우회로 더 낮은 latency)

위 항목들은 현재 plane 한 장 렌더링 범위에선 불필요. PiP / overlay 다층화 시 multiview 검토 가치 있음.
