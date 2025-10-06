#!/bin/bash
# Complete deployment script for IPFS Datasets MCP Server and Dashboard in Kubernetes

set -e

# Configuration
NAMESPACE="ipfs-datasets-mcp"
DOCKER_IMAGE="ipfs-datasets-mcp-standalone"
DOCKER_TAG="latest"
KUBECONFIG_PATH=${KUBECONFIG:-~/.kube/config}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if kubectl is installed
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed. Please install kubectl first."
        exit 1
    fi
    
    # Check if docker is installed
    if ! command -v docker &> /dev/null; then
        log_error "docker is not installed. Please install docker first."
        exit 1
    fi
    
    # Check kubectl connection to cluster
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Please check your kubeconfig."
        exit 1
    fi
    
    # Check if metrics-server is available for HPA
    if ! kubectl get apiservice v1beta1.metrics.k8s.io &> /dev/null; then
        log_warning "Metrics server not found. HPA may not work properly."
        log_info "To install metrics server: kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
    fi
    
    log_success "Prerequisites check completed"
}

# Build Docker image
build_docker_image() {
    log_info "Building Docker image: ${DOCKER_IMAGE}:${DOCKER_TAG}"
    
    if docker build -f ipfs_datasets_py/mcp_server/Dockerfile.standalone -t ${DOCKER_IMAGE}:${DOCKER_TAG} .; then
        log_success "Docker image built successfully"
    else
        log_error "Failed to build Docker image"
        exit 1
    fi
}

# Create namespace
create_namespace() {
    log_info "Creating namespace: ${NAMESPACE}"
    
    if kubectl get namespace ${NAMESPACE} &> /dev/null; then
        log_warning "Namespace ${NAMESPACE} already exists"
    else
        kubectl create namespace ${NAMESPACE}
        kubectl label namespace ${NAMESPACE} name=${NAMESPACE}
        log_success "Namespace ${NAMESPACE} created"
    fi
}

# Deploy to Kubernetes
deploy_kubernetes() {
    log_info "Deploying to Kubernetes..."
    
    # Apply ConfigMap and Secrets first
    kubectl apply -f deployments/kubernetes/mcp-deployment.yaml
    
    # Wait for deployments to be ready
    log_info "Waiting for deployments to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/mcp-server -n ${NAMESPACE}
    kubectl wait --for=condition=available --timeout=300s deployment/mcp-dashboard -n ${NAMESPACE}
    
    log_success "Deployments are ready"
}

# Deploy ingress
deploy_ingress() {
    log_info "Deploying ingress..."
    
    # Check if ingress-nginx is installed
    if ! kubectl get namespace ingress-nginx &> /dev/null; then
        log_warning "ingress-nginx not found. Installing..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
        
        # Wait for ingress controller to be ready
        kubectl wait --namespace ingress-nginx \
            --for=condition=ready pod \
            --selector=app.kubernetes.io/component=controller \
            --timeout=120s
    fi
    
    # Apply ingress configuration
    kubectl apply -f deployments/kubernetes/mcp-ingress.yaml
    
    log_success "Ingress deployed"
}

