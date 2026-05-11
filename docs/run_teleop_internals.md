# run_teleop.py 분석 — wrapper의 역할과 sim 실행 흐름

> Phase 1에서 작성한 [scripts/run_teleop.py](../scripts/run_teleop.py)가 upstream의 [xr_teleoperate/teleop/teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py)를 어떻게 wrap하는지, 그리고 IsaacSim G1+Dex3 sim 환경에서 실제로 어떤 함수들이 호출되는지 정리.

---

## 0. 한 줄 요약

`run_teleop.py`는 upstream `teleop_hand_and_arm.py`를 **그대로 실행하되 그 앞뒤에 5가지 wrapping을 끼워 넣는** 216줄짜리 부팅 스크립트다. upstream 코드는 한 줄도 수정하지 않고, **import 직전 monkey-patch 5종 + cwd 보정 + sanity check + sim 친화 default**로 우리 환경(Quest 3 / Galaxy XR + USB-only + IsaacSim 별도 docker)에 맞춤. USB-C 유선 통신은 wrapper가 직접 처리하는 게 아니라, **wrapper가 cert 우회(HTTP 모드)** + **`README.md`의 `adb reverse` 안내**로 USB-only 환경이 동작 가능하게 한 것이다.

---

## 1. wrap이 필요했던 이유 (Phase 1 발견 사항 요약)

`teleop_hand_and_arm.py`는 Unitree 로봇 (G1 / H1) + Unitree 사내 환경을 가정해서 작성됐다. 우리 환경에서 발견한 호환성 함정 5가지 → 각각이 wrapper의 한 함수로 대응됨:

| # | upstream 가정 | 우리 환경 현실 | wrapper 처방 |
|---|---|---|---|
| 1 | vuer가 항상 HTTPS+WSS 강제, cert/key를 자동 검색 | Quest 3 / Galaxy XR Chrome이 self-signed cert를 거부하거나 Wolvic 등은 cert 신뢰 UI조차 안 뜸 | `_apply_http_monkey_patch()` — vuer 인스턴스 cert/key를 None으로 강제 → plain HTTP fallback |
| 2 | `--img-server-ip` default `192.168.123.164` (Unitree 로봇 IP) | 우리는 같은 host의 다른 docker에서 sim이 도므로 `localhost` | `_ensure_sim_defaults()` — `--img-server-ip localhost` 자동 삽입 (cert 신뢰 host와 일치하도록) |
| 3 | 영상 spawn func이 ws disconnect race에 무방비 — 첫 ws가 짧게 끊기면 `AssertionError: Websocket session is missing`으로 영상 plane 영영 미등록 | Quest 3 기본 브라우저에서 자주 trigger됨 | `_patch_image_spawn_retry()` — 8개 spawn method를 try/except로 감싸 20회 retry |
| 4 | 시스템 Python 또는 ROS Humble pinocchio로 import 시도 | ROS pinocchio엔 casadi backend 없어 즉시 ImportError | `_sanity_check()` — conda env tv 활성/casadi/dex_retargeting을 boot 직후 확인, fail-fast |
| 5 | upstream을 `cd teleop && python teleop_hand_and_arm.py` 가정 — `../assets/g1/...` cwd-relative path | 우리는 `python scripts/run_teleop.py`로 다른 cwd에서 실행 → URDF load 실패 | `os.chdir(teleop_path.parent)` — runpy 호출 직전 cwd 이동 |

5번을 제외한 1~4번은 모두 monkey-patch + argparse 변환으로 처리. **upstream 코드는 1줄도 수정 안 함**.

---

## 2. wrapper가 추가/변경한 핵심 기능 5종

### 2.1 `_apply_http_monkey_patch()` ([run_teleop.py:43-56](../scripts/run_teleop.py#L43-L56))

```python
import televuer.televuer as _tv_mod
_OrigVuer = _tv_mod.Vuer

class _PlainHTTPVuer(_OrigVuer):
    def __init__(self, *args, **kwargs):
        kwargs["cert"] = None
        kwargs["key"] = None
        super().__init__(*args, **kwargs)

_tv_mod.Vuer = _PlainHTTPVuer
```

