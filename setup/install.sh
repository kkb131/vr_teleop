#!/usr/bin/env bash
# xr_teleoperate clone + 서브모듈 + editable install
#
# 공식 가이드(https://github.com/unitreerobotics/xr_teleoperate#11--basic)와 절차 동일하되,
# 우리 환경에서 발견한 호환성 함정 두 가지를 추가로 처리한다:
#  - vuer 0.0.60는 params-proto>=3에서 ImportError 발생 → params-proto<3 핀
#  - dex-retargeting은 pin==2.7 / torch==2.3 강제로 시스템 stack을 다운그레이드하므로
#    INSTALL_DEX_RETARGETING=1 일 때만 설치 (Week 5)
#
# Usage:
#   conda env에서:  conda activate tv && bash setup/install.sh
#   Docker에서:     bash setup/install.sh    (system pip 사용)
#   Week 5 진입:    INSTALL_DEX_RETARGETING=1 bash setup/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "[install] working dir: $REPO_ROOT"
echo "[install] python: $(which python3)  $(python3 --version)"

# ── 1. xr_teleoperate clone ──
if [ ! -d "xr_teleoperate" ]; then
  echo "[install] cloning xr_teleoperate..."
  git clone https://github.com/unitreerobotics/xr_teleoperate.git
else
  echo "[install] xr_teleoperate already exists — skipping clone"
fi

cd xr_teleoperate
echo "[install] initializing submodules (shallow)..."
git submodule update --init --depth 1

# ── 2. teleimager (--no-deps, 공식 권장 — Week 9에서 본격 사용) ──
if [ -d "teleop/teleimager" ]; then
  echo "[install] pip install -e teleop/teleimager --no-deps"
  pip install -e teleop/teleimager --no-deps
fi

# ── 3. televuer (vuer/aiohttp/등 transitive deps 함께 설치) ──
echo "[install] pip install -e teleop/televuer"
pip install -e teleop/televuer

# ── 4. 호환성 핀: vuer 0.0.60 + params-proto<3 ──
# televuer가 끌고 들어오는 params-proto가 3.x로 깔리면 vuer.server import 실패. 강제로 2.x로.
echo "[install] pinning params-proto<3 for vuer 0.0.60 compatibility"
pip install 'params-proto<3'

# ── 5. dex-retargeting (opt-in, Week 5) ──
if [ "${INSTALL_DEX_RETARGETING:-0}" = "1" ] && [ -d "teleop/robot_control/dex-retargeting" ]; then
  echo "[install] pip install -e teleop/robot_control/dex-retargeting"
  pip install -e teleop/robot_control/dex-retargeting
else
  echo "[install] dex-retargeting skip (Week 5에서 INSTALL_DEX_RETARGETING=1 로 재실행)"
fi

# ── 6. unitree_sdk2_python (PyPI에 없으면 GitHub fallback) ──
if ! python3 -c "import unitree_sdk2py" >/dev/null 2>&1; then
  echo "[install] installing unitree_sdk2_python..."
  pip install unitree_sdk2_python || {
    TMP="$(mktemp -d)"
    git clone https://github.com/unitreerobotics/unitree_sdk2_python.git "$TMP"
    pip install -e "$TMP"
  }
else
  echo "[install] unitree_sdk2_python already importable — skipping"
fi

# ── 7. numpy 가드 ──
# pip 의존성이 numpy 2.x로 끌어올렸으면 강제 다운그레이드 (pinocchio ABI 호환)
NUMPY_MAJOR=$(python3 -c "import numpy; print(numpy.__version__.split('.')[0])")
if [ "$NUMPY_MAJOR" != "1" ]; then
  echo "[install] numpy $NUMPY_MAJOR.x detected — forcing <2"
  pip install 'numpy<2' --force-reinstall --no-deps
fi

# ── 8. SSL 인증서 ── (Galaxy XR Chrome → televuer 서버 HTTPS/WSS 연결용)
# televuer/vuer는 cert/key 없이 부팅 안 됨. idempotent하므로 매번 호출해도 안전.
if [ -x "$SCRIPT_DIR/gen_certs.sh" ]; then
  echo "[install] running gen_certs.sh..."
  bash "$SCRIPT_DIR/gen_certs.sh" || \
    echo "[install] WARN: gen_certs.sh failed — bash setup/gen_certs.sh 수동 실행 필요"
fi

echo ""
echo "[OK] install complete. Next:"
echo "     python3 setup/verify.py"
echo "     python3 setup/test_pose_only.py     # Galaxy XR 연결 후"
echo "     bash setup/diagnose.sh              # connectivity 5단계 점검 (test_pose_only 실행 중에)"
