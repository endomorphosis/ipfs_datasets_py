#!/bin/bash
# Setup GitHub CLI and Copilot CLI Authentication on Self-Hosted Runner
#
# This script configures persistent GitHub CLI and Copilot CLI authentication
# on self-hosted GitHub Actions runners. The authentication persists across
# workflow runs and system reboots.
#
# Usage:
#   sudo ./setup_gh_copilot_auth_on_runner.sh
#
# Requirements:
#   - Must be run as root (uses sudo)
#   - GitHub CLI must be installed
#   - A GitHub Personal Access Token with appropriate scopes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}║    GitHub CLI & Copilot Auth Setup for Self-Hosted        ║${NC}"
echo -e "${BLUE}║                   Runners                                  ║${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Configuration
RUNNER_USER="${RUNNER_USER:-runner}"
RUNNER_HOME="/home/${RUNNER_USER}"
GH_CONFIG_DIR="${RUNNER_HOME}/.config/gh"
GH_HOSTS_FILE="${GH_CONFIG_DIR}/hosts.yml"
ROOT_GH_CONFIG_DIR="/root/.config/gh"

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}❌ This script must be run as root (use sudo)${NC}"
        echo "Usage: sudo $0"
        exit 1
    fi
}

# Function to check if GitHub CLI is installed
check_gh_cli() {
    echo -e "${BLUE}📋 Checking GitHub CLI installation...${NC}"
    
    if command -v gh &> /dev/null; then
        GH_VERSION=$(gh --version | head -1)
        echo -e "${GREEN}✅ GitHub CLI is installed: ${GH_VERSION}${NC}"
        return 0
    else
        echo -e "${RED}❌ GitHub CLI is not installed${NC}"
        echo -e "${YELLOW}Would you like to install it now? (y/n)${NC}"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            install_gh_cli
        else
            echo -e "${RED}GitHub CLI is required. Exiting.${NC}"
            exit 1
        fi
    fi
}

# Function to install GitHub CLI
install_gh_cli() {
    echo -e "${BLUE}📥 Installing GitHub CLI...${NC}"
    
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
            dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
        
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
            tee /etc/apt/sources.list.d/github-cli.list > /dev/null
        
        apt-get update && apt-get install -y gh
    elif [ -f /etc/redhat-release ]; then
        # RedHat/CentOS
        dnf install -y 'dnf-command(config-manager)'
        dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
        dnf install -y gh
    else
        echo -e "${RED}❌ Unsupported OS. Please install GitHub CLI manually.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ GitHub CLI installed successfully${NC}"
}

# Function to prompt for GitHub token
prompt_for_token() {
    echo ""
    echo -e "${YELLOW}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  GitHub Personal Access Token Required                    ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}To create a token:${NC}"
    echo "1. Go to https://github.com/settings/tokens/new"
    echo "2. Give it a descriptive name (e.g., 'Self-hosted Runner Auth')"
    echo "3. Select the following scopes:"
    echo "   - repo (Full control of private repositories)"
    echo "   - workflow (Update GitHub Action workflows)"
    echo "   - write:packages (Upload packages to GitHub Package Registry)"
    echo "   - read:org (Read org and team membership)"
    echo "4. Click 'Generate token'"
    echo "5. Copy the token (you won't be able to see it again)"
    echo ""
    echo -e "${YELLOW}Enter your GitHub Personal Access Token:${NC}"
    read -s GITHUB_TOKEN
    echo ""
    
    if [ -z "$GITHUB_TOKEN" ]; then
        echo -e "${RED}❌ Token is required${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Token received${NC}"
}

# Function to configure GitHub CLI authentication for a user
configure_gh_auth() {
    local user=$1
    local user_home=$2
    local config_dir="${user_home}/.config/gh"
    local hosts_file="${config_dir}/hosts.yml"
    
    echo -e "${BLUE}⚙️  Configuring GitHub CLI for user: ${user}${NC}"
    
    # Create config directory
    mkdir -p "$config_dir"
    
    # Create hosts.yml file with token
    cat > "$hosts_file" << EOF
github.com:
    user: ""
    oauth_token: ${GITHUB_TOKEN}
    git_protocol: https
EOF
    
    # Set proper permissions
    chown -R ${user}:${user} "$config_dir" 2>/dev/null || true
    chmod 700 "$config_dir"
    chmod 600 "$hosts_file"
    
    echo -e "${GREEN}✅ GitHub CLI configured for user: ${user}${NC}"
}