- **무엇을 함**: televuer 모듈이 import한 vuer 클래스를 cert/key=None을 강제하는 서브클래스로 교체.
- **왜 동작함**: vuer 0.0.60의 `vuer/base.py:119`에 `if not self.cert: HTTP fallback` 분기가 존재 — cert가 None이면 HTTPS 강제 부팅을 우회해 plain HTTP로 부팅.
- **언제 적용**: `wrapper_args.http`가 True (default ON), `--upstream-help`가 아닐 때만. monkey-patch는 `runpy.run_path` 호출 전에 적용해야 효과 있음 (upstream이 import할 때 이미 교체된 클래스를 보도록).

### 2.2 `_ensure_sim_defaults()` ([run_teleop.py:59-74](../scripts/run_teleop.py#L59-L74))

```python
if not any(a == "--img-server-ip" or a.startswith("--img-server-ip=") for a in passthrough):
    passthrough = ["--img-server-ip", "localhost", *passthrough]
```

- **무엇을 함**: 사용자가 `--img-server-ip`를 명시 안 하면 `localhost`를 자동 삽입.
- **왜 `localhost`**: 사용자가 Quest 3 Chrome에서 `https://localhost:60001`로 cert 신뢰한 host와 일치시키기 위함. 브라우저 cert cache는 `127.0.0.1`과 `localhost`를 다른 host로 취급. v6에서 `127.0.0.1` → `localhost` 변경 (commit `afe15c7`).
- **upstream default와의 차이**: upstream은 `192.168.123.164` (Unitree 로봇 LAN IP). sim docker가 같은 host에 떠 있으니 의미 없음.

### 2.3 `_patch_image_spawn_retry()` ([run_teleop.py:86-131](../scripts/run_teleop.py#L86-L131))

```python
def _wrap(orig_method):
    async def _retried(self, session):
        for attempt in range(20):  # 최대 ~10초
            try:
                return await orig_method(self, session)
            except AssertionError as e:
                if "Websocket session is missing" in str(e):
                    await asyncio.sleep(0.5)
                    continue
                raise
    return _retried

for name in ("main_image_monocular_webrtc", "main_image_binocular_webrtc",
             "main_image_monocular_zmq",     "main_image_binocular_zmq",
             "main_image_monocular_webrtc_ego", ...):
    if hasattr(_OrigTV, name):
        setattr(_OrigTV, name, _wrap(getattr(_OrigTV, name)))
```

- **무엇을 함**: `televuer.TeleVuer`의 8개 영상 spawn method를 ws-race에 강한 wrapper로 교체.
- **왜 필요**: vuer가 ws connect 직후 즉시 `session.upsert(WebRTCVideoPlane)`를 시도하는데, Quest 3 / Galaxy XR Chrome 측 ws가 한두 번 짧게 끊기는 패턴이 흔함 → upstream은 try/except 없어서 영상 plane이 영영 client에 등록 안 됨 (vuer scene이 빈 3D 공간으로 보임).
- **언제 적용**: default ON. `--upstream-help` 모드에선 skip. 부작용 거의 없음 — ws session이 정상이면 첫 시도에 통과.

### 2.4 `_sanity_check()` ([run_teleop.py:134-165](../scripts/run_teleop.py#L134-L165))

3단계 fail-fast 점검:

1. `os.environ.get("CONDA_DEFAULT_ENV") == "tv"` → 아니면 **exit 2** + 안내 ("conda activate tv 후 재시도")
2. `import pinocchio.casadi` → 실패 시 **exit 3** + 안내 ("ROS PYTHONPATH 의심" / "환경 재구성")
3. `import dex_retargeting` → 실패 시 **exit 4** + 안내 ("INSTALL_DEX_RETARGETING=1 bash scripts/install.sh")

