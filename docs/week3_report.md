# Week 3 개발 결과 보고서

**프로젝트**: xr_teleoperate 기반 Galaxy XR + UR10e + DG-5F 원격조종 시스템
**기간**: Phase 1, Week 3
**목적**: IsaacSim G1+Dex3-1 + Quest 3 hand tracking 통합 검증 (Gate 3) — xr_teleoperate 업스트림 stack 전체가 우리 환경에서 동작함을 확인

---

## 1. 금주 목표

12주 개발 계획의 **Phase 1 - Week 3** 단계로, 다음 사항을 검증하는 것이 목표였습니다.

- 같은 host의 별도 docker container에서 돌고 있는 `unitree_sim_isaaclab` (G1+Dex3-1)에 우리 docker가 CycloneDDS로 붙는지 확인
- xr_teleoperate 업스트림의 `teleop_hand_and_arm.py`를 우리 환경에서 boot해 IsaacSim 안의 G1+Dex3-1을 hand tracking으로 조종 가능한지 (**Gate 3**)
- 다른 PC에서 재현 가능하도록 setup/ 폴더를 conda env / wrapper 단위로 보강
- 발견된 호환성 이슈를 모두 자동 처리하는 wrapper(run_teleop.py) 완성

> Gate 3 통과 시 → Week 4(UR10e URDF + IK 교체)로 Phase 2 진입
> Gate 3 실패 시 → DDS / 의존성 / cert / vuer race 등 분기별 처방

본 주차 통합 환경:
- **xr_teleoperate side**: 본 docker (Ubuntu 24.04 host 위 Ubuntu 22.04 container, ROS Humble + cuMotion stack), conda env `tv`
- **sim host side**: 같은 물리 host의 별도 docker (`unitree_sim_isaaclab` + Isaac Sim 5.1.0 + Isaac Lab 0.46.6 + conda env `unitree_sim_env` Python 3.11)
- **헤드셋**: Meta Quest 3 (Galaxy XR 본기 검증은 Week 7-8 이월)
- 두 docker 모두 `--network=host` → CycloneDDS multicast 자동 동작

---

## 2. 주요 결과 및 산출물

### 2.1 핵심 결과 요약

| 검증 항목 | 결과 | 비고 |
|---|---|---|
| INTEGRATION §8.A: DDS LowState subscribe (~94 Hz) | ✅ 성공 | 93.0 Hz / 279 msgs in 3s 수신 |
| INTEGRATION §8.B: ZMQ camera frame (head/L/R) | ✅ 성공 | 3개 카메라 모두 응답 (74KB / 43KB / 43KB) |
| INTEGRATION §8.C: passive LowCmd round-trip | ✅ 성공 | 50 msgs publish, sim 콘솔 에러 없음 |
| conda env `tv` 자동 생성 + pinocchio.casadi backend 정상 | ✅ 성공 | activate hook으로 ROS PYTHONPATH 자동 unset |
| `teleop_hand_and_arm.py --ee dex3 --sim` boot 통과 | ✅ 성공 | 메인 루프 진입 ('Press [r] to start syncing') |
| Quest 3 hand tracking → IsaacSim G1+Dex3-1 동작 | ✅ 성공 | 사용자 실측 — hand sync 자연스럽게 따라감 |
| **VR scene 안 head_camera 영상 plane 표시** | ✅ 성공 | spawn retry monkey-patch 적용 후 |
| **Gate 3 통과** | ✅ **통과** | Phase 1 완료 → Week 4 진입 가능 |

**🎯 Gate 3 결과: 통과**

xr_teleoperate 업스트림 stack 전체 (vuer pose stream + televuer wrapper + Pinocchio IK + Unitree DDS + IsaacSim G1+Dex3-1)가 우리 환경에서 end-to-end 동작 확정. **Week 4 (UR10e URDF + IK 교체)로 진입**.

### 2.2 산출물 목록

