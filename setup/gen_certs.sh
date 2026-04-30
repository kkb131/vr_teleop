#!/usr/bin/env bash
# Galaxy XR (Android XR Chrome) + USB adb reverse 환경용 self-signed 인증서 생성.
#
# televuer/vuer 서버는 항상 HTTPS+WSS 모드로 부팅되어 cert/key 파일을 강제 로드한다
# (televuer.py:91 → Vuer(host='0.0.0.0', cert=cert_file, key=key_file, ...)).
# localhost는 브라우저 쪽에서만 secure context 예외이고, 서버는 cert가 있어야 시작됨.
#
# 생성 위치(televuer 자동 검색 경로):
#   $XDG_CONFIG_HOME/xr_teleoperate/cert.pem  (또는 ~/.config/xr_teleoperate/)
#   $XDG_CONFIG_HOME/xr_teleoperate/key.pem
#
# Usage:
#   bash setup/gen_certs.sh           # 이미 있으면 skip (idempotent)
#   bash setup/gen_certs.sh --force   # 만료 등으로 재생성

set -euo pipefail

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xr_teleoperate"
mkdir -p "$CONF_DIR"

FORCE="${1:-}"
if [ -f "$CONF_DIR/cert.pem" ] && [ -f "$CONF_DIR/key.pem" ] && [ "$FORCE" != "--force" ]; then
  echo "[certs] $CONF_DIR/cert.pem 이미 존재 → 재생성하려면: bash setup/gen_certs.sh --force"
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "[certs] ERROR: openssl 미설치. 'sudo apt install openssl' 후 재시도"
  exit 1
fi

echo "[certs] generating self-signed cert with SAN (DNS:localhost, IP:127.0.0.1, IP:::1) → $CONF_DIR"
# Chrome 58+ (특히 Android XR Chrome)은 SubjectAltName 없는 cert를 invalid로 즉시 거부 →
# cert 경고 화면도 못 띄우고 ERR_EMPTY_RESPONSE 발생. SAN과 serverAuth EKU 명시 필수.
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$CONF_DIR/key.pem" -out "$CONF_DIR/cert.pem" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1" \
  -addext "basicConstraints=CA:FALSE" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>&1 | grep -v "^\.\.\.\.\.\.\.\.\.\.$" || true

chmod 600 "$CONF_DIR/key.pem"
chmod 644 "$CONF_DIR/cert.pem"

echo ""
echo "[certs] OK"
echo "         cert: $CONF_DIR/cert.pem"
echo "         key : $CONF_DIR/key.pem"
echo "[certs] Galaxy XR Chrome 첫 접속 시 'self-signed' 경고 → '고급 → 안전하지 않은 사이트로 이동' 한 번 수동 허용"