- **왜 필요**: upstream은 깊은 import chain (pinocchio.casadi, dex_retargeting, matplotlib) 거치며, 어디 한 곳이 막히면 200줄 traceback이 쏟아져 사용자가 원인 파악하기 어려움. wrapper가 boot 직후 핵심 3개를 미리 시도해 즉시 명확한 에러로 abort.

### 2.5 cwd 보정 + runpy 실행 ([run_teleop.py:200-211](../scripts/run_teleop.py#L200-L211))

```python
sys.argv = [str(teleop_path), *passthrough]
os.chdir(teleop_path.parent)              # ← 핵심: cwd 이동
import runpy
runpy.run_path(str(teleop_path), run_name="__main__")
```

- **왜 cwd 이동**: `robot_arm_ik.py`가 `'../assets/g1/g1_body29_hand14.urdf'` 같은 cwd-relative 경로를 사용. upstream은 `cd teleop && python teleop_hand_and_arm.py` 호출을 가정. 우리 wrapper는 다른 cwd에서 실행되므로 명시적으로 `xr_teleoperate/teleop/`로 이동.
- **왜 `runpy.run_path`**: upstream이 `if __name__ == '__main__':` 블록에 거의 모든 부팅 로직을 둠. import 형태로는 그 블록이 안 돌아감. `runpy.run_path(path, run_name="__main__")`이 정확히 그 의미를 모사.

---

## 3. wrapper 부팅 흐름 (`main()` 단계별)