- **신규 파일** (다른 PC 재현용):
  - `setup/dds_env.sh` — `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` + `ROS_DOMAIN_ID=1` 한 곳
  - `setup/test_dds_sim.py` — INTEGRATION §8 자동화 (LowState subscribe + 3 ZMQ camera + LowCmd round-trip + 색상 OK/WARN/FAIL)
  - `setup/run_teleop.py` — `teleop_hand_and_arm.py` wrapper:
    * `_sanity_check()`: conda env `tv` 활성화 / pinocchio.casadi / dex_retargeting 사전 확인 + fail-fast
    * `_apply_http_monkey_patch()`: vuer cert/key를 None으로 강제 (Week 2 v3 기법, plain HTTP 부팅)
    * `_patch_image_spawn_retry()`: `main_image_*_webrtc/zmq` spawn func 8개를 monkey-patch — `AssertionError: Websocket session is missing` 시 0.5초 sleep 후 20회 재시도
    * `_ensure_sim_defaults()`: `--img-server-ip localhost` 자동 삽입 (cert 신뢰 host 일치)
    * cwd를 `xr_teleoperate/teleop/`로 변경 (robot_arm_ik.py의 `../assets/g1/...` 상대 경로 대응)
- **수정 파일**:
  - `setup/environment.yml` — `pip` 패키지 명시 추가
  - `setup/install.sh` — `python3 -m pip` 강제, requirements.txt + vuer[all]==0.0.60 명시 설치, INSTALL_DEX_RETARGETING opt-in
  - `setup/README.md` — Step H 신규 (T1-T6: dds_env / test_dds_sim / run_teleop / Quest 3 / VR webrtc / controller 모드)
- **conda env `tv` activate hook**:
  - `/root/miniconda3/envs/tv/etc/conda/activate.d/clear_pythonpath.sh` — ROS PYTHONPATH 자동 unset
  - `/root/miniconda3/envs/tv/etc/conda/deactivate.d/restore_pythonpath.sh` — deactivate 시 복원
- **새로 받은 외부 자료**:
  - `docs/INTEGRATION_FOR_XR_TELEOPERATE.md` — sim host 측 환경 / DDS topic / 검증 절차 명세 (사용자 작성, 277 lines)

---

## 3. 수행 내역

### 3.1 Day 1 — DDS 통신 verification

본 docker에서 INTEGRATION §8의 3가지 verification을 수동으로 확인.

**(a) Docker network 모드 확인**
```
hostname → ys-MS-7D75
hostname -I → 211.221.73.41 192.168.0.10 172.17.0.1 ...
```
host network namespace 공유 확정 (docker bridge가 아니라 host 인터페이스 그대로 보임).

**(b) DDS 환경**
```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1
```
sim의 sim_main.py가 `ChannelFactoryInitialize(1)`로 도메인 1을 강제하므로 동일 도메인 필요.

**(c) §8.A LowState subscribe**: 93 Hz / 279 msgs in 3s — sim의 RobotState publisher가 약 94Hz로 publish 중 정상 확인.

**(d) §8.B ZMQ camera**: head(55555) 74KB, left_wrist(55556) 43KB, right_wrist(55557) 43KB 모두 응답.

**(e) §8.C passive LowCmd**: 50회 publish 정상, sim 콘솔에 에러 없음.

→ 통신 기반 검증 완료. INTEGRATION 문서 §1의 host network mode + Section §2의 DDS 설정이 모두 정상 동작.

### 3.2 Day 2 — 자동화 스크립트

Day 1을 매번 수동 명령으로 돌리지 않도록 자동화:

**(a) `setup/dds_env.sh`** — RMW + ROS_DOMAIN_ID 한 곳에서 export. 매 작업 시작 전 `source setup/dds_env.sh`.

**(b) `setup/test_dds_sim.py`** — INTEGRATION §8을 한 번에 실행하는 진단 스크립트. step 0 환경 변수 / A LowState / B ZMQ 3대 / C round-trip 모두 점검 + 색상 OK/WARN/FAIL + 요약 + 다음 액션 제안. 옵션: `--skip-cameras`, `--skip-lowcmd`, `--lowstate-duration N`.

