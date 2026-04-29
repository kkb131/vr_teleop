# 프로젝트 컨텍스트 — Galaxy XR 기반 원격조종 시스템

> **목적**: 새 Claude 세션이 이 문서만 읽으면 프로젝트 맥락을 즉시 파악하고 개발을 이어갈 수 있도록 작성된 핸드오프 문서

---

## 1. 프로젝트 한 줄 요약

**Unitree xr_teleoperate 오픈소스를 기반으로, Samsung Galaxy XR 헤드셋을 사용해 UR10e 매니퓰레이터 + Tesollo DG-5F 5-finger 그리퍼를 원격 조종하는 시스템을 구축**한다.

기존 Manus Metaglove + Vive Tracker 시스템을 단일 디바이스(Galaxy XR)로 대체하는 것이 최종 목표이며, 점진적으로 Shared Autonomy(Residual Copilot), gaze-guided manipulation, F/T 시각화 같은 고급 기능까지 확장한다.

---

## 2. 시스템 구성

### 하드웨어
- **헤드셋**: Samsung Galaxy XR (모델명 SM-I610, Android 14, Snapdragon XR2+ Gen 2, 16GB RAM)
- **로봇팔**: UR10e (Universal Robots, 6-DoF)
- **그리퍼**: Tesollo DG-5F (5-finger dexterous hand)
- **카메라**: Intel RealSense D405 × 3대 (egocentric 1 + 양 손목 2)
- **조종 PC**: Ubuntu 22.04, RTX 4090/5090 (예정)
- **로봇 PC**: 별도, 기존 환경 (ur_rtde + PINK IK + DG-5F SDK pipeline 구축됨)

### 분리 아키텍처 (조종 PC ↔ 로봇 PC)
```
[Galaxy XR] ─USB(adb reverse)─→ [조종 PC: televuer + retargeting + ZMQ pub]
                                          ↓ ZMQ
                                 [로봇 PC: 기존 ur_rtde 500Hz pipeline]
                                          ↓
                                  [UR10e + DG-5F]
```

**중요**: 로봇 PC의 기존 pipeline은 그대로 유지. xr_teleoperate에서 IK/제어 부분은 사용하지 않고, 조종 PC에서 target pose만 ZMQ로 송신하는 구조로 운영.

### 네트워크 제약 (필수 인지 사항)
- **연구실 환경에 WiFi 없음** — Galaxy XR과 PC는 USB-C 케이블로만 연결
- `adb reverse`로 USB 직결 통신 (UsbFfs 채널) → 모든 개발 진행 가능
- localhost 접근이라 SSL 인증서 불필요 (HTTPS 예외 적용)

---

## 3. xr_teleoperate 선정 이유

검증된 오픈소스 우선순위:
1. **Unitree xr_teleoperate** ← 최우선 채택
2. OpenTeleVision/TeleVision (참고용)
3. XRoboToolkit (Plan B, Native APK 필요시)

xr_teleoperate를 1순위로 한 이유:
- OpenTeleVision의 후속작으로 televuer/dex-retargeting/teleimager 통합
- Apple Vision Pro, PICO 4, Meta Quest 3 검증됨 → Galaxy XR 호환성 높음
- WebXR 기반이라 헤드셋에 APK 빌드 없이 Chrome 접속만으로 동작
- imitation learning 데이터 수집(LeRobot 호환)까지 포함

### xr_teleoperate 구성 모듈

xr_teleoperate는 6개 계층으로 구성:
- **televuer** (Vuer 기반 WebXR) — XR 입력 취득, 25-joint hand pose
- **teleimager** — ZeroMQ + WebRTC 멀티카메라 스트리밍
- **dex-retargeting** — AnyTeleop 계열 손 retargeting (DG-5F config 추가 필요)
- **robot_arm_ik.py** — Pinocchio + CasADi IK (UR10e용 수정 또는 미사용)
- **robot_arm.py** — Unitree DDS 통신 (UR/DG-5F는 전면 교체 필요)
- **episode_writer + ACT** — 데이터 수집 + imitation learning

### 환경에 맞춰 변경 필요 부분

| 모듈 | 변경 유형 |
|---|---|
| televuer | ✓ 그대로 사용 |
| dex-retargeting | 🔧 DG-5F config YAML 신규 작성 |
| teleimager | 🔧 D405 3대 launch config 수정 |
| robot_arm_ik.py | 🔧 UR10e용 변경 또는 미사용(로봇PC가 IK 수행) |
| robot_arm.py | ❌ ZMQ Sender로 전면 재작성 (DDS 제거) |
| robot_hand_*.py | ❌ DG-5F용 ZMQ Sender 신규 작성 |