# Function to verify authentication
verify_auth() {
    local user=$1
    local user_home=$2
    
    echo -e "${BLUE}🔍 Verifying authentication for user: ${user}...${NC}"
    
    # Test as the target user
    if sudo -u "$user" -H bash -c "cd ${user_home} && gh auth status" &> /dev/null; then
        echo -e "${GREEN}✅ Authentication verified for user: ${user}${NC}"
        
        # Show authenticated user
        AUTH_USER=$(sudo -u "$user" -H bash -c "cd ${user_home} && gh api user --jq .login" 2>/dev/null || echo "unknown")
        echo -e "${GREEN}   Authenticated as: ${AUTH_USER}${NC}"
        return 0
    else
        echo -e "${RED}❌ Authentication verification failed for user: ${user}${NC}"
        return 1
    fi
}

# Function to install Copilot CLI extension
install_copilot_cli() {
    local user=$1
    local user_home=$2
    
    echo -e "${BLUE}🤖 Installing GitHub Copilot CLI extension for user: ${user}...${NC}"
    
    # Check if already installed
    if sudo -u "$user" -H bash -c "cd ${user_home} && gh extension list" 2>/dev/null | grep -q "github/gh-copilot"; then
        echo -e "${GREEN}✅ Copilot CLI already installed for user: ${user}${NC}"
        return 0
    fi
    
    # Install Copilot CLI extension
    if sudo -u "$user" -H bash -c "cd ${user_home} && gh extension install github/gh-copilot" &> /dev/null; then
        echo -e "${GREEN}✅ Copilot CLI installed successfully for user: ${user}${NC}"
    else
        echo -e "${YELLOW}⚠️  Could not install Copilot CLI for user: ${user}${NC}"
        echo -e "${YELLOW}   You may need to install it manually or verify your token has the right scopes${NC}"
        return 1
    fi
}

# Function to create systemwide git config for GH_TOKEN
setup_git_credential_helper() {
    echo -e "${BLUE}⚙️  Setting up git credential helper...${NC}"
    
    # Configure git to use the gh credential helper
    git config --system credential.helper ""
    git config --system credential.helper "!gh auth git-credential"
    
    echo -e "${GREEN}✅ Git credential helper configured${NC}"
}

# Function to create environment file for runner service
create_runner_env_file() {
    echo -e "${BLUE}⚙️  Creating environment file for runner service...${NC}"
    
    local runner_dir="/home/actions-runner"
    local env_file="${runner_dir}/.env"
    
    if [ ! -d "$runner_dir" ]; then
        echo -e "${YELLOW}⚠️  Runner directory not found at ${runner_dir}${NC}"
        echo -e "${YELLOW}   Skipping runner environment file creation${NC}"
        return 0
    fi
    
    # Create .env file
    cat > "$env_file" << EOF
# GitHub Authentication
GH_TOKEN=${GITHUB_TOKEN}
GITHUB_TOKEN=${GITHUB_TOKEN}

# Git configuration
GIT_CONFIG_GLOBAL=/dev/null
GIT_CONFIG_SYSTEM=/dev/null
EOF
    
    # Set permissions
    chown ${RUNNER_USER}:${RUNNER_USER} "$env_file"
    chmod 600 "$env_file"
    
    echo -e "${GREEN}✅ Runner environment file created: ${env_file}${NC}"
}