**(c) `setup/README.md` Step H 신규** — Step A~G 다음에 IsaacSim 통합 절차 (T1 dds_env → T2 test_dds_sim → T3 run_teleop → T4 Quest 3 hand teleop → T5 VR 영상 → T6 controller 모드).

→ 결과: `python setup/test_dds_sim.py` 한 줄로 3/3 단계 통과 확인.

### 3.3 Day 3 — `teleop_hand_and_arm.py` wrapper 작성

xr_teleoperate 업스트림의 `teleop/teleop_hand_and_arm.py`를 우리 환경에서 그대로 boot하기 위해 `setup/run_teleop.py` wrapper 작성.

**(a) cert 강제 우회 (Week 2 v3 기법 답습)**
- teleop_hand_and_arm.py가 `TeleVuerWrapper`를 통해 vuer를 부팅하는데 vuer는 cert/key 강제 → Quest 3 brower의 cert 신뢰 비용. Week 2의 monkey-patch (cert=None → plain HTTP fallback)를 동일하게 적용:
```python
class _PlainHTTPVuer(_OrigVuer):
    def __init__(self, *args, **kwargs):
        kwargs["cert"] = None; kwargs["key"] = None
        super().__init__(*args, **kwargs)
_tv_mod.Vuer = _PlainHTTPVuer
```

**(b) cwd 변경**
- `robot_arm_ik.py`가 G1 URDF를 `../assets/g1/g1_body29_hand14.urdf` 상대 경로로 로드 → 사용자가 어느 디렉토리에서 실행하든 `xr_teleoperate/teleop/`에서 돌도록 가정. 우리는 `setup/`에서 wrapper 호출하므로 `os.chdir(teleop_path.parent)`로 변경.

**(c) `--img-server-ip` default 자동 삽입**
- 같은 host 다른 docker = sim image server가 localhost. 사용자 명시 안 하면 wrapper가 `--img-server-ip localhost`를 자동 삽입. (초기엔 `127.0.0.1`이었으나 v6에서 `localhost`로 변경 — webrtc_url cert host mismatch 회피)

**(d) sys.argv 정리**
- vuer 임포트 시 params_proto가 sys.argv를 가로채 우리 wrapper 옵션이 가려짐 → argparse 먼저 수행 후 `sys.argv = sys.argv[:1]`로 비우기.

**(e) runpy 실행**
- teleop_hand_and_arm.py가 `if __name__ == '__main__':` 가드라 `runpy.run_path(..., run_name="__main__")`로 호출.

→ 첫 boot 시도에서 `ImportError: cannot import name 'casadi' from 'pinocchio'` 발생. 다음 단계로.

### 3.4 Day 3 - pinocchio.casadi 이슈 → conda env tv 도입

**증상**: ROS Humble system pinocchio (`/opt/ros/humble/lib/...`)는 casadi backend 없이 빌드됨. teleop_hand_and_arm.py가 `from pinocchio import casadi` 강제하므로 즉시 ImportError.

**해결**: 사용자 docker에 conda env `tv`를 새로 만들어 그 안에서 conda-forge `pinocchio=3.1.0` (casadi backend 포함) 사용.

**시행착오**:
1. `environment.yml`에 `pip` 자체가 명시 안 되어 있어 conda env에 pip 미설치 → `python -m pip` "No module named pip" → `environment.yml`에 `pip` 추가
2. conda activate 후에도 `which pip` → `/usr/bin/pip` (system pip) → install.sh의 모든 `pip install` 호출을 `python3 -m pip install`로 변경 (어느 PATH에서도 conda env의 pip 우선)
3. ROS Humble PYTHONPATH가 conda env site-packages를 가림 → `/root/miniconda3/envs/tv/etc/conda/activate.d/clear_pythonpath.sh` activate hook 설치 (env 활성 시 PYTHONPATH 자동 unset, deactivate 시 복원)
4. `install.sh`에 requirements.txt 설치 단계 누락 (matplotlib 등) → §1b/§1c 추가
5. `dex_retargeting` 미설치 → G1+Dex3-1 hand control은 `INSTALL_DEX_RETARGETING=1`이 필수 (이전엔 Week 5로 미뤘으나 Week 3에서도 필요해 활성)