# Test deployment
test_deployment() {
    log_info "Testing deployment..."
    
    # Get service endpoints
    MCP_SERVER_IP=$(kubectl get service mcp-server-service -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')
    MCP_DASHBOARD_IP=$(kubectl get service mcp-dashboard-service -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')
    
    # Port forward for testing
    log_info "Setting up port forwarding for testing..."
    kubectl port-forward service/mcp-server-service 8000:8000 -n ${NAMESPACE} &
    SERVER_PF_PID=$!
    kubectl port-forward service/mcp-dashboard-service 8080:8080 -n ${NAMESPACE} &
    DASHBOARD_PF_PID=$!
    
    # Wait for port forwarding to be ready
    sleep 5
    
    # Test MCP server
    log_info "Testing MCP server health..."
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        log_success "MCP server is healthy"
    else
        log_error "MCP server health check failed"
    fi
    
    # Test MCP dashboard
    log_info "Testing MCP dashboard health..."
    if curl -f http://localhost:8080/health > /dev/null 2>&1; then
        log_success "MCP dashboard is healthy"
    else
        log_error "MCP dashboard health check failed"
    fi
    
    # Test MCP tools
    log_info "Testing MCP tools endpoint..."
    if curl -f http://localhost:8000/tools > /dev/null 2>&1; then
        log_success "MCP tools endpoint is working"
    else
        log_error "MCP tools endpoint failed"
    fi
    
    # Clean up port forwarding
    kill $SERVER_PF_PID $DASHBOARD_PF_PID 2>/dev/null || true
    
    log_success "Deployment testing completed"
}

# Show deployment status
show_status() {
    log_info "Deployment Status:"
    echo ""
    
    # Show pods
    echo "Pods:"
    kubectl get pods -n ${NAMESPACE} -o wide
    echo ""
    
    # Show services
    echo "Services:"
    kubectl get services -n ${NAMESPACE} -o wide
    echo ""
    
    # Show HPA status
    echo "Horizontal Pod Autoscalers:"
    kubectl get hpa -n ${NAMESPACE}
    echo ""
    
    # Show ingress
    echo "Ingress:"
    kubectl get ingress -n ${NAMESPACE}
    echo ""
    
    # Show resource usage
    echo "Resource Usage:"
    kubectl top pods -n ${NAMESPACE} 2>/dev/null || log_warning "Metrics server not available for resource usage"
    echo ""
}

# Scale deployment
scale_deployment() {
    local component=$1
    local replicas=$2
    
    if [[ -z "$component" || -z "$replicas" ]]; then
        log_error "Usage: $0 scale <component> <replicas>"
        log_info "Components: server, dashboard"
        exit 1
    fi
    
    case $component in
        server)
            log_info "Scaling MCP server to ${replicas} replicas..."
            kubectl scale deployment mcp-server --replicas=${replicas} -n ${NAMESPACE}
            ;;
        dashboard)
            log_info "Scaling MCP dashboard to ${replicas} replicas..."
            kubectl scale deployment mcp-dashboard --replicas=${replicas} -n ${NAMESPACE}
            ;;
        *)
            log_error "Unknown component: ${component}"
            log_info "Available components: server, dashboard"
            exit 1
            ;;
    esac
    
    log_success "Scaling initiated"
}

# Cleanup deployment
cleanup() {
    log_info "Cleaning up deployment..."
    
    # Delete ingress
    kubectl delete -f deployments/kubernetes/mcp-ingress.yaml --ignore-not-found=true
    
    # Delete main deployment
    kubectl delete -f deployments/kubernetes/mcp-deployment.yaml --ignore-not-found=true
    
    # Delete namespace (optional - comment out if you want to keep it)
    # kubectl delete namespace ${NAMESPACE} --ignore-not-found=true
    
    log_success "Cleanup completed"
}

# Show help
show_help() {
    echo "IPFS Datasets MCP Kubernetes Deployment Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  deploy          - Full deployment (build, create namespace, deploy, test)"
    echo "  build           - Build Docker image only"
    echo "  create-ns       - Create namespace only"
    echo "  deploy-k8s      - Deploy to Kubernetes only"
    echo "  deploy-ingress  - Deploy ingress only"
    echo "  test            - Test deployment"
    echo "  status          - Show deployment status"
    echo "  scale <component> <replicas> - Scale deployment"
    echo "  cleanup         - Clean up deployment"
    echo "  help            - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 deploy                    # Full deployment"
    echo "  $0 scale server 5            # Scale server to 5 replicas"
    echo "  $0 scale dashboard 2         # Scale dashboard to 2 replicas"
    echo "  $0 status                    # Show current status"
    echo ""
}

# Main execution
main() {
    case ${1:-help} in
        deploy)
            check_prerequisites
            build_docker_image
            create_namespace
            deploy_kubernetes
            deploy_ingress
            test_deployment
            show_status
            log_success "Full deployment completed!"
            ;;
        build)
            check_prerequisites
            build_docker_image
            ;;
        create-ns)
            check_prerequisites
            create_namespace
            ;;
        deploy-k8s)
            check_prerequisites
            create_namespace
            deploy_kubernetes
            ;;
        deploy-ingress)
            check_prerequisites
            deploy_ingress
            ;;
        test)
            check_prerequisites
            test_deployment
            ;;
        status)
            check_prerequisites
            show_status
            ;;
        scale)
            check_prerequisites
            scale_deployment $2 $3
            ;;
        cleanup)
            check_prerequisites
            cleanup
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"