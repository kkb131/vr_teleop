# Week 3 개발 결과 보고서 — Galaxy XR 본기 기준

**프로젝트**: xr_teleoperate 기반 Galaxy XR + UR10e + DG-5F 원격조종 시스템
**기간**: Phase 1, Week 3
**대상 헤드셋**: Samsung Galaxy XR (SM-I610, Android XR Chrome)
**목적**: Galaxy XR + IsaacSim G1+Dex3-1 + hand tracking + WebRTC 영상까지 end-to-end teleop 검증 (Gate 3)

---

## 1. 금주 목표

12주 개발 계획의 **Phase 1 - Week 3** 단계로, 다음 사항을 검증하는 것이 목표였습니다.

- 같은 host의 별도 docker container에서 돌고 있는 `unitree_sim_isaaclab` (G1+Dex3-1)에 우리 docker가 CycloneDDS로 붙는지 확인
- xr_teleoperate 업스트림의 `teleop_hand_and_arm.py`를 **Galaxy XR 본기**로 boot 해 IsaacSim 안의 G1+Dex3-1을 hand tracking으로 조종 가능한지 (**Gate 3**)
- 다른 PC에서 재현 가능하도록 `scripts/` + `assets/` 폴더 자동화
- Galaxy XR Chrome 환경에서 발견되는 호환성 이슈를 모두 처리하는 wrapper 완성

> Gate 3 통과 시 → Week 4 (UR10e URDF + IK 교체)로 Phase 2 진입
> Gate 3 실패 시 → DDS / vuer client / WebRTC 분기별 처방

본 주차 통합 환경:
- **xr_teleoperate side**: 본 docker (Ubuntu 24.04 host 위 Ubuntu 22.04 container, ROS Humble + cuMotion stack), conda env `tv`
- **sim host side**: 같은 물리 host의 별도 docker (`unitree_sim_isaaclab` + Isaac Sim 5.1.0 + Isaac Lab 0.46.6 + conda env `unitree_sim_env` Python 3.11)
- **헤드셋**: Samsung Galaxy XR 본기. USB-only(`adb reverse`) 통신, WiFi 없음 (Quest 3는 Week 2까지 sanity 용도로만 사용)
- 두 docker 모두 `--network=host` → CycloneDDS multicast 자동 동작

---

## 2. 주요 결과 및 산출물

### 2.1 핵심 결과 요약

| 검증 항목 | 결과 | 비고 |
|---|---|---|
| INTEGRATION §8.A: DDS LowState subscribe (~94 Hz) | ✅ 성공 | 93.0 Hz / 279 msgs in 3s |
| INTEGRATION §8.B: ZMQ camera frame (head/L/R) | ✅ 성공 | 3개 카메라 모두 응답 (74KB / 43KB / 43KB) |
| INTEGRATION §8.C: passive LowCmd round-trip | ✅ 성공 | 50 msgs publish, sim 콘솔 에러 없음 |
| conda env `tv` + pinocchio.casadi backend | ✅ 성공 | activate hook 으로 ROS PYTHONPATH 자동 unset |
| Galaxy XR Chrome WebXR API 자체 검증 (webxr_check.html) | ✅ 성공 | navigator.xr / immersive-vr / -ar / hand-tracking required 모두 OK, 손 2개 wrist 좌표 OK |
| **vuer 0.0.60 client publish (Galaxy XR immersive)** | ❌ **실패** | 30초간 cam=7 hand=2 → **>99% event loss** (R3F XR-RAF 전환 stall 추정) |
| 자체 ws bridge — pose-only (`test_pose_only_ws.py` + `webxr_to_pose.html`) | ✅ 성공 | head/LW/RW/LH/RH 모두 OK + msg/s ≥ 30, hand_pos 손 움직임에 따라 변동 |
| 옵션 A — BridgePoseStore + `run_teleop_ws.py` 통합 | ✅ 성공 | TeleVuer 인터페이스 100% mimick, teleop_hand_and_arm.py 변경 0줄. G1+Dex3 sync 자연스러움 |
| 옵션 B1 — WebRTC peer + WebGL plane + pass-through | ✅ 성공 | immersive-ar 진입 시 실세계 + viewer 앞 1m head_camera plane |
| `scripts/config.yaml` 단일 source (Python + HTML 양쪽 참조) | ✅ 성공 | 무선 환경 대비 host/port 한 곳에서 변경 가능 |
| **Gate 3 통과 (Galaxy XR 본기)** | ✅ **통과** | Phase 1 완료 → Week 4 진입 가능 |