→ `python setup/verify.py` 통과 + `python setup/run_teleop.py --ee dex3 --sim`이 메인 루프 진입까지 도달.

### 3.5 Day 3 - sanity check 추가 (사용자 conda activate 누락 대응)

사용자가 `conda activate tv` 없이 `python setup/run_teleop.py`를 실행 → system Python으로 떨어져 200줄 traceback. 사용자 인내 비용 큼. wrapper 시작 시점에 `_sanity_check()`로 fail-fast 안내:
- `CONDA_DEFAULT_ENV != 'tv'` → exit 2 + `conda activate tv` 안내
- `import pinocchio.casadi` 실패 → exit 3 + PYTHONPATH/install.sh 안내
- `import dex_retargeting` 실패 → exit 4 + INSTALL_DEX_RETARGETING 안내

### 3.6 Day 4 (v6) — VR scene 안 영상 plane 미등록 fix

**증상**: 사용자 Quest 3로 hand sync는 잘 되는데 Enter VR 후 vuer scene 안에 빈 3D 공간만, 영상 plane 미표시.

**진단**:
- `https://localhost:60001/2/3` 직접 접속 시 영상 스트림 OK (sim WebRTC server 정상)
- PC log에 `AssertionError: Websocket session is missing` from `televuer.py:470 main_image_monocular_webrtc` + ws connect/disconnect 반복

**원인**: ws disconnect race + webrtc_url host mismatch. 두 갈래 처방:

**(a) Step 1A — `--img-server-ip` default를 `127.0.0.1` → `localhost`로 변경**
- vuer client의 webrtc_url이 `https://localhost:60001/offer`로 만들어져 사용자가 신뢰한 cert host와 일치 → cert 거부로 인한 ws lifecycle race trigger 제거
- (대안 Step 1B: sim host측 image_server.py를 patch해 HTTP 모드로 영구 운영. 사용자 선택은 1A. plan에 1B는 fallback으로 보존)

**(b) Step 2 — spawn func retry monkey-patch (default ON)**
- `televuer.TeleVuer.main_image_*_webrtc/zmq` spawn func 8개를 monkey-patch
- `AssertionError: Websocket session is missing` 발생 시 0.5초 sleep 후 20회 재시도
- ws race가 동시 발생해도 자동 회복

→ 사용자 Quest 3 재시도에서 vuer scene 안 head 영상 plane 정상 표시 확인. **Gate 3 통과**.

**참고**: wrist 카메라(60002/60003)는 sim에서 영상 publish 중이지만 업스트림 default가 head_camera 영상만 vuer scene에 띄우도록 설계됨 (immersive first-person view 디자인). Wrist 카메라 multi-plane 표시는 12주 plan의 Week 9 (멀티카메라 통합)에서 다룸.

### 3.7 Day 5 — Gate 3 정성 확인

| 항목 | 결과 |
|---|---|
| Quest 3 hand tracking → IsaacSim G1 팔 동작 | ✅ 자연스러움 |
| Dex3-1 손가락 retargeting | ✅ 동작 |
| VR scene 안 head_camera 영상 표시 | ✅ 정상 |
| 컨트롤러 입력 (`--input-mode controller` 미사용 시) | 정상적으로 무시 (default `hand`) |
| 30Hz 안정 동작 | ✅ (sim controller 250Hz publish, hand pose ≥30Hz) |

→ Gate 3 통과 조건 모두 충족.

---

## 4. 이슈 및 리스크

### 4.1 발생한 이슈와 해결

