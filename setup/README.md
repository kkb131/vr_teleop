# xr_teleoperate 환경 구축 가이드 (다른 PC 재현용)

이 폴더는 **Galaxy XR과 USB로 연결되는 조종 PC**에 xr_teleoperate 개발 환경을 그대로 재현하기 위한 자료입니다. Week 1 보고서의 ADB/USB 설정 + Week 2 conda 환경 + xr_teleoperate clone을 한 번에 끝낼 수 있도록 정리했습니다.

## 사전 요건

- **OS**: Ubuntu 22.04 (Week 1에서 검증된 조합)
- **하드웨어**: Galaxy XR (SM-I610) + USB-C 데이터 케이블
- **권장**: NVIDIA RTX GPU (추후 NVENC 인코딩에 사용)
- **계정**: sudo 가능한 일반 사용자

> 📝 Docker 컨테이너에서 작업하는 경우 Step A~C는 호스트에서 1회만 수행해도 되고, conda 대신 system pip로 설치해도 됩니다(자세한 내용은 본 폴더 외부의 `docs/CLAUDE.md` §6 참고).

---

## Step A — Google 공식 ADB(platform-tools) 설치

> ⚠️ Ubuntu 패키지(`android-tools-adb`)는 glibc 2.35 호환성 문제로 데몬 시작 시 `free(): invalid pointer` 에러가 납니다(Week 1에서 확인). **반드시 Google 공식 빌드를 사용하세요.**

```bash
# 기존 패키지 ADB 제거 (있을 경우)
sudo apt remove --purge android-tools-adb android-tools-fastboot 2>/dev/null || true
sudo apt autoremove -y

# Google 공식 platform-tools 설치
cd /tmp
wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip
unzip -q platform-tools-latest-linux.zip
sudo mv platform-tools /opt/

# PATH 등록 (bashrc)
grep -q '/opt/platform-tools' ~/.bashrc || \
  echo 'export PATH=/opt/platform-tools:$PATH' >> ~/.bashrc
export PATH=/opt/platform-tools:$PATH

adb --version    # "Version 35.x.x" 표시되면 정상
```

## Step B — udev rules + plugdev 그룹 (Samsung VID 04e8)

```bash
sudo usermod -aG plugdev "$USER"
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/51-android.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
# 로그아웃 후 재로그인 (또는 재부팅)
```

연결 후 인식 확인:
```bash
adb devices
# 처음에는 "unauthorized" → Galaxy XR 헤드셋 안에서 RSA 키 지문 팝업 "이 컴퓨터에서 항상 허용" 체크
adb devices
# R3KYA01R62L device   ← 정상
```

## Step C — Miniconda 설치 (없을 경우)

```bash
cd /tmp
wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p "$HOME/miniconda3"
"$HOME/miniconda3/bin/conda" init bash
source ~/.bashrc
conda --version
```

## Step D — conda env 생성

```bash
cd <이 README가 있는 폴더의 상위 폴더, 즉 src/xr_teleop/>
conda env create -f setup/environment.yml
conda activate tv
```

생성되는 환경 `tv` — **공식 README와 동일하게 conda는 3개 패키지만**:
- Python 3.10
- pinocchio 3.1.0 (conda-forge)
- numpy 1.26.4 (pinocchio ABI 호환을 위해 <2 고정)

> 💡 **왜 3개만?** 공식 가이드도 동일. casadi/matplotlib/opencv를 conda로 핀하면 conda-forge에 정확한 patch 버전이 없거나(matplotlib=3.7.5*) transitive dep끼리 RECORD 파일 충돌(`uninstall-no-record-file`)이 납니다. 나머지는 모두 install.sh가 pip로 처리.

## Step E — xr_teleoperate clone + editable install

```bash
bash setup/install.sh
```