**🎯 Gate 3 결과: 통과 (Galaxy XR 본기 기준)**

xr_teleoperate 업스트림 stack 그대로는 Galaxy XR Chrome 에서 vuer client publish freeze 로 동작 불가 — 자체 ws bridge + WebRTC peer 영상 통합으로 우회. **unitree 측 코드(xr_teleoperate / televuer / teleimager) 변경 0 줄**로 G1+Dex3 sim teleop end-to-end 동작 확정. **Week 4 (UR10e URDF + IK 교체)** 진입 가능.

### 2.2 산출물 목록

**신규 (다른 PC 재현용)**:
- `scripts/dds_env.sh` — `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` + `ROS_DOMAIN_ID=1`
- `scripts/test_dds_sim.py` — INTEGRATION §8 자동화 (3 단계 색상 OK/WARN/FAIL)
- `scripts/run_teleop.py` — vuer 경로 teleop_hand_and_arm.py wrapper (Week 2 v3 패턴 + 영상 spawn retry)
- `scripts/bridge_pose_store.py` — **TeleVuer interface 100% mimick + 자체 aiohttp ws server**. multiprocessing.Array shared variables + 모든 property + render_to_xr/close + Singleton
- `scripts/run_teleop_ws.py` — Galaxy XR ws bridge 통합 wrapper. TeleVuer 클래스를 3 군데(`televuer.televuer`, `televuer.tv_wrapper`, `televuer` 패키지) 동시 monkey-patch
- `scripts/test_pose_only_ws.py` — BridgePoseStore standalone 검증 (smoke/measure)
- `scripts/config.yaml` — ws port / WebRTC host&port / plane 크기·거리 단일 source
- `assets/webxr_check.html` — vuer 무관 WebXR API 자체 진단 페이지 (visibility + setInterval + RAF throttle 카운터 포함)
- `assets/webxr_to_pose.html` — XR-RAF onFrame 기반 pose ws send + WebRTC peer + WebGL video plane + pass-through (alpha=0 clear). config fetch + URL 쿼리 override 지원

**수정**:
- `scripts/environment.yml` / `scripts/install.sh` — `python -m pip` 강제, requirements.txt + vuer[all]==0.0.60 명시, INSTALL_DEX_RETARGETING opt-in
- `README.md` (root 이동) — Step H~I 신규 (DDS env / IsaacSim 통합 / Galaxy XR ws bridge 절차)
- `.gitignore` — `__pycache__/` 등 추가

**conda env `tv` activate hook** (이전 Week 3 작업 그대로):
- `…/etc/conda/activate.d/clear_pythonpath.sh` — ROS PYTHONPATH 자동 unset
- `…/etc/conda/deactivate.d/restore_pythonpath.sh` — 복원

**문서**:
- `docs/galaxy_xr_ws_bridge_integration.md` — 통합 옵션(A/B1/B2/C/D) 분석 + 우선순위 + vuer freeze 진단 trace 부록
- `docs/run_teleop_internals.md` — wrapper 내부 단계 별 사양

---

## 3. 수행 내역

### 3.1 Day 1 — DDS 통신 verification

본 docker 에서 INTEGRATION §8 의 3 가지 검증 수동 수행.

- **Docker network**: `hostname -I` 로 host 인터페이스 그대로 보임 → `--network=host` namespace 공유 확정
- **DDS env**: `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` + `ROS_DOMAIN_ID=1` (sim `ChannelFactoryInitialize(1)` 와 일치)
- **§8.A LowState subscribe**: 93 Hz / 279 msgs in 3s — sim RobotState publisher 약 94 Hz 정상
- **§8.B ZMQ camera**: head(55555) 74KB, left_wrist(55556) 43KB, right_wrist(55557) 43KB
- **§8.C passive LowCmd**: 50 회 publish, sim 콘솔 에러 없음

