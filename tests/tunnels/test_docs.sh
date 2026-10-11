#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOC="$ROOT/docs/operations/ssh-tunnels.md"
grep -q 'com.babymonitor.ssh-tunnels' "$DOC"
grep -q 'com.babymonitor.ollama-tunnel' "$DOC"
grep -q '127.0.0.1:1984' "$DOC"
grep -q '127.0.0.1:11435' "$DOC"
grep -q 'Camera Reply' "$DOC"
grep -q 'does not disable' "$DOC"
grep -q 'hardware activation remains' "$DOC"
echo 'test_docs=PASS'
