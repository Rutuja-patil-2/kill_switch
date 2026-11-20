#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.." || exit 1

pick_python() {
  if command -v python >/dev/null 2>&1; then
    echo python
  elif command -v python3 >/dev/null 2>&1; then
    echo python3
  elif command -v py >/dev/null 2>&1; then
    echo py
  else
    echo ""
  fi
}

PYTHON="$(pick_python)"
if [ -z "$PYTHON" ]; then
  echo "FAIL: no Python interpreter found"
  exit 1
fi

echo "== starting stack =="
docker compose up -d --build
if [ $? -ne 0 ]; then
  echo "FAIL: docker compose up"
  exit 1
fi

echo "== waiting for health =="
healthy=0
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done
if [ "$healthy" -ne 1 ]; then
  echo "FAIL: gateway health timeout"
  exit 1
fi

echo "== seeding demo agents =="
docker compose exec -T gateway python -m app.cli seed-demo > tokens.json
if [ $? -ne 0 ]; then
  echo "FAIL: seed-demo"
  exit 1
fi

fail=0
echo "== utility tests =="
"$PYTHON" tests/test_util.py || fail=1

echo "== demo =="
"$PYTHON" agents/run_demo.py || fail=1

echo "== gateway integration tests =="
"$PYTHON" tests/test_gateway.py || fail=1

if [ "$fail" -eq 0 ]; then
  echo "PASS: phase1 check"
  exit 0
else
  echo "FAIL: phase1 check"
  exit 1
fi
