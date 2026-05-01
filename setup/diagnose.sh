#!/usr/bin/env bash
# Galaxy XR ↔ televuer connectivity 5단계 진단.
#
# 사용 시점: setup/test_pose_only.py를 PC에서 실행한 상태에서 (별도 터미널에서)
#            돌리면 가장 정확. 서버가 안 떠 있어도 1, 4단계는 점검 가능.
#
# Usage:
#   bash setup/diagnose.sh

set -uo pipefail

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xr_teleoperate"
PORT=8012

# ── color helpers ─────────────────────────────────────────────────────
if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[34m'; X=$'\033[0m'
else
  R=""; G=""; Y=""; B=""; X=""
fi
ok()   { echo "${G}[OK]${X}   $*"; }
warn() { echo "${Y}[WARN]${X} $*"; }
fail() { echo "${R}[FAIL]${X} $*"; }
hdr()  { echo; echo "${B}── $* ──${X}"; }

PASS=0; FAILS=0

# ── 1. cert 파일 존재 + SAN 포함 확인 ──────────────────────────────────
hdr "1. SSL cert (~/.config/xr_teleoperate/)"
if [ ! -f "$CONF_DIR/cert.pem" ] || [ ! -f "$CONF_DIR/key.pem" ]; then
  fail "cert.pem / key.pem 없음 → bash setup/gen_certs.sh"
  ((FAILS++))
else
  ok   "cert/key 파일 존재"
  if openssl x509 -in "$CONF_DIR/cert.pem" -noout -ext subjectAltName 2>/dev/null \
        | grep -qE 'DNS:localhost|IP Address:127\.0\.0\.1'; then
    ok   "SubjectAltName(SAN) 포함됨"
    ((PASS++))
  else
    fail "SAN 누락 — Chrome 58+가 거부함. bash setup/gen_certs.sh --force 로 재생성"
    ((FAILS++))
  fi
fi

# ── 2. PC 측 TCP LISTEN 확인 (vuer 서버 떠있는지) ──────────────────────
hdr "2. vuer server LISTEN on :${PORT}"
LISTEN=$(ss -tlnH 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $4}' | head -1)
if [ -z "$LISTEN" ]; then
  fail "포트 $PORT 에 LISTEN 없음 → 다른 터미널에서 'python3 setup/test_pose_only.py' 먼저 실행"
  ((FAILS++))
else
  ok   "$PORT LISTEN: $LISTEN"
  ((PASS++))
  # 0.0.0.0이 아니면 외부에서 못 옴
  case "$LISTEN" in
    0.0.0.0:*|"[::]":*|"*:$PORT") ok "전체 인터페이스 바인딩 OK" ;;
    127.0.0.1:*|"[::1]":*) warn "loopback 전용 — adb reverse는 OK이지만 외부 IP로는 못 들어옴" ;;
    *) warn "특정 IP 바인딩: $LISTEN" ;;
  esac
fi

# ── 3. PC 핸드셰이크 (HTTP/HTTPS 둘 다 시도, 서버 모드 자동 감지) ──────
hdr "3. PC HTTP/HTTPS 핸드셰이크 (localhost:${PORT})"
if [ -n "${LISTEN:-}" ]; then
  HTTP_CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 \
              "http://localhost:${PORT}/" 2>/dev/null || echo "000")
  HTTPS_CODE=$(curl -k -sS -o /dev/null -w '%{http_code}' --max-time 3 \
               "https://localhost:${PORT}/" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" != "000" ] && [ "$HTTP_CODE" != "" ]; then
    ok "HTTP  $HTTP_CODE — plain HTTP 모드 (Galaxy XR 권장)"
    ((PASS++))
  elif [ "$HTTPS_CODE" != "000" ] && [ "$HTTPS_CODE" != "" ]; then
    ok "HTTPS $HTTPS_CODE — TLS 모드 (cert 필요)"
    ((PASS++))
    warn "Galaxy XR Chrome이 self-signed cert 거부 시: --http 모드로 재시작 권장"
  else
    fail "HTTP / HTTPS 둘 다 응답 없음 (000) — 서버 부팅 실패"
    ((FAILS++))
  fi
else
  warn "step 2 LISTEN 없으므로 건너뜀"
fi

# ── 4. adb 디바이스 + reverse 상태 ─────────────────────────────────────
hdr "4. adb device & reverse"
if ! command -v adb >/dev/null 2>&1; then
  fail "adb 미설치 → README Step A 참조"
  ((FAILS++))
else
  DEV=$(adb devices | awk 'NR>1 && $2=="device" {print $1}' | head -1)
  if [ -z "$DEV" ]; then
    fail "adb device 없음 (또는 unauthorized) → 헤드셋 RSA 키 허용 + USB 케이블 확인"
    ((FAILS++))
  else
    ok "device: $DEV"
    REV=$(adb -s "$DEV" reverse --list 2>/dev/null | grep -E "tcp:${PORT}\\s+tcp:${PORT}" || true)
    if [ -z "$REV" ]; then
      fail "tcp:$PORT reverse 없음 → adb reverse tcp:$PORT tcp:$PORT"
      ((FAILS++))
    else
      ok "reverse 활성: $REV"
      ((PASS++))
    fi
  fi
fi

# ── 5. 요약 ────────────────────────────────────────────────────────────
hdr "요약"
TOTAL=$((PASS + FAILS))
if [ "$FAILS" -eq 0 ]; then
  ok "모든 단계 통과 ($PASS/$TOTAL)"
  echo
  if [ "${HTTP_CODE:-000}" != "000" ] && [ -n "${HTTP_CODE:-}" ]; then
    echo "  Galaxy XR Chrome → http://localhost:${PORT}     (cert 경고 없음, 권장)"
  else
    echo "  Galaxy XR Chrome → https://localhost:${PORT}    (cert 경고 → '고급 → 진행')"
    echo "    cert 경고 자체가 안 뜨거나 'no data' 표시 시:"
    echo "      - PC에서 Ctrl+C 후 'python3 setup/test_pose_only.py --http' 로 재시작 (권장)"
    echo "      - chrome://flags/#allow-insecure-localhost   enable + Chrome 재시작"
    echo "      - chrome://net-internals/#hsts               'Delete domain security policies' 에 localhost 입력"
  fi
  exit 0
else
  fail "$FAILS 개 단계 실패 ($PASS/$TOTAL). 위 메시지 따라 수정 후 재실행"
  exit 1
fi