이 스크립트가 수행하는 작업 (공식 가이드 절차와 동일):
1. `src/xr_teleop/xr_teleoperate/`에 upstream clone (https://github.com/unitreerobotics/xr_teleoperate)
2. `git submodule update --init --depth 1` (televuer / dex-retargeting / teleimager)
3. `pip install -e teleop/teleimager --no-deps` (공식 권장)
4. `pip install -e teleop/televuer` — vuer / casadi / meshcat / matplotlib 등이 transitive로 함께 들어옴
5. **호환성 핀**: `pip install 'params-proto<3'` (vuer 0.0.60는 3.x에서 ImportError)
6. `unitree_sdk2_python` (PyPI 우선, 실패 시 GitHub fallback)
7. numpy 가드 — pip가 numpy 2.x로 끌어올렸으면 `<2`로 강제 다운그레이드

> ⚠️ **dex-retargeting는 기본적으로 설치 안 함**: Week 5에서 DG-5F 손 retargeting 작업 시 사용. 깨끗한 conda env(`tv`)에서 `INSTALL_DEX_RETARGETING=1 bash setup/install.sh`로 재실행하면 함께 설치됨. 시스템 torch/pinocchio가 이미 다른 버전으로 깔린 환경(예: 우리 Docker)에서는 충돌이 일어나므로 자동 설치를 막아둠.

## Step F — sanity check

```bash
python3 setup/verify.py
```

기대 결과:
```
[OK]   numpy                  1.26.4
[OK]   pinocchio              3.1.0
[OK]   casadi                 ...
[OK]   meshcat                ...
[OK]   vuer                   0.0.60
[OK]   televuer               ...
[OK]   dex_retargeting        ...
[OK]   unitree_sdk2py         ...
[adb reverse] ...
[PASS] all checks ok
```

## Step F.5 — Galaxy XR 인증서 생성

televuer/vuer 서버는 항상 HTTPS+WSS로 부팅하면서 cert/key 파일을 강제 로드한다 (소스: `televuer.py:91`). localhost는 브라우저 쪽에서만 secure context 예외이고, **서버 자체는 cert가 있어야 시작**된다.

```bash
bash setup/gen_certs.sh
# → ~/.config/xr_teleoperate/cert.pem, key.pem 생성 (CN=localhost)
# 이미 있으면 skip. 만료 시: bash setup/gen_certs.sh --force
```

공식 [televuer README §2.2~2.3](../xr_teleoperate/teleop/televuer/README.md)의 Pico/Quest 경로와 동일하되 USB adb reverse 환경에 맞춰 CN을 `localhost`로 고정. AVP rootCA 경로는 불필요.

## Step G — televuer pose-only 검증 (Gate 2)

업스트림 `example/test_televuer.py`는 teleimager 영상 서버(192.168.123.164)에 의존하므로 Week 9까지는 동작 못 한다. 우리는 영상 의존성을 제거한 [setup/test_pose_only.py](test_pose_only.py)를 사용한다.

### T1 — PC 측 서버 기동

```bash
# 1) Galaxy XR USB-C 연결 후
adb devices                          # R3KYA01R62L device 확인
adb reverse tcp:8012 tcp:8012        # televuer WebSocket
adb reverse --list                   # UsbFfs tcp:8012 tcp:8012

# 2) televuer pose-only 서버 시작 — Galaxy XR Chrome은 self-signed HTTPS를
#    엄격 거부하는 경우가 많아 **plain HTTP 모드 권장** (--http 플래그)
conda activate tv                    # (system pip 환경이면 생략)
cd src/xr_teleop
python3 setup/test_pose_only.py --http   # ← 추천: HTTP 평문, cert 불필요
# python3 setup/test_pose_only.py        # ← 기본 HTTPS 모드 (cert.pem 필요)
```

> 💡 **왜 --http 권장?** Galaxy XR Chrome은 self-signed cert를 SAN까지 추가해도 ERR_EMPTY_RESPONSE로 끊는 사례가 확인됨. localhost는 W3C 사양상 평문 HTTP도 secure context로 인정되어 WebXR API가 그대로 동작. (실제로 Week 1의 webxr-samples 동작 확인이 이 경로.) [vuer.base.py:119-120](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py)에서 cert=None이면 자동 HTTP fallback이라 안전한 우회.

### T2 — Galaxy XR (Chrome)

`--http` 모드:
1. `http://localhost:8012` 접속 (cert 경고 없음 — localhost 예외)
2. **Enter VR** (또는 좌하단 **pass-through**) 클릭
3. 손을 시야 안에 들이밀어 hand tracking 활성화
4. PC 터미널에서 Enter → 1Hz 로그가 흐르기 시작 (`OK / OK / OK / OK / OK` + 좌표)

기본 HTTPS 모드 (`--http` 없이 실행한 경우):
1. `https://localhost:8012/?ws=wss://localhost:8012` 접속
2. self-signed cert 경고 → **고급 → 안전하지 않은 사이트로 이동**
3. cert 경고 자체가 안 뜨면 (PC에서) `Ctrl+C` 후 `--http` 모드로 재시작

### T3 — Gate 2 정량 측정

```bash
python3 setup/test_pose_only.py --http --measure 30 --report docs/week2_report.md
```

가이드:
- 30초 자동 측정. 시작 직후 ① 손 자연스럽게 움직이기 → ② 한 번 시야 밖으로 뺐다 다시 들이밀기 (recovery 측정) → ③ 마지막 5초간 손 정지 (jitter 측정)
- 종료 후 `docs/week2_report.md`에 markdown 표가 append됨

> ⚠️ **결과 해석 주의**: 보고서의 NaN=0 / Hz≥30만 보고 "성공"이라 판단하지 말 것. **Lost frames per field가 전체 프레임 수와 같으면(예: `5571 / 5571`) 30초 동안 단 한 프레임도 실제 pose를 못 받은 것** — Hz는 Python 폴링 속도일 뿐이고 shared array가 zeros 초기값 그대로일 때도 NaN=0으로 표시됨. 이 경우 `--debug` 절차로 진행.

### T4 — Lost frames 100% 트러블슈팅

> 🔥 **가장 흔한 원인: 잘못된 URL.** Lost가 전체 프레임 수와 같으면 server에 WebSocket 연결 자체가 안 된 상태입니다 (Hz/NaN은 정상처럼 보일 수 있음 — Hz는 Python 폴링 속도, NaN은 zeros 초기값에서도 0). **먼저 URL부터 정확히 확인**:
>
> | 모드 | 정확한 URL |
> |---|---|
> | `--http` | `http://localhost:8012` |
> | 기본 (HTTPS) | `https://localhost:8012/?ws=wss://localhost:8012` |
>
> ❌ **하지 말 것**: vuer 부팅 메시지 `Visit: https://vuer.ai?grid=False`의 `vuer.ai` 도메인 직접 접속. 이건 vuer-ai 호스팅 frontend로 우리 local server와 별개이며, 환경에 따라 WebSocket이 우리 server에 안 붙음.

URL이 정확한데도 Lost가 100%면 [televuer.py](../xr_teleoperate/teleop/televuer/src/televuer/televuer.py)의 `on_cam_move`/`on_hand_move`가 `try: ... except: pass`로 감싸져 있어 이벤트 파싱 실패가 묻힐 가능성. `--debug` 플래그로 핸들러 호출 횟수와 첫 이벤트 구조를 노출해 원인 파악:

```bash
python3 setup/test_pose_only.py --http --debug --measure 30
```

종료 시 출력되는 `debug summary`로 시나리오 판별:

| 출력 패턴 | 시나리오 | 처방 |
|---|---|---|
| `cam=0, hand=0` | **B 전체** — WebSocket 미연결 또는 WebXR session 미시작 | (1) URL 재확인 — 위 박스 표 (2) "Enter VR" 정확히 눌렀는지, hand-tracking 권한 허용했는지 확인 |
| `cam>0, hand=0`, lost: head=0 / 나머지 100% | **B 한정** (드물게) | 일반적으로는 잘못된 URL일 가능성 크니 URL부터 재검증. 그래도 동일하면 `--show-hands` (experimental) 시도 |
| `cam>0` + `errors`도 비슷 | **A** — `event.value` 구조 mismatch | 출력된 `first event.value` dump + traceback 보고 핸들러 보정 |
| `cam>0, hand>0, errors=0`인데 lost 100% | **C** — Process 분리에서 shared array 미공유 | vuer 단일 process wrapper 작성 |

> 📊 **실측 사례 (Quest 3, 2026-05-05)**: 정확한 URL(`http://localhost:8012`)로 접속 시 cam>0, hand>0, lost=0/모든 필드, 192Hz로 Gate 2 통과 확인 (week2_report.md 22:15, 22:18). 이전 100% lost runs는 모두 **wrong URL artifact**였음 — `vuer.ai` 호스팅 페이지로 잘못 들어간 케이스.

#### `--show-hands` (experimental) 사용 예

```bash
python3 setup/test_pose_only.py --http --debug --show-hands --measure 30
```

vuer Hands 컴포넌트의 `hideLeft/hideRight=False`로 강제. **Quest 3 + 정확한 URL에서는 hideLeft=True여도 stream이 정상 동작함이 확인되어 보통 불필요**. hideLeft=True가 stream까지 막는 헤드셋이 발견될 가능성에 대비해 옵션으로만 유지.

### Gate 2 통과 조건

| 항목 | 측정 | 통과 기준 |
|---|---|---|
| 평균 frequency | `mean_freq_hz` | ≥ 30 Hz |
| Recovery latency | `recovery_latency_s` | < 1.0 s |
| TeleData 필드 NaN | `nan_per_field` | 모두 0 |
| Wrist jitter (정지 5초) | `wrist_jitter_cm` | 보고만 (~1 cm 예상) |
| 좌표계 | smoke 모드 hand_pos[0] 부호 | 손 들었을 때 z 양수 |

자세한 12주 계획상의 통과 조건은 [`docs/xr_teleoperate_weekly_plan.md`](../docs/xr_teleoperate_weekly_plan.md) Week 2 참고.

결과는 `docs/week2_report.md`에 기록.

---

## Step H — IsaacSim G1+Dex3-1 통합 검증 (Week 3 / Gate 3)

전제: 같은 host에서 별도 docker container로 `unitree_sim_isaaclab`이 sim_main.py로 G1+Dex3-1 환경 구동 중. 자세한 sim host 측 설정은 [`docs/INTEGRATION_FOR_XR_TELEOPERATE.md`](../docs/INTEGRATION_FOR_XR_TELEOPERATE.md) 참조.

**T1 — DDS 환경 변수**

```bash
source setup/dds_env.sh   # RMW_IMPLEMENTATION + ROS_DOMAIN_ID=1
```

**T2 — sim 통신 자동 진단**

```bash
python3 setup/test_dds_sim.py
# 기대 결과:
#   A. DDS LowState ~94 Hz (3초간 ~280 msgs)
#   B. ZMQ camera frames (head/left/right 모두 응답)
#   C. passive LowCmd publish 50회 (sim 콘솔에 에러 없으면 OK)
```

3/3 단계 통과해야 Step H의 다음 단계로 진입.

**T3 — xr_teleoperate teleop 시작 (우리 wrapper 사용)**

```bash
# conda env tv 활성화 + DDS env (먼저 source dds_env.sh로)
conda activate tv
source setup/dds_env.sh

# adb reverse는 헤드셋 연결된 PC에서
adb reverse tcp:8012 tcp:8012

# 우리 wrapper로 실행 — --http monkey-patch + --img-server-ip 127.0.0.1 default 자동
python setup/run_teleop.py --ee dex3 --sim
# 내부 호출:
#   cd xr_teleoperate/teleop
#   python teleop_hand_and_arm.py --img-server-ip 127.0.0.1 --ee dex3 --sim
# (vuer가 plain HTTP로 부팅, cert 거부 우회)
```

부팅 시 이 메시지들이 순서대로 보여야 정상:
```
[run_teleop] HTTP mode (plain) — vuer cert/key forced to None
[run_teleop] cwd → .../xr_teleoperate/teleop
INFO  Received camera config from server 127.0.0.1:60000
INFO  [G1_29_ArmIK] >>> Loading cached/URDF
INFO  [G1_29_ArmController] Subscribe dds ok
INFO  Initialize Dex3_1_Controller OK!
INFO  [SimStateSubscriber] Started subscribing to rt/sim_state
🟢  Press [r] to start syncing the robot with your movements.
```

**T4 — Quest 3/Galaxy XR Chrome에서 hand teleop**

1. Chrome → `http://localhost:8012` 접속 (HTTP 평문, cert 경고 없음 — Week 2 결론대로)
2. **Enter VR** 클릭 → 손을 시야에 들이밀어 hand tracking 활성화
3. 터미널에서 `r` 키 입력 → 동기화 시작
4. IsaacSim 화면에서 G1 팔과 Dex3-1 손가락이 따라 움직이는지 시각 확인
5. 종료: 터미널에서 `q` 키

**Gate 3 통과 조건**: Quest 3 hand tracking → IsaacSim G1+Dex3-1 자연스러운 teleop 1회 이상 시각 확인 + 30 Hz 이상 안정 동작 + recording 1 episode.

---

## 트러블슈팅

### `Vuer encountered an error: [Errno 2] No such file or directory`

televuer/vuer 서버가 cert/key 파일을 못 찾을 때. `bash setup/gen_certs.sh` 실행 후 재시도.

### `WARNING Request to 192.168.123.164:60000 timed out or no response`

업스트림 `example/test_televuer.py`가 teleimager 영상 서버를 찾는 메시지. Week 9 멀티카메라 통합 전까지는 무시 가능. **pose-only 검증은 [setup/test_pose_only.py](test_pose_only.py)를 사용**하면 이 경고 자체가 안 나온다.

### Galaxy XR Chrome에서 "이 페이지가 작동하지 않습니다" — cert 경고조차 안 뜸

거의 모든 경우 cert에 **SubjectAltName(SAN) 누락**이 원인. Chrome 58+(특히 Android XR Chrome)은 CN만 있는 self-signed cert를 invalid로 즉시 거부하면서 "고급 → 진행" 옵션조차 표시 안 함. 결과적으로 ERR_EMPTY_RESPONSE에 가까운 빈 페이지만 보임. PC Chrome에서 잘 됐다면 첫 접속 시 통과시킨 cert가 cache되어서일 뿐.

```bash
bash setup/gen_certs.sh --force      # SAN 포함된 새 cert 생성
bash setup/diagnose.sh               # PC측 5단계 진단 (cert SAN, vuer LISTEN, HTTPS, adb)
# televuer 서버 재시작 + Galaxy XR Chrome에서 캐시 비우고 재접속
```

확인 명령:
```bash
openssl x509 -in ~/.config/xr_teleoperate/cert.pem -noout -ext subjectAltName
# X509v3 Subject Alternative Name:
#     DNS:localhost, IP Address:127.0.0.1, IP Address:0:0:0:0:0:0:0:1
```

여전히 안 되면 (Android XR Chrome strict 모드 우회):
1. `chrome://flags/#allow-insecure-localhost` enable + Chrome 재시작
2. `chrome://net-internals/#hsts` → "Delete domain security policies" 에 `localhost` 입력 후 삭제
3. 그래도 안 되면 cert.pem을 Android Settings → Security → Trusted Credentials로 수동 import (CA 형식 변환 필요 — AVP 경로의 rootCA 방식 적용)

### `wss://` 연결 실패 / WebSocket 끊김

```bash
adb reverse --list      # UsbFfs tcp:8012 tcp:8012 표시 확인
# 안 보이면:
adb kill-server && adb start-server
adb reverse tcp:8012 tcp:8012
```

### `conda env create` 도중 `cannot uninstall casadi 3.6.7` (uninstall-no-record-file)

원인: conda-forge `pinocchio=3.1.0`이 `casadi`를 **conda 패키지**로 미리 설치하는데, 그 다음 pip 단계에서 같은 패키지를 다시 설치/uninstall하려다 RECORD 파일이 없어 실패.

해결: `casadi`/`matplotlib`/`opencv`는 pip 섹션이 아닌 **conda dependencies**에 두어야 함. 본 폴더의 `environment.yml`이 이미 그렇게 되어 있으니, 만약 옛 environment.yml로 만들었던 env가 있으면 한 번 지우고 다시 생성:

```bash
conda env remove -n tv
conda env create -f setup/environment.yml
```

부분 복구만 하고 싶으면:
```bash
conda activate tv
pip install --ignore-installed casadi   # 또는 conda install -c conda-forge casadi
```

### numpy가 2.x로 올라간 경우

```bash
pip install 'numpy<2' --force-reinstall --no-deps
python3 -c "import pinocchio"   # ImportError 안 나면 OK
```

### adb 디바이스가 unauthorized로 굳어버린 경우

```bash
adb kill-server && adb start-server
adb devices       # 다시 헤드셋 안의 RSA 지문 팝업 확인
```

### 매 작업 시작 절차 (요약)

```bash
adb devices                       # device 확인
adb reverse tcp:8012 tcp:8012     # televuer 포트
conda activate tv                 # (conda 환경)
cd src/xr_teleop/xr_teleoperate
python3 teleop/televuer/test/_test_televuer.py
# Galaxy XR Chrome → http://localhost:8012
```

---

## 관련 문서

- `../docs/CLAUDE.md` — 프로젝트 전체 컨텍스트 (한 페이지 요약)
- `../docs/xr_teleoperate_weekly_plan.md` — 12주 상세 계획
- `../docs/week1_report.md` — Week 1 (ADB/WebXR/Gate 1) 보고서
- `../docs/xr_teleoperate_tech_analysis.md` — 기술 스택 분석 + 한계
