#!/usr/bin/env bash
# GraphRAG System Deployment Automation Script
# Supports multiple environments and deployment strategies

set -e

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default values
ENVIRONMENT="development"
DEPLOYMENT_TYPE="docker-compose"
BUILD_IMAGES="false"
INIT_DB="false"
VERBOSE="false"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    cat << EOF
GraphRAG System Deployment Script

Usage: $0 [OPTIONS]

Options:
    -e, --environment ENV       Deployment environment (development, staging, production)
    -t, --type TYPE            Deployment type (docker-compose, kubernetes)
    -b, --build               Build Docker images before deployment
    -i, --init-db             Initialize database after deployment
    -v, --verbose             Enable verbose output
    -h, --help                Show this help message

Examples:
    # Development deployment with Docker Compose
    $0 -e development -t docker-compose -b -i

    # Production deployment to Kubernetes
    $0 -e production -t kubernetes

    # Staging with database initialization
    $0 -e staging -t kubernetes -i

Environments:
    development: Local development with minimal resources
    staging:     Staging environment with production-like setup
    production:  Full production deployment with high availability

Deployment Types:
    docker-compose: Local deployment using Docker Compose
    kubernetes:     Kubernetes cluster deployment with auto-scaling
EOF
}

check_prerequisites() {
    log_info "Checking prerequisites for $DEPLOYMENT_TYPE deployment..."
    
    case "$DEPLOYMENT_TYPE" in
        "docker-compose")
            if ! command -v docker &> /dev/null; then
                log_error "Docker is not installed or not in PATH"
                exit 1
            fi
            
            if ! command -v docker-compose &> /dev/null; then
                log_error "Docker Compose is not installed or not in PATH"
                exit 1
            fi
            
            log_success "Docker and Docker Compose are available"
            ;;
            
        "kubernetes")
            if ! command -v kubectl &> /dev/null; then
                log_error "kubectl is not installed or not in PATH"
                exit 1
            fi
            
            # Check if kubectl can connect to cluster
            if ! kubectl cluster-info &> /dev/null; then
                log_error "Cannot connect to Kubernetes cluster"
                exit 1
            fi
            
            log_success "Kubernetes cluster is accessible"
            ;;
    esac
}

setup_environment() {
    log_info "Setting up environment: $ENVIRONMENT"
    
    cd "$PROJECT_ROOT"
    
    # Copy environment template if not exists
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            log_warning "Created .env from template. Please review and update the configuration."
        else
            log_error ".env.example not found. Cannot create environment configuration."
            exit 1
        fi
    fi
    
    # Source environment variables
    if [ -f ".env" ]; then
        set -a
        source .env
        set +a
        log_success "Environment variables loaded"
    fi
}

build_images() {
    if [ "$BUILD_IMAGES" = "true" ]; then
        log_info "Building Docker images..."
        cd "$PROJECT_ROOT"
        
        case "$DEPLOYMENT_TYPE" in
            "docker-compose")
                docker-compose build
                ;;
            "kubernetes")
                # Build and tag for registry
                docker build -t ipfs-datasets-py:latest .
                
                # If we have a registry configured, push the image
                if [ ! -z "$DOCKER_REGISTRY" ]; then
                    docker tag ipfs-datasets-py:latest "$DOCKER_REGISTRY/ipfs-datasets-py:latest"
                    docker push "$DOCKER_REGISTRY/ipfs-datasets-py:latest"
                    log_success "Image pushed to registry: $DOCKER_REGISTRY/ipfs-datasets-py:latest"
                fi
                ;;
        esac
        
        log_success "Docker images built successfully"
    fi
}

deploy_docker_compose() {
    log_info "Deploying with Docker Compose..."
    cd "$PROJECT_ROOT"
    
    # Start services
    docker-compose up -d
    
    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    docker-compose exec postgres pg_isready -U graphrag_user -d graphrag_db || sleep 10
    docker-compose exec redis redis-cli ping || sleep 5
    
    log_success "Docker Compose deployment completed"
    
    # Show service status
    docker-compose ps
}