---

## 4. 12주 개발 로드맵 (현재 위치 표시)

| Phase | Week | 단계 | 상태 |
|---|---|---|---|
| 1 - 원본 검증 | **Week 1** | 환경 구축 + WebXR 호환성 (Gate 1) | ✅ **완료** |
| 1 - 원본 검증 | Week 2 | televuer 단독 검증 (Gate 2: 30Hz 안정 스트리밍) | ⏳ **다음 차례** |
| 1 - 원본 검증 | Week 3 | IsaacSim에서 G1 원본 예제 재현 (Gate 3) | 대기 |
| 2 - 로봇 교체 | Week 4 | URDF + IK를 UR10e용으로 교체 | 대기 |
| 2 - 로봇 교체 | Week 5 | DG-5F dex-retargeting config 작성 | 대기 |
| 2 - 로봇 교체 | Week 6 | IsaacSim에서 UR10e+DG-5F 통합 (Gate 4) | 대기 |
| 3 - 실시스템 | Week 7 | 조종PC/로봇PC 분리 프로토콜 구현 | 대기 |
| 3 - 실시스템 | Week 8 | 실로봇 초기 통합 (저속 운영) | 대기 |
| 3 - 실시스템 | Week 9 | 멀티카메라 스트리밍 통합 (Gate 5) | 대기 |
| 4 - 평가 | Week 10 | Manus+Vive와 정량 비교 | 대기 |
| 4 - 평가 | Week 11 | 병목 분석 및 개선점 도출 | 대기 |
| 4 - 평가 | Week 12 | Quick Win 적용 + 최종 보고 | 대기 |

### Gate 통과 조건 (각 단계 진입 전 검증)

| Gate | 시점 | 통과 조건 | 실패 시 |
|---|---|---|---|
| **Gate 1** | Week 1 | Galaxy XR Chrome에서 WebXR 25-joint hand tracking 동작 | XRoboToolkit Unity APK 방식으로 Plan B 전환 |
| Gate 2 | Week 2 | televuer로 pose 데이터 30Hz 이상 안정 수신 | 네트워크/필터 디버깅 |
| Gate 3 | Week 3 | IsaacSim에서 G1 원본 teleop 동작 | unitree_sim_isaaclab 설정 재확인 |
| Gate 4 | Week 6 | IsaacSim에서 UR10e+DG-5F 안정 teleop | 해당 주차 연장 |
| Gate 5 | Week 9 | 실로봇+멀티카메라 통합 안정 동작 | 하드웨어/대역폭 재검토 |

---

## 5. Week 1 완료 상태 (2026-04 시점)

### 검증 완료 사항
- ✅ Ubuntu 22.04에 Google 공식 ADB platform-tools 설치 완료
- ✅ Galaxy XR USB 디바이스 인식 (시리얼: R3KYA01R62L, 모델: SM-I610)
- ✅ USB 디버깅 권한 영구 허용 상태
- ✅ ADB Reverse Port Forwarding 동작 확인 (UsbFfs 채널)
- ✅ Galaxy XR Chrome WebXR API 정상 (`navigator.xr` exists)
- ✅ immersive-vr 세션 진입 정상
- ✅ immersive-ar 지원 확인
- ✅ **25-joint Hand Tracking 정상 (`2 hands, 0 controllers` 출력)**
- ✅ **Gate 1 통과** → 원래 계획대로 진행 가능

### 발견된 시행착오 + 해결책 (재발 방지용 기록)

**문제 1**: Ubuntu 패키지 ADB(`28.0.2-debian`)가 glibc 2.35와 호환성 문제로 데몬 시작 시 `free(): invalid pointer` 에러
- **해결**: Ubuntu 패키지 제거 후 Google 공식 platform-tools(`35.x.x`) 직접 설치
- **교훈**: Ubuntu 22.04에서 ADB는 항상 Google 공식 빌드 사용

**문제 2**: WebXR 공식 샘플의 ENTER VR 버튼이 표시되지 않음
- **해결**: 자체 진단 페이지(`webxr_check.html`) 작성으로 우회
- **교훈**: 외부 샘플 의존하지 말고 직접 진단 페이지 작성하는 게 빠름

**문제 3**: VR 세션 시작 후 "응답 없음" 메시지
- **원인**: 렌더링 루프 부재
- **해결**: WebGL 렌더링 루프 + 펄스 색상 추가
- **교훈**: WebXR 세션은 매 프레임 무언가 그려야 함