→ 통신 기반 검증 완료. INTEGRATION §1 host network + §2 DDS 설정 정상.

### 3.2 Day 2 — 자동화 스크립트

`scripts/dds_env.sh` + `scripts/test_dds_sim.py` (자동 진단) + `README.md` Step H 신규. `python scripts/test_dds_sim.py` 한 줄로 3/3 단계 통과 확인.

### 3.3 Day 3 — `run_teleop.py` wrapper + conda env `tv`

xr_teleoperate 업스트림 `teleop_hand_and_arm.py` 를 우리 환경에서 boot 하기 위한 wrapper:

- **cert 강제 우회**: `televuer.televuer.Vuer` 를 cert/key=None subclass 로 monkey-patch → plain HTTP
- **cwd 변경**: `robot_arm_ik.py` 의 `../assets/g1/...` cwd-relative 경로 대응
- **`--img-server-ip localhost` default 자동 삽입**: webrtc_url cert host mismatch 회피 (Week 3 v6 fix)
- **sanity check fail-fast**: conda env `tv` / `pinocchio.casadi` / `dex_retargeting` 사전 import 실패 시 즉시 abort

`pinocchio.casadi`가 ROS Humble system 패키지에 없어 conda env `tv` 도입. activate hook 으로 PYTHONPATH 자동 unset. `python scripts/run_teleop.py --ee dex3 --sim` 이 메인 루프 진입(`Press [r] to start syncing`).

이 시점까지 Quest 3 로 hand sync 정상 확인됨 (Week 2 결과 재확인, sanity 용도).

### 3.4 Day 4 — Galaxy XR 본기 첫 시도, vuer publish freeze 발견

`scripts/run_teleop.py --ee dex3 --sim` 으로 Galaxy XR Chrome 에서 `http://localhost:8012` 접속.

증상:
- vuer page 로드 OK, "socket reconnect" 버튼 동작, pass-through 버튼 표시 (화면 아래에 위치해 처음엔 못 봤음 — Enter VR 버튼은 노출 안 됨)
- pass-through 클릭 후 immersive 진입은 성공
- **pose 출력 시 head 만 OK, LW/RW/LH/RH 는 `..` (lost)**
- `--debug --measure 30` 결과: `cam=7 hand=2 errors=0` → **30 Hz × 30 s = 900 expected 대비 >99 % event loss**
- 매 시도마다 `hand_pos[0]` 이 `[-0.10, +0.07, -0.21]` 처럼 frozen, 값은 다름 (publish 가 1~2 회만 일어나고 그 뒤로 stop)

ws disconnect 메시지가 거의 없음 → server-side close 가 아닌 **client-side publish freeze**.

### 3.5 Day 5 — 가설 분류 + 자체 진단 페이지 (`webxr_check.html`)

vuer 무관 자체 WebXR 진단 페이지를 작성해 Galaxy XR Chrome 의 표준 API 상태를 분리 검증. 결과:

| 가설 | 검증 도구 | 결과 |
|---|---|---|
| Chrome flags / WebXR API 미지원 | webxr_check.html auto diagnostic | `navigator.xr` 정상, immersive-vr / -ar 둘 다 supported |
| hand-tracking 미지원 | required feature 강제 진입 | session 진입 성공, 손 2개 + wrist 좌표 정상 |
| `document.hidden` 가드 | visibility monitor 추가 | immersive 도중 `hidden=false` 유지 (가설 기각) |
| `xrSession.visibilityState` 가드 | XR session visibility 모니터 | `visible` 유지 (가설 기각) |
| setInterval throttle | 33ms setInterval 카운터 + RAF 카운터 | **setInt=30/s 정상**, raf=0/s (immersive 안 normal RAF 멈춤은 표준 동작) → setInterval throttle 가설 기각 |

추가로 vuer `client_build/assets/chunks/chunk-Dd3xtWba.js` 의 source map 을 활용해 minified `Hands` 컴포넌트 복원:

```js
function Hands({ disableLeft: o = !1, disableRight: l = !1, stream: g = !1, ... }) {
  const { sendMsg: S } = useSocket();
  const b = useXR(({ mode: Y }) => Y);   // store mode
  const D = b === "immersive-ar" || b === "immersive-vr";
  const G = useMemo(() => ({}), []);      // mutable hand pose buffer
  useFrame((_, __, V) => { if (!D) return;
                           /* getHandLandmarks → G.left/right */ });
  const J = useCallback(() => {
    D && (!g || o && l || S({ ts: Date.now(), etype: "HAND_MOVE", value: { ...G } }));
  }, [D, g, o, l, G]);
  return useInterval(J, 1e3 / a), ...;
}
```

publish 가드 `D && (!g || o && l || S(...))` 는 `stream=true`, `disableLeft=false`, `disableRight=false` 일 때 정상 호출되어야 함. `useInterval` 도 단순 `setInterval(callback, 1e3/a)` 기반(자체 구현 확인됨). 그러나 `useFrame` 은 R3F frame loop 의존.

**남은 유력 가설**: vuer 0.0.60 의 R3F `<Canvas>` 가 immersive 진입 시 `gl.xr.setSession(session)` 후 `setAnimationLoop` 을 XR-RAF 로 transition 해야 정상이지만, Galaxy XR Chrome 에서 이 transition 이 stall → `useFrame` 멈춤 → `G` 빈 채로 유지 + zustand store 갱신 stale → callback 거의 호출 안 됨. minified bundle 직접 패치 (옵션 C) 는 비용 매우 크고 vuer 업그레이드 마다 재적용 필요 → **자체 ws bridge 로 우회 결정**.

### 3.6 Day 6 — Step C: vuer 우회 ws bridge 1 차 (pose only)

`scripts/test_pose_only_ws.py` + `assets/webxr_to_pose.html` 작성.

- `xrSession.requestAnimationFrame(onFrame)` (XR-RAF) 기반 — vuer freeze 와 무관
- 매 frame `frame.getViewerPose(refSpace).transform.matrix` (head SE(3)) + 양손 25 joints `getJointPose().transform.{position,matrix}` 추출
- JSON 메시지 (`{type:"head", matrix:[16]}` / `{type:"hand", handedness, wrist:[16], positions:[25×[x,y,z]]}`) 로 `ws://localhost:8013/pose` 송신
- aiohttp ws server (`test_pose_only_ws.py`) 가 `/` HTTP 정적 서빙 + `/pose` ws receive + shared array 업데이트
- 자동 reconnect (1초 backoff)

실측: head/LW/RW/LH/RH 모두 OK, hand_pos 가 손 움직임에 따라 변동 (`[-0.03, +0.08, -0.31]` 등 HMD 상대좌표). msg/s ≥ 30 안정.

### 3.7 Day 7 — 옵션 A: BridgePoseStore + run_teleop_ws.py

ws bridge 패턴을 teleop_hand_and_arm.py 와 통합하기 위한 thin layer.

- **`scripts/bridge_pose_store.py`**: TeleVuer interface 100% mimick
  - `__init__` 시그니처 동일 (vuer 관련 인자 받지만 무시)
  - `multiprocessing.Array` shared variables (`head_pose_shared`, `left_arm_pose_shared`, `left_hand_position_shared`, `left_hand_orientation_shared`, `left_hand_pinch_shared`, ...) — TeleVuer 와 동일 layout
  - 모든 property (`head_pose`, `left_arm_pose`, `left_hand_positions`, `left_hand_orientations`, `left_hand_pinch`, controller_*)
  - `render_to_xr` (noop) / `close` (noop)
  - 자체 aiohttp ws server 자동 시작 (background thread, port 8013)
  - **Singleton 패턴** — `_inject_bridge_pose_store` 가 monkey-patch 후 TeleVuerWrapper 가 다시 instantiate 해도 같은 인스턴스 반환 (ws server 중복 시작 방지)