deploy_kubernetes() {
    log_info "Deploying to Kubernetes..."
    cd "$PROJECT_ROOT"
    
    # Create namespace if not exists
    kubectl create namespace graphrag-system --dry-run=client -o yaml | kubectl apply -f -
    
    # Check if secrets exist, create if needed
    if ! kubectl get secret db-credentials -n graphrag-system &> /dev/null; then
        log_warning "Database credentials secret not found. Please create it manually:"
        log_warning "kubectl create secret generic db-credentials --from-literal=postgres-password='your_password' --from-literal=postgres-url='postgresql://...' -n graphrag-system"
    fi
    
    if ! kubectl get secret api-keys -n graphrag-system &> /dev/null; then
        log_warning "API keys secret not found. Please create it manually:"
        log_warning "kubectl create secret generic api-keys --from-literal=openai-api-key='your_key' --from-literal=huggingface-token='your_token' -n graphrag-system"
    fi
    
    # Deploy infrastructure (databases, caches)
    kubectl apply -f deployments/kubernetes/infrastructure.yaml
    
    # Wait for infrastructure to be ready
    log_info "Waiting for infrastructure to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/postgres -n graphrag-system
    kubectl wait --for=condition=available --timeout=300s deployment/redis -n graphrag-system
    
    # Deploy application
    kubectl apply -f deployments/kubernetes/graphrag-deployment.yaml
    
    # Wait for application to be ready
    log_info "Waiting for application to be ready..."
    kubectl wait --for=condition=available --timeout=600s deployment/website-graphrag-processor -n graphrag-system
    
    # Setup ingress
    kubectl apply -f deployments/kubernetes/ingress.yaml
    
    log_success "Kubernetes deployment completed"
    
    # Show deployment status
    kubectl get pods -n graphrag-system
    kubectl get services -n graphrag-system
    kubectl get ingress -n graphrag-system
}

init_database() {
    if [ "$INIT_DB" = "true" ]; then
        log_info "Initializing database..."
        
        case "$DEPLOYMENT_TYPE" in
            "docker-compose")
                docker-compose exec website-graphrag-processor python -m ipfs_datasets_py.scripts.init_database --init
                ;;
            "kubernetes")
                kubectl exec -it deployment/website-graphrag-processor -n graphrag-system -- python -m ipfs_datasets_py.scripts.init_database --init
                ;;
        esac
        
        log_success "Database initialized successfully"
    fi
}

run_health_checks() {
    log_info "Running health checks..."
    
    case "$DEPLOYMENT_TYPE" in
        "docker-compose")
            # Check if all services are healthy
            if docker-compose ps | grep -q "unhealthy\|Exit"; then
                log_error "Some services are not healthy"
                docker-compose ps
                exit 1
            fi
            
            # Test API endpoint
            if curl -f http://localhost:8000/health &> /dev/null; then
                log_success "API health check passed"
            else
                log_error "API health check failed"
                exit 1
            fi
            ;;
            
        "kubernetes")
            # Check pod status
            if kubectl get pods -n graphrag-system | grep -v Running; then
                log_warning "Some pods are not running"
                kubectl get pods -n graphrag-system
            fi
            
            # Get ingress URL
            INGRESS_URL=$(kubectl get ingress graphrag-ingress -n graphrag-system -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || echo "localhost")
            
            # Test API endpoint
            if curl -f "http://$INGRESS_URL/health" &> /dev/null; then
                log_success "API health check passed"
            else
                log_warning "API health check failed (might be normal if ingress is not ready)"
            fi
            ;;
    esac
}

show_deployment_info() {
    log_info "Deployment Information:"
    echo "========================"
    echo "Environment: $ENVIRONMENT"
    echo "Deployment Type: $DEPLOYMENT_TYPE"
    echo "Project Root: $PROJECT_ROOT"
    echo ""
    
    case "$DEPLOYMENT_TYPE" in
        "docker-compose")
            echo "Services:"
            echo "- GraphRAG API: http://localhost:8000"
            echo "- Grafana Dashboard: http://localhost:3000 (admin/admin)"
            echo "- Prometheus: http://localhost:9090"
            echo ""
            echo "To stop: docker-compose down"
            echo "To view logs: docker-compose logs -f"
            ;;
            
        "kubernetes")
            echo "Namespace: graphrag-system"
            echo "Services:"
            kubectl get services -n graphrag-system
            echo ""
            echo "Ingress:"
            kubectl get ingress -n graphrag-system
            echo ""
            echo "To check logs: kubectl logs -f deployment/website-graphrag-processor -n graphrag-system"
            echo "To scale: kubectl scale deployment website-graphrag-processor --replicas=5 -n graphrag-system"
            ;;
    esac
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -t|--type)
                DEPLOYMENT_TYPE="$2"
                shift 2
                ;;
            -b|--build)
                BUILD_IMAGES="true"
                shift
                ;;
            -i|--init-db)
                INIT_DB="true"
                shift
                ;;
            -v|--verbose)
                VERBOSE="true"
                set -x
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    log_info "Starting GraphRAG System deployment..."
    log_info "Environment: $ENVIRONMENT, Type: $DEPLOYMENT_TYPE"
    
    # Run deployment steps
    check_prerequisites
    setup_environment
    build_images
    
    case "$DEPLOYMENT_TYPE" in
        "docker-compose")
            deploy_docker_compose
            ;;
        "kubernetes")
            deploy_kubernetes
            ;;
        *)
            log_error "Unknown deployment type: $DEPLOYMENT_TYPE"
            exit 1
            ;;
    esac
    
    init_database
    run_health_checks
    show_deployment_info
    
    log_success "GraphRAG System deployment completed successfully!"
}

# Run main function
main "$@"