# Function to update runner service to load environment file
update_runner_service() {
    echo -e "${BLUE}⚙️  Updating runner service configuration...${NC}"
    
    local service_file=$(find /etc/systemd/system -name "actions.runner.*.service" 2>/dev/null | head -1)
    
    if [ -z "$service_file" ]; then
        echo -e "${YELLOW}⚠️  Runner service file not found${NC}"
        echo -e "${YELLOW}   Skipping service update${NC}"
        return 0
    fi
    
    echo -e "${BLUE}   Found service file: ${service_file}${NC}"
    
    # Check if EnvironmentFile is already configured
    if grep -q "EnvironmentFile=" "$service_file"; then
        echo -e "${GREEN}✅ Service already configured with EnvironmentFile${NC}"
        return 0
    fi
    
    # Backup service file
    cp "$service_file" "${service_file}.backup-$(date +%s)"
    
    # Add EnvironmentFile directive
    sed -i '/\[Service\]/a EnvironmentFile=-/home/actions-runner/.env' "$service_file"
    
    # Reload systemd
    systemctl daemon-reload
    
    echo -e "${GREEN}✅ Runner service updated${NC}"
    echo -e "${YELLOW}⚠️  You may need to restart the runner service:${NC}"
    echo -e "${YELLOW}   sudo systemctl restart $(basename $service_file)${NC}"
}

# Function to create verification script
create_verification_script() {
    echo -e "${BLUE}📝 Creating verification script...${NC}"
    
    local verify_script="/usr/local/bin/verify-gh-auth"
    
    cat > "$verify_script" << 'EOF'
#!/bin/bash
# Verification script for GitHub CLI authentication

echo "=== GitHub CLI Authentication Verification ==="
echo ""

# Test runner user
echo "Testing runner user authentication:"
if sudo -u runner -H bash -c "cd /home/runner && gh auth status"; then
    echo "✅ Runner user authentication OK"
else
    echo "❌ Runner user authentication FAILED"
fi

echo ""

# Test root user
echo "Testing root user authentication:"
if gh auth status &> /dev/null; then
    echo "✅ Root user authentication OK"
else
    echo "❌ Root user authentication FAILED"
fi

echo ""

# Test Copilot CLI
echo "Testing Copilot CLI extension:"
if sudo -u runner -H bash -c "cd /home/runner && gh extension list" | grep -q "gh-copilot"; then
    echo "✅ Copilot CLI extension installed"
else
    echo "❌ Copilot CLI extension NOT installed"
fi

echo ""
echo "=== Verification Complete ==="
EOF
    
    chmod +x "$verify_script"
    echo -e "${GREEN}✅ Verification script created: ${verify_script}${NC}"
}

# Main execution
main() {
    echo -e "${BLUE}Starting GitHub CLI & Copilot authentication setup...${NC}"
    echo ""
    
    # Check if root
    check_root
    
    # Check/install GitHub CLI
    check_gh_cli
    
    # Prompt for token
    prompt_for_token
    
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Configuring Authentication                               ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Configure for runner user
    configure_gh_auth "$RUNNER_USER" "$RUNNER_HOME"
    
    # Configure for root user
    configure_gh_auth "root" "/root"
    
    # Verify authentication
    echo ""
    verify_auth "$RUNNER_USER" "$RUNNER_HOME"
    verify_auth "root" "/root"
    
    # Install Copilot CLI
    echo ""
    install_copilot_cli "$RUNNER_USER" "$RUNNER_HOME"
    install_copilot_cli "root" "/root"
    
    # Setup git credential helper
    echo ""
    setup_git_credential_helper
    
    # Create runner environment file
    echo ""
    create_runner_env_file
    
    # Update runner service
    echo ""
    update_runner_service
    
    # Create verification script
    echo ""
    create_verification_script
    
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Setup Complete!                                          ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✅ GitHub CLI and Copilot authentication configured${NC}"
    echo ""
    echo -e "${YELLOW}Summary:${NC}"
    echo "- GitHub CLI authenticated for users: runner, root"
    echo "- Copilot CLI extension installed (if available)"
    echo "- Git credential helper configured"
    echo "- Runner environment file created"
    echo "- Runner service updated (may need restart)"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "1. Verify authentication: sudo verify-gh-auth"
    echo "2. Restart runner service (if needed):"
    echo "   sudo systemctl restart actions.runner.*.service"
    echo ""
    echo -e "${YELLOW}Testing Commands:${NC}"
    echo "  # As runner user:"
    echo "  sudo -u runner gh auth status"
    echo "  sudo -u runner gh api user"
    echo "  sudo -u runner gh extension list"
    echo ""
    echo "  # As root:"
    echo "  gh auth status"
    echo "  gh api user"
    echo ""
    echo -e "${GREEN}Authentication will persist across reboots and workflow runs!${NC}"
}

# Run main function
main
