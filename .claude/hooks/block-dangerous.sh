#!/usr/bin/env bash
# PreToolUse hard-block hook. Exit 2 = block. Reads tool JSON on stdin.
input=$(cat)
cmd=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

block() { echo "BLOCKED by guardrail: $1" >&2; exit 2; }

# Reading secrets
echo "$cmd" | grep -qiE '(^|[^a-z])cat[[:space:]]+.*\.env' && block "reading .env"
echo "$cmd" | grep -qiE 'printenv|env[[:space:]]*$' && block "dumping env vars"
echo "$cmd" | grep -qiE '\.env|secrets/' && block "touching secrets"

# Destructive
echo "$cmd" | grep -qiE 'rm[[:space:]]+.*-[a-z]*r[a-z]*f' && block "rm -rf"
echo "$cmd" | grep -qiE 'git[[:space:]]+push[[:space:]]+.*(--force|-f)' && block "force push"
echo "$cmd" | grep -qiE 'git[[:space:]]+reset[[:space:]]+--hard' && block "git reset --hard"

# Running the pentest tool against a target (this project's core safety rule)
echo "$cmd" | grep -qiE '(^|[^a-z])strix([[:space:]]|$).*(-t|--target|-n)' && block "running the pentest tool against a target"
echo "$cmd" | grep -qiE 'run_strix_scan|run_cli|run_tui' && block "invoking a scan run"

exit 0
