"""BridgePoseStore — TeleVuer 인터페이스 100% mimick + 자체 ws server.

Galaxy XR Chrome에서 vuer 0.0.60 client React가 immersive 진입 후 publish freeze
(R3F frame loop XR-RAF 전환 실패 가설)되는 문제를 우회하기 위한 layer.

설계:
- TeleVuer 와 동일한 __init__ 시그니처 (vuer 관련 인자는 받기만 하고 무시)
- TeleVuer 와 동일한 shared variable 이름/형식 (`head_pose_shared` 등 multiprocessing.Array)
- TeleVuer 와 동일한 property API (head_pose, left_arm_pose, left_hand_positions, ...)
- TeleVuer 와 동일한 method (render_to_xr, close)
- 차이: vuer.Vuer 대신 자체 aiohttp ws server (port 8013 default)를 별도 thread에서 실행
- webxr_to_pose.html 이 매 frame head/hand JSON 송신 → ws handler가 shared array 직접 update

Singleton 패턴: teleop_hand_and_arm.py 가 TeleVuer를 monkey-patch한 BridgePoseStore
로 여러 번 instantiate할 수도 있는데 (재시작 등), 같은 인스턴스 반환해 ws server
이중 시작 (port 충돌) 방지.

Usage:
  # 단독 테스트:
  store = BridgePoseStore(use_hand_tracking=True, ...)
  # 그 후 head_pose, left_arm_pose 등 access

  # teleop_hand_and_arm.py 통합 (run_teleop_ws.py wrapper):
  import televuer.televuer as _tv_mod
  from setup.bridge_pose_store import BridgePoseStore
  _tv_mod.TeleVuer = BridgePoseStore
  # 그 후 teleop_hand_and_arm.py 가 TeleVuerWrapper(...) 호출하면
  # 내부의 TeleVuer(...) 호출이 BridgePoseStore(...) 로 redirect 됨
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from multiprocessing import Array, Value
from pathlib import Path
from typing import Literal, Optional

import numpy as np

try:
    from aiohttp import web, WSMsgType
except ImportError as e:
    raise ImportError("aiohttp 필요. conda activate tv 또는 pip install aiohttp") from e

try:
    import yaml
except ImportError as e:
    raise ImportError("PyYAML 필요. pip install pyyaml") from e


# ── config 로딩 (scripts/config.yaml) ──────────────────────────────────
# Python 측 + HTML 측 (fetch '/config') 모두 같은 yaml 파일 한 곳을 참조.
# 환경변수 XR_BRIDGE_CONFIG 로 다른 경로 지정 가능.
_CONFIG_PATH = Path(os.environ.get(
    "XR_BRIDGE_CONFIG",
    str(Path(__file__).resolve().parent / "config.yaml")
))

_DEFAULT_CONFIG = {
    "ws": {"port": 8013},
    "webrtc": {
        "enabled": True,
        "host": "localhost",
        "ports": {"head": 60001, "left_wrist": 60002, "right_wrist": 60003},
    },
    "render": {
        "plane_distance_m": 1.0,
        "plane_width_m": 1.6,
        "plane_height_m": 0.9,
    },
}


def load_config() -> dict:
    """yaml 로딩 + missing key 는 default 로 채움. 파일 없으면 default 그대로."""
    if not _CONFIG_PATH.exists():
        print(f"[bridge_pose_store] config {_CONFIG_PATH} 없음 — default 사용")
        return _DEFAULT_CONFIG.copy()
    try:
        with _CONFIG_PATH.open() as f:
            loaded = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[bridge_pose_store] config 로딩 실패: {e} — default 사용")
        return _DEFAULT_CONFIG.copy()
    # shallow merge — missing top-level 또는 nested key 는 default 로 보강
    merged = {}
    for k, dv in _DEFAULT_CONFIG.items():
        v = loaded.get(k, dv)
        if isinstance(dv, dict) and isinstance(v, dict):
            merged[k] = {**dv, **v}
            # one more level for webrtc.ports
            if k == "webrtc" and "ports" in v and isinstance(v["ports"], dict):
                merged[k]["ports"] = {**dv["ports"], **v["ports"]}
        else:
            merged[k] = v
    return merged


CONFIG = load_config()


# WebXR 25-joint 이름 순서. webxr_to_pose.html 의 JOINT_NAMES 와 1:1 일치.
JOINT_NAMES = [
    'wrist',
    'thumb-metacarpal', 'thumb-phalanx-proximal', 'thumb-phalanx-distal', 'thumb-tip',
    'index-finger-metacarpal', 'index-finger-phalanx-proximal',
    'index-finger-phalanx-intermediate', 'index-finger-phalanx-distal', 'index-finger-tip',
    'middle-finger-metacarpal', 'middle-finger-phalanx-proximal',
    'middle-finger-phalanx-intermediate', 'middle-finger-phalanx-distal', 'middle-finger-tip',
    'ring-finger-metacarpal', 'ring-finger-phalanx-proximal',
    'ring-finger-phalanx-intermediate', 'ring-finger-phalanx-distal', 'ring-finger-tip',
    'pinky-finger-metacarpal', 'pinky-finger-phalanx-proximal',
    'pinky-finger-phalanx-intermediate', 'pinky-finger-phalanx-distal', 'pinky-finger-tip',
]
THUMB_TIP_IDX = 4
INDEX_TIP_IDX = 9
MIDDLE_TIP_IDX = 14

# televuer/dist/index.js 의 getHandLandmarks threshold 와 동일
PINCH_THRESHOLD = 0.01    # m, thumb-tip ↔ index-tip
SQUEEZE_THRESHOLD = 0.07  # m, thumb-tip ↔ middle-tip


class BridgePoseStore:
    """TeleVuer interface 100% mimick + 자체 ws bridge.

    Singleton: 같은 process 안에서 두 번째 호출 시 기존 인스턴스 반환.
    """

    _instance: Optional["BridgePoseStore"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        use_hand_tracking: bool,
        binocular: bool = True,
        img_shape: Optional[tuple] = None,
        display_fps: float = 30.0,
        display_mode: Literal["immersive", "pass-through", "ego"] = "immersive",
        zmq: bool = False,
        webrtc: bool = False,
        webrtc_url: Optional[str] = None,
        cert_file: Optional[str] = None,
        key_file: Optional[str] = None,
    ):
        """TeleVuer.__init__ 시그니처 그대로. vuer/webrtc/cert 인자는 받지만 무시.

        :param use_hand_tracking: hand 인지 controller 인지. TeleVuer 와 동일하게
            shared variable 셋업이 갈라짐.
        :param binocular / img_shape / display_fps / display_mode / zmq / webrtc /
            webrtc_url / cert_file / key_file: 인터페이스 호환용. BridgePoseStore
            는 자체 ws server 라 사용하지 않음.

        환경변수 `XR_BRIDGE_PORT` (default 8013) 로 ws server port 변경 가능.
        """
        # Singleton: 두 번째 호출이면 이미 init 됐으므로 skip
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.use_hand_tracking = use_hand_tracking
        self.binocular = binocular
        self.display_fps = display_fps
        self.display_mode = display_mode
        # vuer/webrtc 관련 인자는 그대로 보관 (다른 코드가 read 할 수도 있음)
        self.zmq = zmq
        self.webrtc = webrtc
        self.webrtc_url = webrtc_url

        # img_shape 호환용 (TeleVuer 가 img_shape 없으면 raise — 우리도 동일하게)
        if img_shape is None:
            img_shape = (480, 640)
        self.img_shape = (img_shape[0], img_shape[1], 3)
        self.img_height = self.img_shape[0]
        self.img_width = self.img_shape[1] // 2 if binocular else self.img_shape[1]
        self.aspect_ratio = self.img_width / self.img_height

        # ── shared variables — TeleVuer 와 100% 동일 layout ─────────────
        self.head_pose_shared = Array('d', 16, lock=True)
        self.left_arm_pose_shared = Array('d', 16, lock=True)
        self.right_arm_pose_shared = Array('d', 16, lock=True)

        if self.use_hand_tracking:
            self.left_hand_position_shared = Array('d', 75, lock=True)
            self.right_hand_position_shared = Array('d', 75, lock=True)
            self.left_hand_orientation_shared = Array('d', 25 * 9, lock=True)
            self.right_hand_orientation_shared = Array('d', 25 * 9, lock=True)
            self.left_hand_pinch_shared = Value('b', False, lock=True)
            self.left_hand_pinchValue_shared = Value('d', 0.0, lock=True)
            self.left_hand_squeeze_shared = Value('b', False, lock=True)
            self.left_hand_squeezeValue_shared = Value('d', 0.0, lock=True)
            self.right_hand_pinch_shared = Value('b', False, lock=True)
            self.right_hand_pinchValue_shared = Value('d', 0.0, lock=True)
            self.right_hand_squeeze_shared = Value('b', False, lock=True)
            self.right_hand_squeezeValue_shared = Value('d', 0.0, lock=True)
        else:
            # controller 모드 — TeleVuer 와 동일하게 controller state 변수 셋업
            self.left_ctrl_trigger_shared = Value('b', False, lock=True)
            self.left_ctrl_triggerValue_shared = Value('d', 0.0, lock=True)
            self.left_ctrl_squeeze_shared = Value('b', False, lock=True)
            self.left_ctrl_squeezeValue_shared = Value('d', 0.0, lock=True)
            self.left_ctrl_thumbstick_shared = Value('b', False, lock=True)
            self.left_ctrl_thumbstickValue_shared = Array('d', 2, lock=True)
            self.left_ctrl_aButton_shared = Value('b', False, lock=True)
            self.left_ctrl_bButton_shared = Value('b', False, lock=True)
            self.right_ctrl_trigger_shared = Value('b', False, lock=True)
            self.right_ctrl_triggerValue_shared = Value('d', 0.0, lock=True)
            self.right_ctrl_squeeze_shared = Value('b', False, lock=True)
            self.right_ctrl_squeezeValue_shared = Value('d', 0.0, lock=True)
            self.right_ctrl_thumbstick_shared = Value('b', False, lock=True)
            self.right_ctrl_thumbstickValue_shared = Array('d', 2, lock=True)
            self.right_ctrl_aButton_shared = Value('b', False, lock=True)
            self.right_ctrl_bButton_shared = Value('b', False, lock=True)

        # ws message stats (debug)
        self._msg_count = 0
        self._last_msg_time = 0.0
        self._stats_lock = threading.Lock()

        # ── start ws server in background thread ────────────────────────
        # port 결정 우선순위: XR_BRIDGE_PORT env > config.yaml ws.port > 8013 default
        self._port = int(os.environ.get("XR_BRIDGE_PORT", str(CONFIG["ws"]["port"])))
        self._server_ready = threading.Event()
        self._server_thread = threading.Thread(
            target=self._server_thread_main, name="BridgePoseStoreWS", daemon=True
        )
        self._server_thread.start()
        if not self._server_ready.wait(timeout=5.0):
            print(f"[BridgePoseStore] WARN: server start timeout (port={self._port})")
        else:
            print(f"[BridgePoseStore] ws server ready: http://localhost:{self._port}/"
                  f"  (HTML) + ws://localhost:{self._port}/pose")
            print(f"[BridgePoseStore] adb reverse tcp:{self._port} tcp:{self._port} 필요")

    # ── ws server (aiohttp on thread) ──────────────────────────────────
    def _server_thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[BridgePoseStore] server thread error: {e}")

    async def _serve(self) -> None:
        app = web.Application()
        app.router.add_get('/', self._index_handler)
        app.router.add_get('/pose', self._ws_handler)
        app.router.add_get('/config', self._config_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self._port)
        await site.start()
        self._server_ready.set()
        # keep alive
        while True:
            await asyncio.sleep(3600)

    async def _index_handler(self, _request: web.Request) -> web.FileResponse:
        # scripts/bridge_pose_store.py → ../assets/webxr_to_pose.html
        p = Path(__file__).resolve().parent.parent / "assets" / "webxr_to_pose.html"
        if not p.exists():
            return web.Response(status=404, text=f"missing {p}")
        return web.FileResponse(p)

    async def _config_handler(self, _request: web.Request) -> web.Response:
        # webxr_to_pose 가 fetch('/config') 로 호출. URL 쿼리 override 는 client 측에서.
        return web.json_response(CONFIG)

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        print(f"[BridgePoseStore] ws client connected: {request.remote}", flush=True)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        self._handle_message(json.loads(msg.data))
                    except Exception as e:
                        # silent skip — webxr_to_pose 가 매 frame 송신하므로 1회 실패는 무시
                        pass
                elif msg.type == WSMsgType.ERROR:
                    print(f"[BridgePoseStore] ws error: {ws.exception()}", flush=True)
                    break
        finally:
            print(f"[BridgePoseStore] ws client disconnected (total msgs={self._msg_count})",
                  flush=True)
        return ws

    def _handle_message(self, payload: dict) -> None:
        t = payload.get("type")
        if t == "head":
            self._update_head(payload["matrix"])
        elif t == "hand":
            self._update_hand(
                payload["handedness"],
                payload["wrist"],
                payload["positions"],
                payload.get("orientations"),
            )
        with self._stats_lock:
            self._msg_count += 1
            self._last_msg_time = time.perf_counter()

    def _update_head(self, matrix: list) -> None:
        with self.head_pose_shared.get_lock():
            self.head_pose_shared[:] = matrix

    def _update_hand(self, handedness: str, wrist: list, positions: list,
                     orientations: Optional[list]) -> None:
        if not self.use_hand_tracking:
            return
        if handedness == "left":
            arm_shared = self.left_arm_pose_shared
            pos_shared = self.left_hand_position_shared
            ori_shared = self.left_hand_orientation_shared
            pinch_shared = self.left_hand_pinch_shared
            pinchValue_shared = self.left_hand_pinchValue_shared
            squeeze_shared = self.left_hand_squeeze_shared
            squeezeValue_shared = self.left_hand_squeezeValue_shared
        elif handedness == "right":
            arm_shared = self.right_arm_pose_shared
            pos_shared = self.right_hand_position_shared
            ori_shared = self.right_hand_orientation_shared
            pinch_shared = self.right_hand_pinch_shared
            pinchValue_shared = self.right_hand_pinchValue_shared
            squeeze_shared = self.right_hand_squeeze_shared
            squeezeValue_shared = self.right_hand_squeezeValue_shared
        else:
            return

        with arm_shared.get_lock():
            arm_shared[:] = wrist

        # positions: 25 × [x, y, z] → flat 75 float
        flat_pos = np.array(positions, dtype=np.float64).reshape(-1)
        with pos_shared.get_lock():
            pos_shared[:] = flat_pos

        # orientations: 25 × [9 floats column-major 3x3] → flat 225 float
        if orientations is not None:
            flat_ori = np.array(orientations, dtype=np.float64).reshape(-1)
            with ori_shared.get_lock():
                ori_shared[:] = flat_ori

        # pinch / squeeze: thumb-tip ↔ index/middle-tip 거리 기반 계산
        # (vuer client_build 의 getHandLandmarks 로직과 동일)
        pos25 = flat_pos.reshape(25, 3)
        pinch_d = float(np.linalg.norm(pos25[THUMB_TIP_IDX] - pos25[INDEX_TIP_IDX]))
        squeeze_d = float(np.linalg.norm(pos25[THUMB_TIP_IDX] - pos25[MIDDLE_TIP_IDX]))
        with pinch_shared.get_lock():
            pinch_shared.value = pinch_d < PINCH_THRESHOLD
        with pinchValue_shared.get_lock():
            pinchValue_shared.value = pinch_d
        with squeeze_shared.get_lock():
            squeeze_shared.value = squeeze_d < SQUEEZE_THRESHOLD
        with squeezeValue_shared.get_lock():
            squeezeValue_shared.value = squeeze_d

    # ── properties — TeleVuer 와 100% 동일 시그니처 ─────────────────────
    @property
    def head_pose(self) -> np.ndarray:
        with self.head_pose_shared.get_lock():
            return np.array(self.head_pose_shared[:]).reshape(4, 4, order='F')

    @property
    def left_arm_pose(self) -> np.ndarray:
        with self.left_arm_pose_shared.get_lock():
            return np.array(self.left_arm_pose_shared[:]).reshape(4, 4, order='F')

    @property
    def right_arm_pose(self) -> np.ndarray:
        with self.right_arm_pose_shared.get_lock():
            return np.array(self.right_arm_pose_shared[:]).reshape(4, 4, order='F')

    # hand tracking properties
    @property
    def left_hand_positions(self) -> np.ndarray:
        with self.left_hand_position_shared.get_lock():
            return np.array(self.left_hand_position_shared[:]).reshape(25, 3)

    @property
    def right_hand_positions(self) -> np.ndarray:
        with self.right_hand_position_shared.get_lock():
            return np.array(self.right_hand_position_shared[:]).reshape(25, 3)

    @property
    def left_hand_orientations(self) -> np.ndarray:
        with self.left_hand_orientation_shared.get_lock():
            return np.array(self.left_hand_orientation_shared[:]).reshape(25, 9).reshape(
                25, 3, 3, order='F')

    @property
    def right_hand_orientations(self) -> np.ndarray:
        with self.right_hand_orientation_shared.get_lock():
            return np.array(self.right_hand_orientation_shared[:]).reshape(25, 9).reshape(
                25, 3, 3, order='F')

    @property
    def left_hand_pinch(self) -> bool:
        with self.left_hand_pinch_shared.get_lock():
            return bool(self.left_hand_pinch_shared.value)

    @property
    def left_hand_pinchValue(self) -> float:
        with self.left_hand_pinchValue_shared.get_lock():
            return float(self.left_hand_pinchValue_shared.value)

    @property
    def left_hand_squeeze(self) -> bool:
        with self.left_hand_squeeze_shared.get_lock():
            return bool(self.left_hand_squeeze_shared.value)

    @property
    def left_hand_squeezeValue(self) -> float:
        with self.left_hand_squeezeValue_shared.get_lock():
            return float(self.left_hand_squeezeValue_shared.value)

    @property
    def right_hand_pinch(self) -> bool:
        with self.right_hand_pinch_shared.get_lock():
            return bool(self.right_hand_pinch_shared.value)

    @property
    def right_hand_pinchValue(self) -> float:
        with self.right_hand_pinchValue_shared.get_lock():
            return float(self.right_hand_pinchValue_shared.value)

    @property
    def right_hand_squeeze(self) -> bool:
        with self.right_hand_squeeze_shared.get_lock():
            return bool(self.right_hand_squeeze_shared.value)

    @property
    def right_hand_squeezeValue(self) -> float:
        with self.right_hand_squeezeValue_shared.get_lock():
            return float(self.right_hand_squeezeValue_shared.value)

    # controller properties (use_hand_tracking=False 일 때만 의미)
    @property
    def left_ctrl_trigger(self) -> bool:
        with self.left_ctrl_trigger_shared.get_lock():
            return bool(self.left_ctrl_trigger_shared.value)

    @property
    def left_ctrl_triggerValue(self) -> float:
        with self.left_ctrl_triggerValue_shared.get_lock():
            return float(self.left_ctrl_triggerValue_shared.value)

    @property
    def left_ctrl_squeeze(self) -> bool:
        with self.left_ctrl_squeeze_shared.get_lock():
            return bool(self.left_ctrl_squeeze_shared.value)

    @property
    def left_ctrl_squeezeValue(self) -> float:
        with self.left_ctrl_squeezeValue_shared.get_lock():
            return float(self.left_ctrl_squeezeValue_shared.value)

    @property
    def left_ctrl_thumbstick(self) -> bool:
        with self.left_ctrl_thumbstick_shared.get_lock():
            return bool(self.left_ctrl_thumbstick_shared.value)

    @property
    def left_ctrl_thumbstickValue(self) -> np.ndarray:
        with self.left_ctrl_thumbstickValue_shared.get_lock():
            return np.array(self.left_ctrl_thumbstickValue_shared[:])

    @property
    def left_ctrl_aButton(self) -> bool:
        with self.left_ctrl_aButton_shared.get_lock():
            return bool(self.left_ctrl_aButton_shared.value)

    @property
    def left_ctrl_bButton(self) -> bool:
        with self.left_ctrl_bButton_shared.get_lock():
            return bool(self.left_ctrl_bButton_shared.value)

    @property
    def right_ctrl_trigger(self) -> bool:
        with self.right_ctrl_trigger_shared.get_lock():
            return bool(self.right_ctrl_trigger_shared.value)

    @property
    def right_ctrl_triggerValue(self) -> float:
        with self.right_ctrl_triggerValue_shared.get_lock():
            return float(self.right_ctrl_triggerValue_shared.value)

    @property
    def right_ctrl_squeeze(self) -> bool:
        with self.right_ctrl_squeeze_shared.get_lock():
            return bool(self.right_ctrl_squeeze_shared.value)

    @property
    def right_ctrl_squeezeValue(self) -> float:
        with self.right_ctrl_squeezeValue_shared.get_lock():
            return float(self.right_ctrl_squeezeValue_shared.value)

    @property
    def right_ctrl_thumbstick(self) -> bool:
        with self.right_ctrl_thumbstick_shared.get_lock():
            return bool(self.right_ctrl_thumbstick_shared.value)

    @property
    def right_ctrl_thumbstickValue(self) -> np.ndarray:
        with self.right_ctrl_thumbstickValue_shared.get_lock():
            return np.array(self.right_ctrl_thumbstickValue_shared[:])

    @property
    def right_ctrl_aButton(self) -> bool:
        with self.right_ctrl_aButton_shared.get_lock():
            return bool(self.right_ctrl_aButton_shared.value)

    @property
    def right_ctrl_bButton(self) -> bool:
        with self.right_ctrl_bButton_shared.get_lock():
            return bool(self.right_ctrl_bButton_shared.value)

    # ── methods ────────────────────────────────────────────────────────
    def render_to_xr(self, image) -> None:
        """TeleVuer.render_to_xr noop replacement.

        영상 통합은 옵션 B1 (webxr_to_pose 에 WebRTC peer 추가) 또는 옵션 B2
        (PC server image relay) 진입 시 확장. 현재는 ZMQ frame이 호출되더라도
        무시 — operator 가 헤드셋 안에서 영상 못 봄 (별도 desktop 모니터 권장).
        """
        return

    def close(self) -> None:
        """daemon thread 라 main 종료 시 자동 cleanup. 명시적 close 는 noop."""
        return

    # ── stats accessor (debug) ─────────────────────────────────────────
    def get_stats(self) -> dict:
        with self._stats_lock:
            return {
                "msg_count": self._msg_count,
                "last_msg_time": self._last_msg_time,
            }


__all__ = ["BridgePoseStore", "JOINT_NAMES"]