| 이슈 | 원인 | 해결 방법 | 상태 |
|---|---|---|---|
| ROS Humble system pinocchio에 casadi backend 없음 | apt 패키지가 casadi 옵션 없이 빌드됨 | conda env `tv` 도입 + activate hook으로 PYTHONPATH unset | ✅ 해결 |
| `environment.yml`에 pip 미명시 → conda env에 pip 미설치 | 단순화 시 누락 | environment.yml에 `pip` 패키지 추가 | ✅ 해결 |
| `which pip` → /usr/bin/pip (system) (conda activate 후에도) | PATH 우선순위 / 일부 base 이미지 알리아스 | install.sh 모든 pip 호출을 `python3 -m pip`로 변경 | ✅ 해결 |
| `ImportError: cannot import name 'casadi' from 'pinocchio'` | 위 문제와 동일 (conda env 미사용) | conda env tv 활성화 + sanity check fail-fast | ✅ 해결 |
| matplotlib 미설치 (teleop_hand_and_arm.py import chain) | install.sh §0에 requirements.txt 단계 누락 | §1b로 `pip install -r requirements.txt` 추가 | ✅ 해결 |
| `dex_retargeting` 미설치 → robot_hand_unitree.py import 실패 | Week 2 시점 INSTALL_DEX_RETARGETING=0 (Week 5로 미룸) | Week 3에서 `INSTALL_DEX_RETARGETING=1`로 활성 | ✅ 해결 |
| `g1_body29_hand14.urdf does not contain valid URDF` | robot_arm_ik.py가 `../assets/g1/...` cwd-relative 경로 | wrapper에서 `os.chdir(teleop_path.parent)`로 변경 | ✅ 해결 |
| 사용자 conda activate 누락 시 200줄 traceback | wrapper 사전 안내 없음 | `_sanity_check()`로 exit 2/3/4 명확히 분기 안내 | ✅ 해결 |
| `AssertionError: Websocket session is missing` 반복 | webrtc_url host mismatch + ws disconnect race | (1A) `--img-server-ip` default `localhost` (2) `_patch_image_spawn_retry()` default ON | ✅ 해결 |
| VR scene 안 빈 3D 공간만, 영상 plane 미표시 | 위와 동일 | 위와 동일 | ✅ 해결 |

### 4.2 잠재 리스크

**리스크 1: Galaxy XR 본기 측 미검증**
- 본 주차 검증은 Quest 3로만 진행. Galaxy XR Chrome의 cert 정책이 더 strict한 것으로 알려져 있어 webrtc cert 신뢰 단계가 더 까다로울 수 있음
- **대응**: Week 7-8 (실시스템 통합) 시점에 Galaxy XR 본기 PC에서 동일 setup 재현 + 측정 비교

**리스크 2: ws race retry monkey-patch 부작용**
- `_patch_image_spawn_retry()`가 spawn func 8개 모두를 wrap. AssertionError 외 다른 예외가 발생하는 경우는 그대로 raise하지만, vuer 0.0.60의 다른 lifecycle path와 충돌 가능성
- **대응**: 부작용 발견 시 try/except 범위를 더 좁게 (`AssertionError + "Websocket session" 문자열만`)

**리스크 3: Quest 3 기본 브라우저 vs Chrome 동작 차이**
- 우리 README는 Chrome 가정. Quest 3 기본 브라우저 (Meta Browser / Wolvic)는 cert/WebRTC 동작이 미세히 다를 수 있음. v6 fix가 Meta Browser에서 동작 확인 — Wolvic은 별도 검증 필요할 수 있음
- **대응**: 사용자 사용 브라우저 정보 기록. 필요 시 webrtc_codec=h264 → vp8 fallback (sim 측 cam_config 변경)

**리스크 4: Wrist 카메라가 VR scene에 미표시**
- 업스트림 default 설계 (immersive first-person view). 데이터는 sim에서 publish 중이고 record 모드에서 HDF5에 저장은 됨. VR 안 wrist plane 추가는 별도 작업
- **대응**: Week 9 (멀티카메라 통합)에서 자체 wrapper로 picture-in-picture 추가