- **`assets/webxr_to_pose.html` 확장**: 25 joint orientation (column-major 3x3) 송신 추가. TeleVuer `extract_hand_poses` 의 `[m[0],m[1],m[2], m[4],m[5],m[6], m[8],m[9],m[10]]` layout 그대로 맞춤
- **pinch / squeeze 자동 계산**: BridgePoseStore 가 thumb-tip ↔ index/middle-tip 거리 기반 (vuer `getHandLandmarks` 와 동일 threshold 0.01 / 0.07)
- **`scripts/run_teleop_ws.py`**: `run_teleop.py` 패턴 차용 + `_inject_bridge_pose_store` 신규

### 3.8 Day 8 — monkey-patch 무효 fix

run_teleop_ws.py 1차 시도에서 BridgePoseStore 가 instantiate 안 됨 (port 8013 listen 안 함). 진단:

```
[run_teleop_ws] televuer.TeleVuer → BridgePoseStore monkey-patched   ← 출력은 나옴
Initialize Dex3_1_Controller OK!                                       ← main 루프는 진입
Press [r] to start syncing...
```
→ 그러나 8013 에 ws server 없음.

원인: Python `from X import Y` 는 import time 에 local namespace 에 `Y` 이름이 캐시되고 그 시점 원본 객체를 가리킨다. 이후 `X.Y = Other` 로 attribute 만 변경해도 **이미 import 한 곳의 local `Y` 는 안 바뀜**.

| 파일 | line | import 패턴 | 영향 |
|---|---|---|---|
| `tv_wrapper.py:2` | `from .televuer import TeleVuer` | tv_wrapper 모듈에 원본 `TeleVuer` 캐시 |
| `tv_wrapper.py:238` | `self.tvuer = TeleVuer(...)` | bare name → 캐시된 원본 호출 |
| `televuer/__init__.py:2` | `from .televuer import TeleVuer` | 패키지 namespace 에도 원본 캐시 |

처방: 3 군데 모두 patch.

```python
import televuer as _tv_pkg
import televuer.televuer as _tv_mod
import televuer.tv_wrapper as _wrapper_mod
from bridge_pose_store import BridgePoseStore
_tv_mod.TeleVuer      = BridgePoseStore
_wrapper_mod.TeleVuer = BridgePoseStore
_tv_pkg.TeleVuer      = BridgePoseStore
```

(`test_pose_only_ws.py` 가 동작했던 이유: BridgePoseStore 를 직접 호출해 monkey-patch 의존 없었음.)

수정 후 `[BridgePoseStore] ws server ready: http://localhost:8013/` 출력 확인 + Galaxy XR Chrome 접속 OK + **IsaacSim 안 G1 팔/Dex3 손가락이 hand sync 자연스럽게 따라감**. 옵션 A 완료.

### 3.9 Day 9 — 옵션 B1: WebRTC peer + WebGL plane + pass-through

영상 통합 (head_camera 만, 추후 wrist 확장):

- **WebRTC peer** (`_connectWebRTC`): `RTCPeerConnection({iceServers:[]})` + `addTransceiver('video', recvonly)` + `fetch('https://<host>:<port>/offer', POST {sdp, type})` + answer SDP `setRemoteDescription` + `pc.ontrack` 에서 `<video>.srcObject = stream` + `video.play()`. session 시작 직후 자동 connect, end 시 cleanup
- **WebGL video plane**:
  - WebGL 2 컨텍스트 `{ xrCompatible, alpha:true, premultipliedAlpha:false }`
  - vertex/fragment shader (GLSL ES 3.0), quad buffer, GL_TEXTURE_2D
  - head-locked: camera space `(0, 0, -D)` 에 plane → 양 눈에서 같은 위치 (view matrix 안 곱함)
  - `onFrame` 안 `viewerPose.views[]` 순회 → `gl.viewport(view.viewport)` + `texImage2D(video)` + `drawArrays(TRIANGLE_STRIP, 4)`
- **Pass-through**:
  - `gl.clearColor(0, 0, 0, 0)` + `clear(COLOR|DEPTH)`
  - immersive-ar 진입 시 alpha=0 background → **실세계 카메라 영상 그대로 보임** + viewer 앞 plane 에 robot head_camera 가 그려짐 → 디버깅 시 모니터/주변 직접 관찰 가능

