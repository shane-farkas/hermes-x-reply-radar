#!/usr/bin/env bash
# x-reply-radar installer
# Sets up the skill/scripts based on detected agent type.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/shane-farkas/hermes-x-reply-radar/main/install.sh | bash
#
# Or clone and run: ./install.sh

set -e

REPO_URL="https://github.com/shane-farkas/hermes-x-reply-radar.git"
SKILL_NAME="x-reply-radar"
HERMES_SKILL_DIR="$HOME/.hermes/skills/social-media/$SKILL_NAME"

# Colors for output (disable if not a terminal)
if [ -t 1 ]; then
    BOLD="\033[1m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    RED="\033[0;31m"
    RESET="\033[0m"
else
    BOLD=""
    GREEN=""
    YELLOW=""
    RED=""
    RESET=""
fi

step() { printf "${BOLD}${GREEN}==>${RESET} ${BOLD}%s${RESET}\n" "$1"; }
warn() { printf "${BOLD}${YELLOW}==> WARNING:${RESET} %s\n" "$1"; }
err()  { printf "${BOLD}${RED}==> ERROR:${RESET} %s\n" "$1"; }

# Detect agent type
detect_agent() {
    AGENT="unknown"
    if [ -d "$HOME/.hermes" ]; then
        AGENT="hermes"
    fi
    echo "$AGENT"
}

# Check Python
check_python() {
    step "Checking Python..."
    if command -v python3 >/dev/null 2>&1; then
        PY=$(python3 --version 2>&1)
        echo "  Found: $PY"
        return 0
    fi
    err "python3 not found. Install Python 3.8+ first."
    return 1
}

# Check / install xurl
check_xurl() {
    step "Checking xurl..."
    if command -v xurl >/dev/null 2>&1 || [ -x "$HOME/.local/bin/xurl" ]; then
        XURL_PATH=$(command -v xurl 2>/dev/null || echo "$HOME/.local/bin/xurl")
        echo "  Found: $XURL_PATH"
        return 0
    fi
    warn "xurl not found."
    echo "  Install from: https://github.com/shane-farkas/xurl"
    return 1
}

# Check X auth
check_xauth() {
    step "Checking X authentication..."
    XURL_BIN=$(command -v xurl 2>/dev/null || echo "$HOME/.local/bin/xurl")
    if [ -x "$XURL_BIN" ]; then
        if "$XURL_BIN" whoami >/dev/null 2>&1; then
            USER_INFO=$("$XURL_BIN" whoami 2>&1 | head -3)
            echo "  Authenticated: $USER_INFO"
            return 0
        fi
    fi
    warn "X auth not configured."
    echo "  Run: xurl auth login"
    return 1
}

# Check Together API key (optional, for dashboard's on-demand LLM features)
check_together() {
    if [ -n "$TOGETHER_API_KEY" ]; then
        echo "  Together API key: configured (TOGETHER_API_KEY)"
        return 0
    fi
    echo "  Together API key: not set (optional, needed only for dashboard's LLM reply generation)"
    return 0
}

# Install for Hermes
install_hermes() {
    step "Installing for Hermes Agent..."
    mkdir -p "$HERMES_SKILL_DIR/references"
    cp SKILL.md "$HERMES_SKILL_DIR/SKILL.md"
    cp search.py "$HERMES_SKILL_DIR/search.py"
    cp server.py "$HERMES_SKILL_DIR/server.py"
    cp references/*.md "$HERMES_SKILL_DIR/references/"
    echo "  Installed to: $HERMES_SKILL_DIR"
}

# Install for non-Hermes agents
install_generic() {
    step "Installing scripts in current directory..."
    mkdir -p references
    cp search.py ./search.py
    cp server.py ./server.py
    cp references/*.md ./references/
    echo "  Scripts installed to: ./"
    echo ""
    echo "  To use with your agent, point it at:"
    echo "    ./search.py        (search + filter pipeline)"
    echo "    ./server.py        (web dashboard, port 8080)"
    echo ""
    echo "  See README.md and references/ for usage details."
}

# Main
main() {
    echo ""
    printf "${BOLD}x-reply-radar installer${RESET}\n"
    echo "======================"
    echo ""

    AGENT=$(detect_agent)
    step "Detected agent: $AGENT"

    check_python || exit 1
    echo ""
    check_xurl || true
    echo ""
    check_xauth || true
    echo ""
    step "Checking optional dependencies..."
    check_together
    echo ""

    if [ "$AGENT" = "hermes" ]; then
        install_hermes
    else
        install_generic
    fi

    echo ""
    step "Installation complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Set environment variables (recommended):"
    echo "     export XURL=\"\$HOME/.local/bin/xurl\""
    echo "     export X_REPLY_RADAR_DIR=\"\$HOME/.x-reply-radar\""
    echo "     export X_REPLY_RADAR_MY_ID=\"your-x-user-id\""
    echo "     export TOGETHER_API_KEY=\"...\"   # optional, for dashboard LLM"
    echo ""
    echo "  2. Run a search:"
    echo "     python3 search.py"
    echo ""
    echo "  3. Start the dashboard:"
    echo "     python3 server.py"
    echo ""
    echo "  4. Query for engagement opportunities:"
    echo "     Tell your agent: 'find posts worth replying to about [topic]'"
    echo ""
}

main "$@"