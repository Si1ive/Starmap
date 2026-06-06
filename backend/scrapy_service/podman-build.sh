#!/bin/bash
# Podman build script for StarMap Scrapy Service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="starmap-scrapy"
IMAGE_TAG="latest"
REGISTRY="${REGISTRY:-localhost}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if podman is installed
check_podman() {
    if ! command -v podman &> /dev/null; then
        log_error "Podman is not installed. Please install Podman first."
        exit 1
    fi
    
    PODMAN_VERSION=$(podman --version)
    log_info "Found: $PODMAN_VERSION"
}

# Build image
build_image() {
    log_info "Building Podman image..."
    
    cd "$SCRIPT_DIR"
    
    podman build \
        -t "${PROJECT_NAME}:${IMAGE_TAG}" \
        -t "${REGISTRY}/${PROJECT_NAME}:${IMAGE_TAG}" \
        -f Dockerfile \
        .
    
    log_info "Image built successfully: ${PROJECT_NAME}:${IMAGE_TAG}"
}

# Run container
run_container() {
    log_info "Starting Scrapy service container..."
    
    # Check if container already exists
    if podman ps -a --format "{{.Names}}" | grep -q "^${PROJECT_NAME}$"; then
        log_warn "Container '${PROJECT_NAME}' already exists. Removing..."
        podman rm -f "${PROJECT_NAME}" || true
    fi
    
    # Run new container
    podman run -d \
        --name "${PROJECT_NAME}" \
        --network host \
        -e REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
        -e MYSQL_HOST="${MYSQL_HOST:-localhost}" \
        -e MYSQL_PORT="${MYSQL_PORT:-3306}" \
        -e MYSQL_USER="${MYSQL_USER:-starmap}" \
        -e MYSQL_PASSWORD="${MYSQL_PASSWORD:-starmap123}" \
        -e MYSQL_DATABASE="${MYSQL_DATABASE:-starmap}" \
        -e NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}" \
        -e NEO4J_USER="${NEO4J_USER:-neo4j}" \
        -e NEO4J_PASSWORD="${NEO4J_PASSWORD:-starmap123}" \
        -e LOG_LEVEL="${LOG_LEVEL:-INFO}" \
        -v "${SCRIPT_DIR}/logs:/app/logs" \
        "${PROJECT_NAME}:${IMAGE_TAG}"
    
    log_info "Container started: ${PROJECT_NAME}"
    log_info "View logs: podman logs -f ${PROJECT_NAME}"
}

# Stop container
stop_container() {
    log_info "Stopping Scrapy service container..."
    
    if podman ps --format "{{.Names}}" | grep -q "^${PROJECT_NAME}$"; then
        podman stop "${PROJECT_NAME}"
        log_info "Container stopped"
    else
        log_warn "Container '${PROJECT_NAME}' is not running"
    fi
}

# Remove container
remove_container() {
    log_info "Removing Scrapy service container..."
    
    if podman ps -a --format "{{.Names}}" | grep -q "^${PROJECT_NAME}$"; then
        podman rm -f "${PROJECT_NAME}"
        log_info "Container removed"
    else
        log_warn "Container '${PROJECT_NAME}' does not exist"
    fi
}

# Show status
show_status() {
    log_info "Container status:"
    podman ps -a --filter "name=${PROJECT_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
}

# Show logs
show_logs() {
    log_info "Showing logs..."
    podman logs -f "${PROJECT_NAME}"
}

# Push image to registry
push_image() {
    log_info "Pushing image to registry: ${REGISTRY}"
    
    podman push "${REGISTRY}/${PROJECT_NAME}:${IMAGE_TAG}"
    
    log_info "Image pushed successfully"
}

# Main
main() {
    case "${1:-build}" in
        build)
            check_podman
            build_image
            ;;
        run)
            check_podman
            run_container
            ;;
        start)
            check_podman
            build_image
            run_container
            ;;
        stop)
            stop_container
            ;;
        remove)
            remove_container
            ;;
        restart)
            stop_container
            sleep 2
            run_container
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs
            ;;
        push)
            push_image
            ;;
        help|--help|-h)
            echo "Usage: $0 {build|run|start|stop|remove|restart|status|logs|push}"
            echo ""
            echo "Commands:"
            echo "  build    - Build the Podman image"
            echo "  run      - Run the container (without rebuilding)"
            echo "  start    - Build and run the container"
            echo "  stop     - Stop the container"
            echo "  remove   - Remove the container"
            echo "  restart  - Restart the container"
            echo "  status   - Show container status"
            echo "  logs     - Show container logs"
            echo "  push     - Push image to registry"
            echo ""
            echo "Environment variables:"
            echo "  REDIS_URL       - Redis connection URL"
            echo "  MYSQL_HOST      - MySQL host"
            echo "  MYSQL_PORT      - MySQL port"
            echo "  MYSQL_USER      - MySQL user"
            echo "  MYSQL_PASSWORD  - MySQL password"
            echo "  MYSQL_DATABASE  - MySQL database"
            echo "  NEO4J_URI       - Neo4j URI"
            echo "  NEO4J_USER      - Neo4j user"
            echo "  NEO4J_PASSWORD  - Neo4j password"
            echo "  LOG_LEVEL       - Log level (DEBUG/INFO/WARNING/ERROR)"
            ;;
        *)
            log_error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

main "$@"