실측: Galaxy XR Chrome 에서 Enter AR → 실세계 + viewer 앞 1m 에 G1 head_camera 영상 + 손 자유 움직임 → IsaacSim G1+Dex3 sync 자연스러움. **end-to-end 영상+pose teleop 완성**.

### 3.10 Day 10 — `scripts/` + `assets/` 재배치 + `config.yaml` 단일 source

용도별 분리:
- `scripts/` ← `setup/*.{py,sh,yml}` (12 파일)
- `assets/` ← `setup/*.html` (2 파일)
- `README.md` ← `setup/README.md` (project root 로 이동)
- 코드/문서 내부 `setup/` reference → `scripts/` 또는 `assets/`

`scripts/config.yaml` 신규 — Python (`BridgePoseStore` 가 yaml 로딩 + `/config` HTTP endpoint 로 JSON export) + HTML (`webxr_to_pose.html` 이 페이지 로드 시 `fetch('/config')` + URL 쿼리 override) 양쪽 단일 source. 무선 환경 진입 시 `webrtc.host` 한 곳만 변경 가능.

---

## 4. 이슈 및 리스크

### 4.1 발생한 이슈와 해결

| 이슈 | 원인 | 해결 | 상태 |
|---|---|---|---|
| Galaxy XR Chrome vuer client publish freeze | R3F `useFrame` 이 일반 RAF 기반, immersive 시 XR-RAF transition stall (가장 유력) | 자체 ws bridge 로 vuer client 완전 우회 (BridgePoseStore + webxr_to_pose) | ✅ |
| vuer page에 Enter VR 안 보이고 pass-through 만 노출 | vuer XRButton 위치가 화면 아래 — 디바이스/뷰포트 차이 | 사용자 시야 스크롤 후 발견. vuer freeze 와는 별개 | ✅ |
| document.hidden / xrSession.visibilityState 가설 기각 | 둘 다 immersive 도중 visible 유지 | 가설 폐기 + setInterval / RAF 카운터로 다음 진단 | ✅ |
| setInterval throttle 가설 기각 | setInt=30/s 정상 fire | useFrame / R3F frame loop 가설로 전환 | ✅ |
| BridgePoseStore monkey-patch 무효 (run_teleop_ws.py 1차) | `from .televuer import TeleVuer` 의 import-time local name 캐시 | `televuer.televuer` + `televuer.tv_wrapper` + `televuer` 패키지 3 군데 동시 patch | ✅ |
| ROS Humble system pinocchio 에 casadi backend 없음 | apt pinocchio 빌드에 casadi 옵션 없음 | conda env `tv` + activate hook PYTHONPATH unset | ✅ |
| `which pip` → `/usr/bin/pip` (conda activate 후에도) | PATH 우선순위 / 일부 base image alias | install.sh 모든 pip 호출을 `python -m pip` 로 강제 | ✅ |
| `dex_retargeting` 미설치 | Week 3 시점부터 G1+Dex3 hand control 필수 | `INSTALL_DEX_RETARGETING=1` 활성 + sanity check fail-fast | ✅ |
| WebRTC `/offer` cert 신뢰 미설정 | self-signed cert + Galaxy XR Chrome strict | 사용자가 `https://localhost:60001` 한 번 직접 방문해 cert 신뢰. webxr_to_pose 가 실패 시 안내 출력 | ✅ |
| `webxr_to_pose.html` 의 WebRTC port 하드코딩 | 무선 환경 / 다른 카메라 추가 시 부담 | `scripts/config.yaml` + URL 쿼리 override 로 분리 | ✅ |

### 4.2 잠재 리스크

**리스크 1: vuer 0.0.60 의존성 일부 잔존**
- 본 우회는 vuer client publish 경로를 안 쓰지만 `dex_retargeting` 등 다른 패키지는 여전히 의존. vuer 업그레이드 시 freeze 가 자연 해결될 가능성도 있어 정기 회귀 테스트 필요
- **대응**: 새 vuer 릴리스 마다 `scripts/run_teleop.py` (원본 경로) 로 빠르게 sanity 비교