### USB-Only 표준 운영 절차 (매번 사용 시)

```bash
# 1. Galaxy XR을 PC에 USB-C 연결
# 2. 디바이스 인식 확인
adb devices
# 결과: R3KYA01R62L device

# 3. 사용할 모든 포트 reverse forwarding
adb reverse tcp:8080 tcp:8080  # HTTP 서버
adb reverse tcp:8012 tcp:8012  # televuer WebSocket (예정)

# 4. PC에서 서버 실행
# 5. Galaxy XR Chrome에서 http://localhost:<port> 접속
```

---

## 6. 다음 단계 (Week 2 작업 항목)

### 즉시 시작할 작업
1. **conda 환경 생성**:
   ```bash
   conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge
   conda activate tv
   ```

2. **xr_teleoperate clone 및 서브모듈 초기화**:
   ```bash
   git clone https://github.com/unitreerobotics/xr_teleoperate.git
   cd xr_teleoperate
   git submodule update --init --depth 1
   cd teleop/televuer && pip install -e .
   cd ../robot_control/src/dex-retargeting && pip install -e .
   ```

3. **의존성 설치**:
   ```bash
   pip install meshcat casadi
   pip install unitree_sdk2_python  # DDS 의존성 (당장 사용 안 해도 import 필요)
   ```

4. **televuer 단독 테스트**:
   ```bash
   # PC에서
   cd xr_teleoperate
   adb reverse tcp:8012 tcp:8012  # televuer 포트
   python teleop/televuer/test/_test_televuer.py

   # Galaxy XR Chrome에서
   # http://localhost:8012 또는 https://localhost:8012/?ws=ws://localhost:8012 접속
   ```

5. **검증 항목 (Gate 2)**:
   - TeleData 객체에 head/wrist/hand pose 정상 채워지는지
   - 스트리밍 frequency 30Hz 이상 안정인지
   - 손이 시야 밖으로 나갔다 돌아왔을 때 즉시 복구되는지
   - jitter 정량 측정 (Galaxy XR hand tracking 노이즈 수준)

### Week 2 후반 작업 (Gate 2 통과 후)
6. **IsaacSim 환경 설치 준비** (Week 3 사전 작업):
   ```bash
   # 별도 conda 환경 (xr_teleoperate와 분리)
   git clone https://github.com/unitreerobotics/unitree_sim_isaaclab.git
   ```

---

## 7. 핵심 참조 정보

### 검증된 오픈소스 (우선순위 순)
- `github.com/unitreerobotics/xr_teleoperate` (메인)
- `github.com/OpenTeleVision/TeleVision` (참고)
- `github.com/dexsuite/dex-retargeting` (서브모듈로 포함됨)
- `github.com/unitreerobotics/unitree_sim_isaaclab` (시뮬레이션)
- `github.com/XR-Robotics` (Plan B용 XRoboToolkit)

### Galaxy XR 알려진 한계
- Hand tracking 정확도 1-2cm 수준 (Manus 대비 떨어짐)
- Jitter 약 1cm — temporal smoothing 필요
- Eye tracking은 WebXR으로 접근 제한적 — 향후 Native 앱 필요할 수 있음

### 기봉님이 이미 보유하거나 계획 중인 것
- 기존 ur_rtde + PINK IK + DG-5F SDK pipeline (로봇 PC, 변경 없이 재사용)
- DG-5F URDF (dex-retargeting config 작성에 활용)
- Jetson AGX Orin 세팅 경험
- FoundationPose + SAM3 + Grounding DINO + cuMotion (Phase 5+에서 통합 예정)
- Shared Autonomy 아키텍처 설계 (Residual Copilot, Phase 7+에서 통합)

### 향후 Phase 5+ 확장 로드맵
- Phase 5: F/T 센서 시각화 AR overlay
- Phase 6: Eye-tracking + SAM3 + cuMotion gaze-guided manipulation
- Phase 7: Shared Autonomy (Residual Copilot) 통합
- Phase 8: VLA 자율화 + imitation learning 운영

---

## 8. 함께 작업할 Claude에게 안내

### 의사결정 원칙
1. **검증된 오픈소스 우선**: 새로 짜기보다 검증된 코드 fork + 수정
2. **분리 아키텍처 유지**: 로봇 PC pipeline은 건드리지 않음
3. **WiFi 없는 환경 전제**: 모든 개발은 USB-only 환경 가정
4. **Gate 조건 검증 우선**: 각 Phase 진입 전 통과 조건 확인 후 다음 단계 진행
5. **점진적 안정성**: 시뮬레이션 → 저속 실로봇 → 정상 속도 순으로 진행

