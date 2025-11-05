#!/bin/bash
# Setup script for configuring self-hosted runner secrets
# This script helps set up secure secrets management on GitHub Actions runners

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SECRETS_DIR="/etc/github-runner-secrets"
SECRETS_FILE="${SECRETS_DIR}/secrets.json"
RUNNER_USER="${RUNNER_USER:-runner}"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}║    GitHub Self-Hosted Runner Secrets Setup                ║${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}❌ This script must be run as root (use sudo)${NC}"
        exit 1
    fi
}

# Function to create secrets directory
create_secrets_dir() {
    echo -e "${YELLOW}📁 Creating secrets directory...${NC}"
    
    if [ -d "$SECRETS_DIR" ]; then
        echo -e "${GREEN}✅ Directory already exists: $SECRETS_DIR${NC}"
    else
        mkdir -p "$SECRETS_DIR"
        echo -e "${GREEN}✅ Created directory: $SECRETS_DIR${NC}"
    fi
    
    # Set secure permissions
    chmod 700 "$SECRETS_DIR"
    echo -e "${GREEN}✅ Set directory permissions to 700${NC}"
}

# Function to prompt for API keys
prompt_for_secrets() {
    echo ""
    echo -e "${YELLOW}🔑 Enter your API keys${NC}"
    echo -e "${BLUE}Leave blank to skip any key${NC}"
    echo ""
    
    # OpenAI
    echo -e "${YELLOW}OpenAI API Key:${NC}"
    read -s OPENAI_KEY
    echo ""
    
    # Anthropic
    echo -e "${YELLOW}Anthropic API Key:${NC}"
    read -s ANTHROPIC_KEY
    echo ""
    
    # OpenRouter
    echo -e "${YELLOW}OpenRouter API Key:${NC}"
    read -s OPENROUTER_KEY
    echo ""
}

