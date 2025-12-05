#!/bin/bash

# CVAT Image Selector - Docker Run Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  CVAT Image Selector - Docker"
echo "========================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

# Determine which docker compose command to use
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo "Error: Neither 'docker-compose' nor 'docker compose' is available."
    echo "Please install Docker Compose."
    exit 1
fi

echo -e "${YELLOW}Using: $COMPOSE_CMD${NC}"
echo ""

# Parse command line arguments
ACTION=${1:-"up"}

case $ACTION in
    build)
        echo -e "${YELLOW}Building Docker image...${NC}"
        $COMPOSE_CMD build
        echo -e "${GREEN}Build complete!${NC}"
        ;;
    up|start)
        echo -e "${YELLOW}Starting container on port 1504...${NC}"
        $COMPOSE_CMD up -d
        echo ""
        echo -e "${GREEN}Container started!${NC}"
        echo "Access the application at: http://localhost:1504"
        echo ""
        echo "To view logs: ./docker-run.sh logs"
        echo "To stop: ./docker-run.sh stop"
        ;;
    down|stop)
        echo -e "${YELLOW}Stopping container...${NC}"
        $COMPOSE_CMD down
        echo -e "${GREEN}Container stopped.${NC}"
        ;;
    restart)
        echo -e "${YELLOW}Restarting container...${NC}"
        $COMPOSE_CMD restart
        echo -e "${GREEN}Container restarted.${NC}"
        ;;
    logs)
        $COMPOSE_CMD logs -f
        ;;
    status)
        $COMPOSE_CMD ps
        ;;
    rebuild)
        echo -e "${YELLOW}Rebuilding and restarting container...${NC}"
        $COMPOSE_CMD down
        $COMPOSE_CMD build --no-cache
        $COMPOSE_CMD up -d
        echo -e "${GREEN}Container rebuilt and started!${NC}"
        echo "Access the application at: http://localhost:1504"
        ;;
    *)
        echo "Usage: $0 {build|start|stop|restart|logs|status|rebuild}"
        echo ""
        echo "Commands:"
        echo "  build    - Build the Docker image"
        echo "  start    - Start the container (default)"
        echo "  stop     - Stop the container"
        echo "  restart  - Restart the container"
        echo "  logs     - View container logs"
        echo "  status   - Show container status"
        echo "  rebuild  - Rebuild image and restart container"
        exit 1
        ;;
esac