### 작업 시 주의사항
- xr_teleoperate의 Unitree DDS 부분은 사용 안 함 (UR/DG-5F에 무용)
- ACT는 baseline으로만 활용, 향후 Diffusion Policy 또는 VLA로 교체 예정
- Vuer는 브라우저 업데이트에 취약하므로 **동작 확인된 Chrome 버전 기록 유지**
- 코드 수정 시 매번 git branch 분리 (예: `feat/dg5f-retargeting`)

### 의문점 발생 시 참조 우선순위
1. xr_teleoperate 공식 README 및 코드 주석
2. OpenTeleVision 논문 (CoRL 2024)
3. AnyTeleop 논문 (RSS 2023)
4. 별도 첨부된 문서들:
   - `weekly_plan.md` (12주 상세 계획)
   - `week1_report.md` (Week 1 완료 보고서)
   - `tech_analysis.md` (기술 스택 분석 및 한계)

---

## 9. 핵심 진단 코드 (재사용 가능)

`webxr_check.html` 핵심부 (Galaxy XR WebXR 검증용, 향후에도 재사용 가능):

```javascript
// WebXR API 단계별 검증 + Hand Tracking 활성화
if (navigator.xr) {
  navigator.xr.isSessionSupported('immersive-vr').then(supported => {
    if (supported) {
      vrBtn.onclick = async () => {
        const canvas = document.createElement('canvas');
        gl = canvas.getContext('webgl2', { xrCompatible: true });
        await gl.makeXRCompatible();

        // 핵심: hand-tracking을 optionalFeatures로 요청
        xrSession = await navigator.xr.requestSession('immersive-vr', {
          optionalFeatures: ['hand-tracking', 'local-floor']
        });

        xrSession.updateRenderState({
          baseLayer: new XRWebGLLayer(xrSession, gl)
        });
        xrRefSpace = await xrSession.requestReferenceSpace('local-floor');

        // Hand input 감지
        xrSession.addEventListener('inputsourceschange', () => {
          let handCount = 0;
          for (const source of xrSession.inputSources) {
            if (source.hand) handCount++;
          }
          console.log(`Hands: ${handCount}`);
        });

        xrSession.requestAnimationFrame(onXRFrame);
      };
    }
  });
}

// 매 프레임 렌더링 + Hand pose 접근
function onXRFrame(time, frame) {
  xrSession.requestAnimationFrame(onXRFrame);
  const pose = frame.getViewerPose(xrRefSpace);
  if (!pose) return;

  // 렌더링 (응답 없음 방지)
  gl.bindFramebuffer(gl.FRAMEBUFFER, xrSession.renderState.baseLayer.framebuffer);
  gl.clearColor(0.2, 0.3, 0.5, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);

  // 25-joint Hand pose 데이터 접근
  for (const source of frame.session.inputSources) {
    if (source.hand) {
      const wrist = source.hand.get('wrist');
      const wristPose = frame.getJointPose(wrist, xrRefSpace);
      // wristPose.transform.position / .orientation 사용 가능
    }
  }
}
```

WebXR 표준 25-joint 이름 (xr_teleoperate televuer와 동일):

```javascript
const JOINT_NAMES = [
  'wrist',
  'thumb-metacarpal','thumb-phalanx-proximal','thumb-phalanx-distal','thumb-tip',
  'index-finger-metacarpal','index-finger-phalanx-proximal',
  'index-finger-phalanx-intermediate','index-finger-phalanx-distal','index-finger-tip',
  'middle-finger-metacarpal','middle-finger-phalanx-proximal',
  'middle-finger-phalanx-intermediate','middle-finger-phalanx-distal','middle-finger-tip',
  'ring-finger-metacarpal','ring-finger-phalanx-proximal',
  'ring-finger-phalanx-intermediate','ring-finger-phalanx-distal','ring-finger-tip',
  'pinky-finger-metacarpal','pinky-finger-phalanx-proximal',
  'pinky-finger-phalanx-intermediate','pinky-finger-phalanx-distal','pinky-finger-tip'
];
```

---

*이 문서는 새 Claude 세션의 컨텍스트로 활용하기 위해 작성되었습니다. 시작 시 이 문서 + 첨부된 weekly_plan.md, week1_report.md를 함께 제공해주세요.*