**리스크 2: WebRTC self-signed cert 신뢰 절차**
- Galaxy XR Chrome 에서 `https://localhost:60001` 등 endpoint 별로 self-signed cert 한 번 신뢰 필요. 새 setup 마다 사용자 부담
- **대응**: `assets/webxr_to_pose.html` 의 Live log 가 fetch 실패 시 정확한 신뢰 URL 안내 출력. README Step 에 절차 명시

**리스크 3: 무선 환경 (조종 PC ↔ 로봇 PC WiFi) 진입 시 라우팅**
- 현재는 same-host docker → `localhost` 동작. 무선 분리 시 헤드셋이 직접 로봇 PC IP 로 WebRTC peer 협상하려면 cert SAN 갱신 + NAT/라우팅 검토 필요
- **대응**: docs/galaxy_xr_ws_bridge_integration.md §2 옵션 B2 (PC server image relay) 미리 정리됨 — WiFi 진입 시 그 경로 점진 전환 가능

**리스크 4: WebGL video texture 성능 (Galaxy XR 미정량)**
- 헤드셋 측 GPU 부담. 현재 head_camera 1 개 plane 은 충분히 동작했으나 wrist 2 개 추가 시 성능 영향 미지수
- **대응**: Week 9 멀티카메라 통합 시 `gl.texImage2D` 대신 `EXT_video_texture` 또는 OffscreenCanvas 활용 검토

**리스크 5: BridgePoseStore Singleton + monkey-patch 의 side effect**
- TeleVuer 클래스를 3 모듈에 patch 한 상태로 teleop_hand_and_arm.py 가 import. 만약 사용자 코드가 별도 process 에서 TeleVuer 를 import 하면 patch 영향 안 받음 → 의도된 동작이지만 디버깅 시 혼란 가능
- **대응**: `[run_teleop_ws]` 부팅 메시지에 patch 적용 명시 + Singleton 인스턴스 정보 출력

### 4.3 다음 주차로 이월

- **Week 4** (Phase 2 시작): UR10e URDF 준비 + `robot_arm_ik.py` 를 UR10e 용으로 수정 (G1_29_ArmIK → UR10e_ArmIK), dual-arm → single-arm 구조 단순화
- **Week 5**: DG-5F dex-retargeting config (`configs/tesollo_dg5f.yml`) 작성
- **Week 6**: IsaacSim 환경을 UR10e+DG-5F 로 전환 → Gate 4
- **Week 7-8**: 실로봇 통합 + 무선 환경 옵션 B2 (PC server image relay) 적용
- **Week 9**: wrist 카메라 (60002 / 60003) picture-in-picture 추가

---

## 5. 작업 상세 자료 및 주요 코드

### 5.1 자체 ws bridge 데이터 흐름

```
Galaxy XR Chrome (HMD)                       PC docker (조종)
─────────────────────                         ──────────────────
webxr_to_pose.html                            run_teleop_ws.py
  ├─ XR-RAF onFrame loop                        ├─ sanity check
  │    ├─ head pose (4x4)                       ├─ _inject_bridge_pose_store
  │    └─ 양손 25 joint position/orientation    │    └─ TeleVuer = BridgePoseStore × 3 모듈
  │       ↓ JSON over ws://:8013/pose           └─ runpy teleop_hand_and_arm.py
  └─ WebRTC peer (head_camera)                       └─ TeleVuerWrapper
       fetch https://:60001/offer (SDP)              │    └─ self.tvuer = BridgePoseStore()
       ↓ video track                                  │         ├─ aiohttp ws server :8013
       texImage2D → WebGL plane                       │         │    /  GET → webxr_to_pose.html
       (head-locked, viewer 앞 1m)                   │         │    /pose WS  ← JSON
       + pass-through (alpha=0 clear)                │         │    /config GET → config.yaml JSON
                                                     │         └─ shared array (head_pose_shared 등)
                                                     └─ IK / DDS publisher → IsaacSim G1+Dex3
```

### 5.2 BridgePoseStore TeleVuer mimick 변수명

`televuer/televuer.py:138-173` 과 100% 일치:

| TeleVuer 변수 (= BridgePoseStore) | 크기 | 형식 |
|---|---|---|
| `head_pose_shared` | 16 float | 4×4 col-major SE(3) |
| `left_arm_pose_shared` / `right_arm_pose_shared` | 16 float each | wrist 4×4 |
| `left_hand_position_shared` / `right_hand_position_shared` | 25×3 float | joint position |
| `left_hand_orientation_shared` / `right_hand_orientation_shared` | 25×9 float | 3×3 col-major |
| `*_hand_pinch_shared` / `*_hand_pinchValue_shared` | bool / float | thumb-tip ↔ index-tip 거리 기반 |
| `*_hand_squeeze_shared` / `*_hand_squeezeValue_shared` | bool / float | thumb-tip ↔ middle-tip 거리 기반 |

### 5.3 WebRTC peer + WebGL plane 핵심 (`webxr_to_pose.html`)

```js
// WebRTC offer/answer
pc = new RTCPeerConnection({ iceServers: [] });
pc.addTransceiver('video', { direction: 'recvonly' });
pc.ontrack = ev => { videoEl.srcObject = ev.streams[0]; videoEl.play(); };
const offer = await pc.createOffer();
await pc.setLocalDescription(offer);
const resp = await fetch(`https://${WEBRTC_HOST}:${WEBRTC_PORT}/offer`,
  { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ sdp: pc.localDescription.sdp, type: 'offer' }) });
await pc.setRemoteDescription(await resp.json());

// onFrame: pass-through + head-locked plane
gl.clearColor(0, 0, 0, 0);
gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
for (const view of viewerPose.views) {
  gl.viewport(...layer.getViewport(view));
  gl.useProgram(shaderProgram);
  gl.uniformMatrix4fv(uniformProj, false, view.projectionMatrix);  // view matrix 안 곱함
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, videoEl);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}
```

### 5.4 매 작업 시작 시 표준 절차 (Galaxy XR 본기)

```bash
# 1. sim host docker 에서 sim_main.py 시작 (사용자 측, INTEGRATION §6)

# 2. xr_teleoperate side docker (본 docker)
conda activate tv
source scripts/dds_env.sh
adb devices                                # Galaxy XR USB 연결 확인
adb reverse tcp:8013  tcp:8013             # BridgePoseStore ws
adb reverse tcp:60001 tcp:60001            # head_camera WebRTC
# (선택) wrist 영상까지:
# adb reverse tcp:60002 tcp:60002 / 60003

# 3. (선택) 통신 점검
python scripts/test_dds_sim.py

# 4. teleop wrapper 시작
python scripts/run_teleop_ws.py --ee dex3 --sim

# 5. Galaxy XR Chrome
#    - 첫 사용 시: https://localhost:60001 한 번 방문 → cert 신뢰
#    - http://localhost:8013/ → 'Enter AR' (pass-through) → 손 → r 키
```

---

## 6. Week 3 결론

**Gate 3 통과 (Galaxy XR 본기 기준)**. xr_teleoperate 업스트림 stack 자체는 Galaxy XR Chrome 에서 vuer client publish freeze 로 그대로 동작 불가했으나, 자체 ws bridge + WebRTC peer 영상 통합으로 우회 완료. 검증된 핵심 사항:

- Galaxy XR Chrome WebXR API 는 표준 준수 정상 — 문제는 vuer 0.0.60 의 R3F 통합 layer
- BridgePoseStore 가 TeleVuer interface 100% mimick 이라 `teleop_hand_and_arm.py` / `TeleVuerWrapper` 코드 변경 0 줄
- `run_teleop_ws.py` 의 3 군데 monkey-patch 로 import-time local name 캐시까지 정확히 우회
- WebRTC peer + WebGL head-locked plane + immersive-ar pass-through (alpha=0) 로 헤드셋 안에서 실세계 + robot view + 손 동시 관찰
- `scripts/config.yaml` 단일 source 로 무선 환경 전환 시 host/port 한 곳만 변경 가능

다른 PC 재현은 `README.md` Step A~I 를 따라 30 분~1 시간 내 가능. **다음 주 (Week 4) 부터 Phase 2 — UR10e + DG-5F 교체 진입**.

---

*Week 3 보고서 끝.*