# Function to create secrets file
create_secrets_file() {
    echo -e "${YELLOW}📝 Creating secrets file...${NC}"
    
    # Build JSON
    cat > "$SECRETS_FILE" << EOF
{
EOF
    
    FIRST=true
    
    if [ -n "$OPENAI_KEY" ]; then
        if [ "$FIRST" = false ]; then
            echo "," >> "$SECRETS_FILE"
        fi
        echo "  \"OPENAI_API_KEY\": \"$OPENAI_KEY\"" >> "$SECRETS_FILE"
        FIRST=false
        echo -e "${GREEN}✅ Added OpenAI API key${NC}"
    fi
    
    if [ -n "$ANTHROPIC_KEY" ]; then
        if [ "$FIRST" = false ]; then
            echo "," >> "$SECRETS_FILE"
        fi
        echo "  \"ANTHROPIC_API_KEY\": \"$ANTHROPIC_KEY\"" >> "$SECRETS_FILE"
        FIRST=false
        echo -e "${GREEN}✅ Added Anthropic API key${NC}"
    fi
    
    if [ -n "$OPENROUTER_KEY" ]; then
        if [ "$FIRST" = false ]; then
            echo "," >> "$SECRETS_FILE"
        fi
        echo "  \"OPENROUTER_API_KEY\": \"$OPENROUTER_KEY\"" >> "$SECRETS_FILE"
        FIRST=false
        echo -e "${GREEN}✅ Added OpenRouter API key${NC}"
    fi
    
    echo "" >> "$SECRETS_FILE"
    echo "}" >> "$SECRETS_FILE"
    
    echo -e "${GREEN}✅ Created secrets file: $SECRETS_FILE${NC}"
}

# Function to secure the secrets file
secure_secrets_file() {
    echo -e "${YELLOW}🔒 Securing secrets file...${NC}"
    
    # Set owner
    chown "$RUNNER_USER:$RUNNER_USER" "$SECRETS_FILE"
    echo -e "${GREEN}✅ Set owner to $RUNNER_USER:$RUNNER_USER${NC}"
    
    # Set permissions
    chmod 600 "$SECRETS_FILE"
    echo -e "${GREEN}✅ Set file permissions to 600${NC}"
}

# Function to verify setup
verify_setup() {
    echo ""
    echo -e "${YELLOW}🔍 Verifying setup...${NC}"
    
    # Check directory permissions
    DIR_PERMS=$(stat -c %a "$SECRETS_DIR")
    if [ "$DIR_PERMS" = "700" ]; then
        echo -e "${GREEN}✅ Directory permissions correct: $DIR_PERMS${NC}"
    else
        echo -e "${RED}⚠️  Directory permissions: $DIR_PERMS (should be 700)${NC}"
    fi
    
    # Check file permissions
    FILE_PERMS=$(stat -c %a "$SECRETS_FILE")
    if [ "$FILE_PERMS" = "600" ]; then
        echo -e "${GREEN}✅ File permissions correct: $FILE_PERMS${NC}"
    else
        echo -e "${RED}⚠️  File permissions: $FILE_PERMS (should be 600)${NC}"
    fi
    
    # Check file owner
    FILE_OWNER=$(stat -c %U "$SECRETS_FILE")
    if [ "$FILE_OWNER" = "$RUNNER_USER" ]; then
        echo -e "${GREEN}✅ File owner correct: $FILE_OWNER${NC}"
    else
        echo -e "${RED}⚠️  File owner: $FILE_OWNER (should be $RUNNER_USER)${NC}"
    fi
    
    # Validate JSON
    if python3 -c "import json; json.load(open('$SECRETS_FILE'))" 2>/dev/null; then
        echo -e "${GREEN}✅ JSON syntax valid${NC}"
    else
        echo -e "${RED}❌ Invalid JSON in secrets file${NC}"
        return 1
    fi
    
    # Test loading secrets
    echo ""
    echo -e "${YELLOW}Testing secrets loading...${NC}"
    if sudo -u "$RUNNER_USER" python3 scripts/load_runner_secrets.py --check 2>/dev/null; then
        echo -e "${GREEN}✅ Secrets can be loaded successfully${NC}"
    else
        echo -e "${RED}❌ Failed to load secrets${NC}"
        return 1
    fi
}

# Function to show summary
show_summary() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}║                    Setup Complete!                         ║${NC}"
    echo -e "${BLUE}║                                                            ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✅ Secrets are now securely stored on this runner${NC}"
    echo ""
    echo -e "${YELLOW}📋 Next steps:${NC}"
    echo "1. Your workflows will automatically load these secrets"
    echo "2. No need to configure GitHub repository secrets"
    echo "3. To update secrets, run this script again or edit:"
    echo "   $SECRETS_FILE"
    echo ""
    echo -e "${YELLOW}📚 Documentation:${NC}"
    echo "- Setup guide: .github/workflows/SECRETS-MANAGEMENT.md"
    echo "- Secrets manager: scripts/load_runner_secrets.py"
    echo ""
    echo -e "${YELLOW}🔒 Security notes:${NC}"
    echo "- Secrets are only accessible to the runner user"
    echo "- Secrets are never exposed in GitHub UI or logs"
    echo "- File permissions prevent unauthorized access"
    echo ""
}

# Main execution
main() {
    check_root
    
    echo -e "${YELLOW}This script will set up secure secrets management for your self-hosted runner.${NC}"
    echo ""
    echo -e "${BLUE}Current configuration:${NC}"
    echo "  Secrets directory: $SECRETS_DIR"
    echo "  Secrets file: $SECRETS_FILE"
    echo "  Runner user: $RUNNER_USER"
    echo ""
    
    # Check if secrets file exists
    if [ -f "$SECRETS_FILE" ]; then
        echo -e "${YELLOW}⚠️  Secrets file already exists!${NC}"
        echo -e "${YELLOW}Do you want to overwrite it? (y/N):${NC}"
        read -r OVERWRITE
        if [ "$OVERWRITE" != "y" ] && [ "$OVERWRITE" != "Y" ]; then
            echo -e "${BLUE}Setup cancelled. Existing secrets preserved.${NC}"
            exit 0
        fi
    fi
    
    create_secrets_dir
    prompt_for_secrets
    
    # Check if any secrets were provided
    if [ -z "$OPENAI_KEY" ] && [ -z "$ANTHROPIC_KEY" ] && [ -z "$OPENROUTER_KEY" ]; then
        echo -e "${RED}❌ No API keys provided. Setup cancelled.${NC}"
        exit 1
    fi
    
    create_secrets_file
    secure_secrets_file
    
    if verify_setup; then
        show_summary
        exit 0
    else
        echo -e "${RED}❌ Setup verification failed. Please check the errors above.${NC}"
        exit 1
    fi
}

# Run main function
main
