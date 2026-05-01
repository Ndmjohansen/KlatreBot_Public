#!/usr/bin/env bash
# View recent Hermes agent traces.
#
# Run on the Ubuntu Hermes host. Lists the N most recent session JSON files
# under ~/.hermes/sessions/ and prints each as: USER prompt, TOOL_CALLs with
# arguments, TOOL_RESULTs (truncated), and the final ASSISTANT reply.
#
# Usage:
#   ./view-hermes-trace.sh                     # last 1 session, truncated (~400 chars per chunk)
#   ./view-hermes-trace.sh 5                   # last 5 sessions, truncated
#   ./view-hermes-trace.sh --full              # last 1, no truncation
#   ./view-hermes-trace.sh 5 --full            # last 5, no truncation
#   ./view-hermes-trace.sh 1 -v                # alias for --full
#
# Pipe into less: ./view-hermes-trace.sh 10 --full | less -R

set -u

VERBOSE=""
N=""
for arg in "$@"; do
    case "$arg" in
        -v|--verbose|--full) VERBOSE=1 ;;
        ''|*[!0-9]*) ;;  # skip non-numeric (handled above)
        *) N="$arg" ;;   # first numeric arg = session count
    esac
done
N="${N:-1}"

SESS_DIR="$HOME/.hermes/sessions"
if [[ ! -d "$SESS_DIR" ]]; then
    echo "no session dir at $SESS_DIR" >&2
    exit 1
fi

mapfile -t FILES < <(ls -1t "$SESS_DIR"/session_*.json 2>/dev/null | head -n "$N")
if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "no sessions found" >&2
    exit 1
fi

# Color codes (skip if not a tty)
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; CYAN=$'\033[36m'; YEL=$'\033[33m'
    GRN=$'\033[32m'; MAG=$'\033[35m'; RST=$'\033[0m'
else
    BOLD=""; DIM=""; CYAN=""; YEL=""; GRN=""; MAG=""; RST=""
fi

for f in "${FILES[@]}"; do
    BOLD="$BOLD" DIM="$DIM" CYAN="$CYAN" YEL="$YEL" GRN="$GRN" MAG="$MAG" RST="$RST" \
    VERBOSE="$VERBOSE" python3 - "$f" <<'PYEOF'
import json, os, sys

f = sys.argv[1]
d = json.load(open(f))
B = os.environ.get('BOLD',''); D = os.environ.get('DIM','')
C = os.environ.get('CYAN',''); Y = os.environ.get('YEL','')
G = os.environ.get('GRN',''); M = os.environ.get('MAG',''); R = os.environ.get('RST','')
VERBOSE = bool(os.environ.get('VERBOSE'))

LIMIT = 10**9 if VERBOSE else 400

print(f"{B}=== {os.path.basename(f)} ==={R}")
meta = ['session_start', 'last_updated', 'model', 'platform']
for k in meta:
    if k in d:
        print(f"{D}{k}: {d[k]}{R}")
print()

msgs = d.get('messages') or []
for i, m in enumerate(msgs):
    role = m.get('role', m.get('type', '?'))
    if role == 'user':
        c = m.get('content', '')
        if isinstance(c, str):
            print(f"{C}[{i}] USER{R} {c[:LIMIT]}")
        else:
            print(f"{C}[{i}] USER{R} {str(c)[:LIMIT]}")
    elif role == 'assistant':
        tc = m.get('tool_calls') or []
        for t in tc:
            fn = t.get('function', {})
            args = fn.get('arguments', '')
            if isinstance(args, str):
                try:
                    args = json.dumps(json.loads(args), ensure_ascii=False)
                except Exception:
                    pass
            print(f"{Y}[{i}] TOOL_CALL{R} {B}{fn.get('name')}{R} {args[:LIMIT]}")
        c = m.get('content')
        if c:
            text = c if isinstance(c, str) else str(c)
            print(f"{G}[{i}] ASSISTANT{R} {text[:LIMIT]}")
    elif role == 'tool':
        nm = m.get('name', '?')
        c = m.get('content', '')
        body = c if isinstance(c, str) else str(c)
        # Pretty-print JSON payload if it parses
        try:
            parsed = json.loads(body)
            body = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            pass
        if not VERBOSE and len(body) > LIMIT:
            body = body[:LIMIT] + f" {D}... ({len(body)} chars total){R}"
        print(f"{M}[{i}] TOOL_RESULT{R} {D}[{nm}]{R}")
        for line in body.splitlines():
            print(f"  {line}")
    else:
        print(f"{D}[{i}] {role}: {str(m)[:200]}{R}")

print()
PYEOF
done