[run_teleop.py:168-212](../scripts/run_teleop.py#L168-L212):

```
┌─────────────────────────────────────────────────────────┐
│ 1. _parse_wrapper_args()                                │
│    └ wrapper 전용 옵션 분리 (--http / --no-http /        │
│      --upstream-help). 나머지는 passthrough에 보관.        │
├─────────────────────────────────────────────────────────┤
│ 2. _sanity_check()           # --upstream-help일 땐 skip │
│    ├ CONDA_DEFAULT_ENV == "tv"                          │
│    ├ import pinocchio.casadi                            │
│    └ import dex_retargeting                             │
├─────────────────────────────────────────────────────────┤
│ 3. _resolve_teleop_path()                               │
│    └ xr_teleoperate/teleop/teleop_hand_and_arm.py 위치 확인 │
├─────────────────────────────────────────────────────────┤
│ 4. sys.path.insert(0, teleop dir)                       │
│    └ upstream이 from . 없이 직접 import하는 모듈들 해결      │
├─────────────────────────────────────────────────────────┤
│ 5. _ensure_sim_defaults(passthrough)                    │
│    └ --img-server-ip localhost 자동 삽입                  │
├─────────────────────────────────────────────────────────┤
│ 6. _apply_http_monkey_patch()  # --http일 때             │
│    └ televuer.Vuer를 _PlainHTTPVuer로 교체              │
├─────────────────────────────────────────────────────────┤
│ 7. _patch_image_spawn_retry()                           │
│    └ TeleVuer.main_image_*_{webrtc,zmq}{,_ego} retry    │
├─────────────────────────────────────────────────────────┤
│ 8. ROS_DOMAIN_ID 검증 (warning만)                        │
├─────────────────────────────────────────────────────────┤
│ 9. sys.argv = [teleop_path, *passthrough]               │
│    os.chdir(teleop_path.parent)                         │
├─────────────────────────────────────────────────────────┤
│10. runpy.run_path(teleop_path, run_name="__main__")     │
│    └ upstream의 if __name__ == '__main__' 블록 실행        │
└─────────────────────────────────────────────────────────┘
```

---

## 4. sim 환경에서 실행되는 주요 함수 호출 sequence

`python scripts/run_teleop.py --ee dex3 --sim` 실행 시, 위 wrapper 단계 10번에서 `teleop_hand_and_arm.py`가 main으로 실행되며 다음 sequence가 진행된다 ([teleop_hand_and_arm.py:73-531](../xr_teleoperate/teleop/teleop_hand_and_arm.py#L73-L531)):

### 4.1 부팅 phase (`__main__` 진입 ~ "Press [r] to start" 대기)

| 순서 | 호출 | 위치 | 역할 |
|---|---|---|---|
| 1 | `argparse.parse_args()` | line 97 | --ee=dex3 --sim 등 파싱. `--img-server-ip localhost`는 wrapper가 이미 삽입 |
| 2 | **`ChannelFactoryInitialize(1, networkInterface=None)`** | line 103 | DDS domain 1 설정 (sim 모드). `--sim` flag가 분기 결정. ROS_DOMAIN_ID env와 일치해야 함 |
| 3 | `listen_keyboard(on_press=on_press, ...)` 백그라운드 thread | line 113 | `r` (start) / `s` (record toggle) / `q` (quit) 키 처리 |
| 4 | **`ImageClient(host="localhost", request_bgr=True)`** | line 119 | teleimager 클라이언트. ZMQ 55555/55556/55557 + WebRTC 60001/60002/60003에 connect |
| 5 | `img_client.get_cam_config()` | line 120 | sim 측 카메라 메타 (binocular?, image_shape, fps, enable_zmq, enable_webrtc, webrtc_port) 받아옴 |
| 6 | **`TeleVuerWrapper(use_hand_tracking=True, binocular, img_shape, display_mode="immersive", zmq, webrtc, webrtc_url=f"https://localhost:60001/offer")`** | line 125-135 | vuer 서버 부팅 (port 8012). wrapper의 `_apply_http_monkey_patch`가 cert=None 강제했으므로 plain HTTP. multiprocessing.Process로 분리됨 |
| 7 | `MotionSwitcher().Enter_Debug_Mode()` | line 142-144 | Unitree G1 sport mode 끄기 (debug mode 진입). sim은 ack만 보냄 |
| 8 | **`G1_29_ArmIK()`** | line 148 | Pinocchio + CasADi 기반 dual-arm IK 솔버 인스턴스. 첫 호출 시 모델 캐시 (`g1_29_model_cache.pkl`) 생성/로드 — cwd가 `teleop/`여야 정상 (wrapper가 chdir 함) |
| 9 | **`G1_29_ArmController(motion_mode=False, simulation_mode=True)`** | line 149 | DDS publisher to `rt/lowcmd` + subscriber from `rt/lowstate`. sim mode면 CRC 무시 |
| 10 | **`Dex3_1_Controller(left_hand_pos_array, right_hand_pos_array, dual_hand_data_lock, ...)`** | line 168 | Dex3 hand multiprocessing.Process 시작. `rt/dex3/{left,right}/{state,cmd}` DDS pub/sub. dex_retargeting (HandRetargeting class)을 내부에서 사용 |
| 11 | `ChannelPublisher("rt/reset_pose/cmd", String_)` | line 228-229 | sim 전용 — scene reset 명령 publisher |
| 12 | `start_sim_state_subscribe()` | line 231 | sim 전용 — `rt/sim_state` (JSON) subscriber. 녹화 모드에서 사용 |
| 13 | "Press [r] to start" 출력 + START 키 대기 (`while not START and not STOP`) | line 251-255 | 대기 동안 head_img를 polling해 vuer로 push (display_mode != pass-through 일 때) |

### 4.2 메인 루프 phase (사용자가 `r` 누른 이후 ~ `q` 또는 KeyboardInterrupt까지)

`arm_ctrl.speed_gradual_max()` ([line 258](../xr_teleoperate/teleop/teleop_hand_and_arm.py#L258))로 5초간 속도 ramp-up 후 메인 루프 진입. 매 iteration (`1/args.frequency` = 1/30s = 33ms 주기):

```
┌─ 루프 1회 (≈ 33 ms) ────────────────────────────────────┐
│                                                          │
│  [영상]                                                  │
│    img_client.get_head_frame()         ← ZMQ 55555      │
│    img_client.get_left_wrist_frame()   ← ZMQ 55556      │
│    img_client.get_right_wrist_frame()  ← ZMQ 55557      │
│    tv_wrapper.render_to_xr(head_img)   → vuer push      │
│    (display_mode='immersive'이고 head 카메라가 webrtc면     │
│     render_to_xr는 no-op — vuer 측에서 webrtc로 직접 받음)  │
│                                                          │
│  [XR 입력]                                               │
│    tele_data = tv_wrapper.get_tele_data()                │
│      ↳ TeleData {                                        │
│          left_wrist_pose:  (4,4) SE3                    │
│          right_wrist_pose: (4,4) SE3                    │
│          left_hand_pos:    (25,3) joints positions      │
│          right_hand_pos:   (25,3) joints positions      │
│          left_hand_pinchValue, ... (controller 모드 시)   │
│        }                                                 │
│                                                          │
│  [hand pose → Dex3 retargeting 입력]                     │
│    left_hand_pos_array[:]  = tele_data.left_hand_pos.flatten()  │
│    right_hand_pos_array[:] = tele_data.right_hand_pos.flatten() │
│    └ Dex3_1_Controller가 자식 프로세스에서 polling 후         │
│      retargeting → DDS rt/dex3/{left,right}/cmd publish      │
│                                                          │
│  [현재 robot state 읽기]                                  │
│    current_lr_arm_q  = arm_ctrl.get_current_dual_arm_q()  │
│    current_lr_arm_dq = arm_ctrl.get_current_dual_arm_dq() │
│      ↳ rt/lowstate에서 motor[arm indices] 추출            │
│                                                          │
│  [arm IK 풀이]                                            │
│    sol_q, sol_tauff = arm_ik.solve_ik(                   │
│        tele_data.left_wrist_pose,                        │
│        tele_data.right_wrist_pose,                       │
│        current_lr_arm_q, current_lr_arm_dq)              │
│      ↳ Pinocchio CasADi IPOPT 솔버.                        │
│        cost = ‖FK(q)_left  − target_left ‖²              │
│             + ‖FK(q)_right − target_right‖²              │
│             + smooth_cost + joint_limit_cost              │
│                                                          │
│  [arm command publish]                                   │
│    arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)              │
│      ↳ rt/lowcmd에 motor_cmd[arm indices] 채워서 publish    │
│        (kp/kd 미리 설정됨, q=sol_q, tau=sol_tauff)            │
│                                                          │
│  [녹화 (--record일 때만)]                                  │
│    recorder.add_item(colors, depths, states, actions)    │
│                                                          │
│  [주기 보정]                                              │
│    time.sleep(max(0, 1/args.frequency - elapsed))         │
└──────────────────────────────────────────────────────────┘
```

### 4.3 종료 phase (KeyboardInterrupt 또는 STOP=True)

[finally 블록 line 486-531](../xr_teleoperate/teleop/teleop_hand_and_arm.py#L486-L531)에서 순차 정리:

| 순서 | 호출 | 효과 |
|---|---|---|
| 1 | `arm_ctrl.ctrl_dual_arm_go_home()` | dual-arm을 home pose로 천천히 이동 |
| 2 | `stop_listening()` + `listen_keyboard_thread.join()` | 키 listener 종료 |
| 3 | `img_client.close()` | ZMQ socket 정리 |
| 4 | `tv_wrapper.close()` | vuer multiprocessing.Process terminate |
| 5 | `sim_state_subscriber.stop_subscribe()` | sim 전용 subscriber 정리 |
| 6 | `recorder.close()` | 녹화 데이터 flush (--record일 때만) |

---

## 5. USB-C 유선 통신은 누가 책임지나?

사용자 질문에서 "유선으로 vr<->pc 통신이 가능하도록 한 부분"이 가장 큰 변경점이라고 표현했는데, 정확히는 **wrapper 자체는 USB 통신을 처리하지 않는다**. 책임 분담은 다음과 같다:

| Layer | 위치 | 역할 |
|---|---|---|
| **USB 데이터 채널** | 외부 명령 `adb reverse tcp:8012 tcp:8012` 등 | Android의 ADB UsbFfs 채널을 통해 헤드셋 → PC localhost로 TCP 포워딩. `README.md` Step A/G에서 안내 |
| **vuer 서버 부팅 (HTTP)** | `_apply_http_monkey_patch()` | self-signed cert 신뢰 단계 우회 — Galaxy XR Chrome / Quest 3 기본 브라우저가 cert를 안 받아도 동작 |
| **vuer client 영상 endpoint host 일치** | `_ensure_sim_defaults()` (`localhost` 강제) | webrtc_url이 `https://localhost:60001/offer`로 만들어져 cert 신뢰 host와 일치 |
| **ws race recovery** | `_patch_image_spawn_retry()` | 헤드셋 측 첫 ws가 짧게 끊겨도 영상 plane 등록 retry |
| **연결 진단** | `scripts/diagnose.sh` | adb / cert / port LISTEN / HTTPS handshake 5단계 점검 |

즉 USB-only 환경에서 **연결을 가능하게 만들어준 것**은 위 5계층의 협업이며, run_teleop.py wrapper는 이 중 **vuer 부팅 단계에서 cert를 우회하고 영상 endpoint를 재배선**하는 부분을 담당한다. ADB 자체는 OS-level utility로, wrapper 외부에서 별도 명령으로 매번 설정.

---

## 6. 주요 함수 호출 그래프 (sim 모드 한눈에 보기)

```
$ conda activate tv
$ source scripts/dds_env.sh
$ python scripts/run_teleop.py --ee dex3 --sim
        │
        ▼
   run_teleop.main()
        │
        ├─ _parse_wrapper_args()          # --http default, passthrough 분리
        ├─ _sanity_check()                # conda env tv / pinocchio.casadi / dex_retargeting
        ├─ _resolve_teleop_path()         # teleop_hand_and_arm.py 위치
        ├─ _ensure_sim_defaults()         # --img-server-ip localhost 삽입
        ├─ _apply_http_monkey_patch()     # televuer.Vuer → _PlainHTTPVuer
        ├─ _patch_image_spawn_retry()     # TeleVuer.main_image_*_{webrtc,zmq}{,_ego} 8개 wrap
        ├─ os.chdir(teleop dir)           # URDF cwd-relative 경로 보정
        └─ runpy.run_path(teleop_hand_and_arm.py, run_name='__main__')
                │
                ▼
        teleop_hand_and_arm.py (__main__ 블록)
                │
        ┌── 부팅 ───────────────────────────────────────┐
        │                                                │
        │   ChannelFactoryInitialize(1, ...)        # DDS domain 1
        │   listen_keyboard(...)                     # 백그라운드 키 listener
        │   ImageClient(host="localhost", ...)       # ZMQ 55555-7
        │   img_client.get_cam_config()              # head/wrist 메타
        │   TeleVuerWrapper(...)                     # vuer 부팅 (HTTP, port 8012)
        │     └─ multiprocessing.Process(_vuer_run)
        │   MotionSwitcher().Enter_Debug_Mode()      # G1 sport mode off
        │   G1_29_ArmIK()                            # Pinocchio + CasADi IPOPT
        │   G1_29_ArmController(simulation_mode=True)# rt/lowcmd pub, rt/lowstate sub
        │   Dex3_1_Controller(...)                   # rt/dex3/{l,r}/cmd pub, retargeting Process
        │   ChannelPublisher("rt/reset_pose/cmd", ...) # sim 전용
        │   start_sim_state_subscribe()              # rt/sim_state JSON
        │                                                │
        └────────────────────────────────────────────────┘
                │
                ▼  사용자가 'r' 키 → START=True
        arm_ctrl.speed_gradual_max(t=5.0)   # 5초 ramp-up
                │
                ▼
        ┌── 메인 루프 (33ms 주기) ───────────────────────┐
        │                                                │
        │   img_client.get_head_frame()                  # ZMQ → bgr/depth
        │   tv_wrapper.render_to_xr(head_img)            # vuer 영상 push
        │   tele_data = tv_wrapper.get_tele_data()       # head/wrist/hand pose
        │   left_hand_pos_array[:] = tele_data.left_hand_pos.flatten()
        │   right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()
        │     └─ Dex3_1_Controller 자식 프로세스가 polling 후
        │        retargeting → DDS rt/dex3/{l,r}/cmd publish
        │   current_lr_arm_q  = arm_ctrl.get_current_dual_arm_q()
        │   current_lr_arm_dq = arm_ctrl.get_current_dual_arm_dq()
        │   sol_q, sol_tauff = arm_ik.solve_ik(
        │       tele_data.left_wrist_pose,
        │       tele_data.right_wrist_pose,
        │       current_lr_arm_q, current_lr_arm_dq)     # CasADi IPOPT
        │   arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)     # DDS rt/lowcmd publish
        │   time.sleep(33ms - elapsed)
        │                                                │
        └────────────────────────────────────────────────┘
                │
                ▼  'q' 키 또는 Ctrl+C
        finally 블록
                ├─ arm_ctrl.ctrl_dual_arm_go_home()
                ├─ stop_listening()
                ├─ img_client.close()
                ├─ tv_wrapper.close()
                ├─ sim_state_subscriber.stop_subscribe()
                └─ exit(0)
```

---

## 7. 정리

- **wrapper는 약 70 줄 분량의 monkey-patch 5종 + cwd 보정이 본질**. upstream 코드 무수정 원칙 유지.
- **USB-only 환경 지원은 wrapper 단독이 아니라 `adb reverse` (외부) + cert 우회 (HTTP 모드) + endpoint host 일치 (`localhost`) + ws retry 4계층의 협업**.
- sim 환경 메인 루프의 핵심 4 함수: **`tv_wrapper.get_tele_data()` → `arm_ik.solve_ik()` → `arm_ctrl.ctrl_dual_arm()` + `Dex3_1_Controller` retargeting Process**.
- DDS topic 5개 (`rt/lowcmd`, `rt/lowstate`, `rt/dex3/{l,r}/{cmd,state}`, `rt/sim_state`, `rt/reset_pose/cmd`)와 ZMQ 3 port (55555-7)가 우리 sim docker (`unitree_sim_isaaclab`)와의 인터페이스. **Phase 2에서 UR10e+DG-5F sim도 이 인터페이스를 그대로 따르면 wrapper는 거의 변경 없이 동작 가능** — `--arm`, `--ee` 분기와 IK / hand controller 클래스만 추가하면 됨.

---

## 참조

- [scripts/run_teleop.py](../scripts/run_teleop.py) — wrapper 본체 (216 줄)
- [README.md](../README.md) — Step A-H 환경/실행 가이드
- [xr_teleoperate/teleop/teleop_hand_and_arm.py](../xr_teleoperate/teleop/teleop_hand_and_arm.py) — upstream 메인 진입점 (531 줄)
- [xr_teleoperate/teleop/televuer/src/televuer/televuer.py](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py) — TeleVuer 클래스 (864 줄)
- [xr_teleoperate/teleop/robot_control/robot_arm_ik.py](../xr_teleoperate/teleop/robot_control/robot_arm_ik.py) — G1_29_ArmIK 등 (1251 줄)
- [xr_teleoperate/teleop/robot_control/robot_arm.py](../xr_teleoperate/teleop/robot_control/robot_arm.py) — G1_29_ArmController 등 (1178 줄)
- [xr_teleoperate/teleop/robot_control/robot_hand_unitree.py](../xr_teleoperate/teleop/robot_control/robot_hand_unitree.py) — Dex3_1_Controller (461 줄)
- [docs/INTEGRATION_FOR_XR_TELEOPERATE.md](INTEGRATION_FOR_XR_TELEOPERATE.md) — DDS/ZMQ 사양
- [docs/xr_teleoperate_setup_issues.md](xr_teleoperate_setup_issues.md) — Phase 1에서 발견된 issue 11종
