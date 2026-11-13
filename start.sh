#!/bin/bash
# macOS development launcher; compatible with the system Bash 3.2.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer the project's environment; macOS may still ship Python 3.9.
for candidate in "${PYTHON:-}" "$root/apps/api/.venv/bin/python" python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        exec "$candidate" "$root/scripts/start_macos.py" "$@"
    fi
done
echo '需要 Python 3.11+。安装后重试，例如：brew install python@3.11' >&2
exit 1
