#!/usr/bin/env bash
#
# Configure GitHub Actions Runner with Passwordless Sudo for Workspace Cleanup
#
# This script must be run as root on the runner machine to allow the runner
# user to clean up workspace directories without permission errors.
#
# Usage:
#   sudo bash configure_runner_sudo.sh <runner_user>
#
# Example:
#   sudo bash configure_runner_sudo.sh barberb
#   sudo bash configure_runner_sudo.sh devel
#

set -euo pipefail

RUNNER_USER="${1:-}"

if [ -z "$RUNNER_USER" ]; then
    echo "ERROR: Runner user not specified"
    echo "Usage: sudo bash $0 <runner_user>"
    echo "Example: sudo bash $0 barberb"
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    echo "Run: sudo bash $0 $RUNNER_USER"
    exit 1
fi

if ! id "$RUNNER_USER" &>/dev/null; then
    echo "ERROR: User '$RUNNER_USER' does not exist"
    exit 1
fi

echo "Configuring passwordless sudo for GitHub Actions runner user: $RUNNER_USER"

# Create sudoers configuration
SUDOERS_FILE="/etc/sudoers.d/github-runner-$RUNNER_USER"

cat > "$SUDOERS_FILE" <<EOF
# GitHub Actions Runner - Workspace Cleanup Permissions
# Created: $(date)
# This allows the runner to clean up workspace directories without permission errors

# Allow rm command for workspace cleanup
$RUNNER_USER ALL=(ALL) NOPASSWD: /bin/rm, /usr/bin/rm

# Allow chown for fixing file ownership
$RUNNER_USER ALL=(ALL) NOPASSWD: /bin/chown, /usr/bin/chown

# Allow chmod for fixing file permissions
$RUNNER_USER ALL=(ALL) NOPASSWD: /bin/chmod, /usr/bin/chmod

# Optional: Allow find for cleanup (if needed)
$RUNNER_USER ALL=(ALL) NOPASSWD: /usr/bin/find
EOF

# Set correct permissions
chmod 0440 "$SUDOERS_FILE"

# Validate syntax
if visudo -c -f "$SUDOERS_FILE"; then
    echo "✅ Sudoers configuration created successfully: $SUDOERS_FILE"
    echo ""
    echo "Configuration:"
    cat "$SUDOERS_FILE"
    echo ""
    echo "Test with:"
    echo "  sudo -u $RUNNER_USER sudo -n rm -rf /tmp/test_cleanup"
else
    echo "❌ ERROR: Invalid sudoers syntax, removing file"
    rm -f "$SUDOERS_FILE"
    exit 1
fi

echo ""
echo "✅ Configuration complete!"
echo ""
echo "The runner user '$RUNNER_USER' can now:"
echo "  - sudo rm -rf <directory>  (cleanup workspace)"
echo "  - sudo chown <user> <file>  (fix ownership)"
echo "  - sudo chmod <mode> <file>  (fix permissions)"
echo ""
echo "This will prevent permission errors in GitHub Actions workflows."