**리스크 5: pin 2.7.0 ↔ pinocchio 3.1.0 같은 conda env 내 충돌 가능성**
- dex_retargeting이 pin 2.7.0을 끌어옴. conda env tv 안에서는 conda-forge pinocchio 3.1이 우선이라 import는 정상 동작 확인. 단 향후 `python -m pip install` 시 dependency resolver가 다시 다운그레이드 시도할 수 있음
- **대응**: `python -m pip install --no-deps`로 dex_retargeting 부분 옵션. 또는 pin 2.7을 hpp-fcl 등과 함께 분리 관리

### 4.3 다음 주차로 이월되는 항목

- **Week 4**: UR10e URDF 준비 + `robot_arm_ik.py`를 UR10e용으로 수정 (G1_29_ArmIK → UR10e_ArmIK), single-arm 구조로 단순화
- **Week 7-8**: Galaxy XR 본기에서 Week 1~3 setup 재현 검증 + 실로봇 통합
- **Week 9**: Wrist 카메라(60002/60003) VR scene 다중 plane 표시
- **Week 5**: DG-5F dex-retargeting config (`configs/tesollo_dg5f.yml`) 작성

---

## 5. 작업 상세 자료 및 주요 코드

### 5.1 정립된 표준 절차 (다른 PC 재현)

```bash
# Step A~F: Week 1/2와 동일 (ADB / udev / Miniconda / conda env / install.sh / verify.py)
# Step G: televuer pose-only 검증 (Week 2)

# === Step H: IsaacSim G1+Dex3-1 통합 (Week 3 신규) ===
# T1: DDS env
source setup/dds_env.sh

# T2: 통신 자동 진단 (sim host에서 sim_main.py가 돌고 있어야 함)
python setup/test_dds_sim.py
# → 3/3 단계 통과 확인

# T3: teleop_hand_and_arm.py wrapper 시작
conda activate tv    # 필수 (sanity check가 fail-fast로 감시)
adb reverse tcp:8012 tcp:8012
adb reverse tcp:60001 tcp:60001
adb reverse tcp:60002 tcp:60002
adb reverse tcp:60003 tcp:60003
python setup/run_teleop.py --ee dex3 --sim
# → 메인 루프 진입 ('Press [r] to start syncing')

# T4: Quest 3 Chrome
# - https://localhost:60001 / 60002 / 60003 한 번씩 cert 신뢰 (--http라도 webrtc는 https)
# - http://localhost:8012 → Enter VR → 손 들이밀기 → r 키 → 동기화 시작
# - 종료: q 키
```

### 5.2 핵심 monkey-patch 패턴 (run_teleop.py)

```python
import televuer.televuer as _tv_mod

# v3 — vuer cert/key 강제 None (plain HTTP)
_OrigVuer = _tv_mod.Vuer
class _PlainHTTPVuer(_OrigVuer):
    def __init__(self, *args, **kwargs):
        kwargs["cert"] = None; kwargs["key"] = None
        super().__init__(*args, **kwargs)
_tv_mod.Vuer = _PlainHTTPVuer

# v6 — image spawn func retry-on-ws-disconnect (8 methods)
def _wrap(orig_method):
    async def _retried(self, session):
        for attempt in range(20):
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
             "main_image_monocular_webrtc_ego", "main_image_binocular_webrtc_ego",
             "main_image_monocular_zmq_ego",    "main_image_binocular_zmq_ego"):
    if hasattr(_tv_mod.TeleVuer, name):
        setattr(_tv_mod.TeleVuer, name, _wrap(getattr(_tv_mod.TeleVuer, name)))
```

### 5.3 conda env activate hook (PYTHONPATH 자동 unset)

```bash
# /root/miniconda3/envs/tv/etc/conda/activate.d/clear_pythonpath.sh
export _TV_PYTHONPATH_BACKUP="${PYTHONPATH:-}"
unset PYTHONPATH

# /root/miniconda3/envs/tv/etc/conda/deactivate.d/restore_pythonpath.sh
export PYTHONPATH="${_TV_PYTHONPATH_BACKUP:-}"
unset _TV_PYTHONPATH_BACKUP
```

