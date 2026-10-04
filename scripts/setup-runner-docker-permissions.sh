#!/bin/bash
# setup-runner-docker-permissions.sh
# Automated script to fix Docker permission issues for GitHub Actions self-hosted runners

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to find runner services
find_runner_services() {
    systemctl list-units --type=service --all | grep -E "(actions\.runner|github.*runner)" | awk '{print $1}' | grep -v "@" || true
}

# Function to get runner user for a service
get_runner_user() {
    local service=$1
    systemctl show -p User "$service" --value 2>/dev/null || echo ""
}

# Main setup function
setup_docker_permissions() {
    print_status "Starting Docker permission setup for GitHub Actions runners..."
    
    # Check if running as root or with sudo
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo privileges"
        exit 1
    fi
    
    # Check if Docker is installed
    if ! command_exists docker; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check if Docker service is running
    if ! systemctl is-active --quiet docker; then
        print_status "Starting Docker service..."
        systemctl start docker
        systemctl enable docker
    fi
    
    # Find runner services
    print_status "Searching for GitHub Actions runner services..."
    RUNNER_SERVICES=$(find_runner_services)
    
    if [[ -z "$RUNNER_SERVICES" ]]; then
        print_warning "No GitHub Actions runner services found."
        print_status "Checking for common runner users..."
        
        # Check common runner usernames
        COMMON_USERS=("github-runner" "actions-runner" "runner" "$SUDO_USER")
        for user in "${COMMON_USERS[@]}"; do
            if id "$user" >/dev/null 2>&1; then
                print_status "Found user: $user"
                setup_user_docker_access "$user"
            fi
        done
    else
        print_success "Found runner services: $RUNNER_SERVICES"
        
        # Process each runner service
        for service in $RUNNER_SERVICES; do
            print_status "Processing service: $service"
            
            RUNNER_USER=$(get_runner_user "$service")
            if [[ -n "$RUNNER_USER" && "$RUNNER_USER" != "root" ]]; then
                print_status "Runner user for $service: $RUNNER_USER"
                setup_user_docker_access "$RUNNER_USER"
                restart_runner_service "$service"
            else
                print_warning "Could not determine user for service $service"
            fi
        done
    fi
    
    # Verify Docker socket permissions
    verify_docker_setup
    
    print_success "Docker permission setup completed!"
    print_status "You may need to manually restart runner services if they're still failing."
}

# Function to setup Docker access for a specific user
setup_user_docker_access() {
    local user=$1
    
    print_status "Setting up Docker access for user: $user"
    
    # Check if user exists
    if ! id "$user" >/dev/null 2>&1; then
        print_error "User $user does not exist"
        return 1
    fi
    
    # Add user to docker group
    if ! groups "$user" | grep -q docker; then
        print_status "Adding $user to docker group..."
        usermod -aG docker "$user"
        print_success "Added $user to docker group"
    else
        print_status "User $user is already in docker group"
    fi
    
    # Test Docker access for user
    if sudo -u "$user" docker ps >/dev/null 2>&1; then
        print_success "Docker access working for $user"
    else
        print_warning "Docker access test failed for $user - may need service restart"
    fi
}

# Function to restart runner service
restart_runner_service() {
    local service=$1
    
    print_status "Restarting runner service: $service"
    
    if systemctl restart "$service"; then
        print_success "Successfully restarted $service"
    else
        print_error "Failed to restart $service"
    fi
    
    # Wait a moment and check status
    sleep 2
    if systemctl is-active --quiet "$service"; then
        print_success "Service $service is running"
    else
        print_warning "Service $service may not be running properly"
    fi
}

# Function to verify Docker setup
verify_docker_setup() {
    print_status "Verifying Docker setup..."
    
    # Check Docker socket permissions
    SOCKET_PERMS=$(ls -la /var/run/docker.sock)
    print_status "Docker socket permissions: $SOCKET_PERMS"
    
    # Check docker group
    if getent group docker >/dev/null 2>&1; then
        DOCKER_GROUP_MEMBERS=$(getent group docker | cut -d: -f4)
        print_status "Docker group members: $DOCKER_GROUP_MEMBERS"
    else
        print_error "Docker group not found"
    fi
    
    # Test basic Docker functionality
    if docker version >/dev/null 2>&1; then
        print_success "Docker daemon is accessible"
    else
        print_error "Docker daemon is not accessible"
    fi
}

# Function to create systemd service override
create_service_override() {
    local service=$1
    local user=$2
    
    print_status "Creating systemd override for $service to ensure docker group membership"
    
    SERVICE_OVERRIDE_DIR="/etc/systemd/system/${service}.d"
    mkdir -p "$SERVICE_OVERRIDE_DIR"
    
    cat > "$SERVICE_OVERRIDE_DIR/docker-group.conf" << EOF
[Service]
SupplementaryGroups=docker
EOF
    
    systemctl daemon-reload
    print_success "Created systemd override for $service"
}

# Function to show diagnostic information
show_diagnostics() {
    print_status "=== Docker Permission Diagnostics ==="
    
    echo "Docker version:"
    docker --version || echo "Docker not accessible"
    
    echo -e "\nDocker socket permissions:"
    ls -la /var/run/docker.sock
    
    echo -e "\nDocker group:"
    getent group docker || echo "Docker group not found"
    
    echo -e "\nRunner services:"
    find_runner_services || echo "No runner services found"
    
    echo -e "\nDocker service status:"
    systemctl status docker --no-pager -l || echo "Docker service status unavailable"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --diagnostics    Show diagnostic information only"
    echo "  --user USER      Setup Docker access for specific user"
    echo "  --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0                              # Auto-detect and fix all runners"
    echo "  sudo $0 --user github-runner        # Fix specific user"
    echo "  sudo $0 --diagnostics               # Show diagnostics only"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --diagnostics)
            show_diagnostics
            exit 0
            ;;
        --user)
            SPECIFIC_USER="$2"
            shift 2
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
if [[ -n "$SPECIFIC_USER" ]]; then
    # Setup for specific user
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo privileges"
        exit 1
    fi
    setup_user_docker_access "$SPECIFIC_USER"
else
    # Full setup
    setup_docker_permissions
fi