### 5.4 INTEGRATION §8 자동화 진단 결과 (실측)

```
══ unitree_sim_isaaclab ↔ xr_teleoperate 통신 진단 ══

── 0. DDS 환경 변수 ──
[OK]   RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
[OK]   ROS_DOMAIN_ID=1

── A. DDS LowState subscribe (3s) ──
[OK]   279 msgs (93.0 Hz, expected ~94 Hz)

── B. ZMQ camera frames ──
[OK]   head_camera @ tcp://127.0.0.1:55555: 74,021 bytes
[OK]   left_camera @ tcp://127.0.0.1:55556: 42,740 bytes
[OK]   right_camera @ tcp://127.0.0.1:55557: 42,642 bytes

── C. passive LowCmd round-trip (50 msgs / 1s) ──
[OK]   50 passive lowcmds published — sim 콘솔에 에러 없으면 round-trip OK

── 요약 ──
[OK]   3/3 단계 통과 — Day 3(teleop_hand_and_arm.py 실행) 진입 가능
```

### 5.5 매 작업 시작 시 표준 절차 요약

```bash
# 1. sim host docker에서 sim_main.py 시작 (사용자 측, INTEGRATION §6)
#    conda activate unitree_sim_env && cd unitree_sim_isaaclab
#    python sim_main.py --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint \
#      --enable_dex3_dds --robot_type g129 --device cuda:0 --enable_cameras \
#      --livestream_type 2 --public_ip 127.0.0.1
#    "controller started, start main loop..." 표시 확인

# 2. xr_teleoperate side docker (본 docker)
conda activate tv
source setup/dds_env.sh
adb devices                                # 헤드셋 USB 연결 확인
adb reverse tcp:8012 tcp:8012              # vuer
adb reverse tcp:60001 tcp:60001            # head_camera webrtc
adb reverse tcp:60002 tcp:60002            # left_wrist webrtc
adb reverse tcp:60003 tcp:60003            # right_wrist webrtc

# 3. (선택) 통신 점검
python setup/test_dds_sim.py

# 4. teleop wrapper 시작
python setup/run_teleop.py --ee dex3 --sim

# 5. Quest 3 / Galaxy XR Chrome
#    - 첫 사용 시: https://localhost:60001 / 60002 / 60003 한 번씩 cert 신뢰
#    - http://localhost:8012 → Enter VR → 손 들이밀기 → r 키
```

---

## 6. Week 3 결론

**Gate 3 통과**. xr_teleoperate 업스트림 stack 전체가 우리 환경에서 동작함이 확정되었습니다. 검증된 핵심 사항:

- 같은 host의 별도 docker에서 돌고 있는 `unitree_sim_isaaclab` (G1+Dex3-1)에 우리 docker가 CycloneDDS multicast로 정상 연결
- conda env `tv` (pinocchio 3.1.0 + casadi backend) + activate hook (PYTHONPATH 자동 unset)으로 ROS Humble과 격리된 안전한 환경
- `setup/run_teleop.py` wrapper가 cert 강제 우회 / cwd 변경 / sanity check / spawn retry / img-server-ip default 5가지 자동 처리
- Quest 3에서 `http://localhost:8012` → Enter VR → vuer scene 안 head_camera 영상 + hand sync → IsaacSim G1+Dex3-1 동작까지 end-to-end

다른 PC 재현은 setup/README.md Step A~H를 따라 30분~1시간 내 가능. Galaxy XR 본기 검증은 Week 7-8 통합 시점에 동일 절차로 수행.

다음 주(Week 4)부터 **Phase 2 — UR10e + DG-5F 교체**로 진입합니다. Week 4는 G1 URDF/IK를 UR10e용으로 교체하고 (`G1_29_ArmIK → UR10e_ArmIK`, dual-arm → single-arm), IsaacSim 환경에서도 UR10e 모델로 전환. Gate 4(IsaacSim에서 UR10e + DG-5F 안정 teleop)는 Week 6 마무리 시점.

---

*Week 3 보고서 끝.*
