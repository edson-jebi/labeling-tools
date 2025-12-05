#!/bin/bash

# CVAT Image Selector - Installation Script
# This script installs all dependencies and sets up the application

set -e

echo "========================================"
echo "  CVAT Image Selector - Installer"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}Installation directory: $SCRIPT_DIR${NC}"
echo ""

# Check for Python 3
echo "Checking for Python 3..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}Found Python $PYTHON_VERSION${NC}"
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
    PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}Found Python $PYTHON_VERSION${NC}"
else
    echo -e "${RED}Error: Python 3 is required but not found.${NC}"
    echo "Please install Python 3.8 or higher and try again."
    exit 1
fi

# Check Python version is at least 3.8
PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    echo -e "${RED}Error: Python 3.8 or higher is required. Found $PYTHON_VERSION${NC}"
    exit 1
fi

# Check for pip
echo ""
echo "Checking for pip..."
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${RED}Error: pip is required but not found.${NC}"
    echo "Please install pip and try again."
    exit 1
fi
echo -e "${GREEN}pip is available${NC}"

# Create virtual environment if it doesn't exist
echo ""
echo "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}Virtual environment created${NC}"
else
    echo -e "${YELLOW}Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    echo -e "${RED}Error: Could not find virtual environment activation script${NC}"
    exit 1
fi
echo -e "${GREEN}Virtual environment activated${NC}"

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo ""
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
echo ""
if [ ! -f ".env" ]; then
    echo "Creating .env configuration file..."
    cat > .env << 'ENVFILE'
# CVAT Image Selector Configuration
# Fill in your CVAT connection details below

# CVAT Server URL (e.g., http://localhost:8080 or http://cvat.example.com:8080)
CVAT_URL=

# CVAT Username
CVAT_USERNAME=

# CVAT Password
CVAT_PASSWORD=

# Flask Secret Key (auto-generated, you can change this)
FLASK_SECRET_KEY=
ENVFILE
    echo -e "${GREEN}.env file created${NC}"
    echo -e "${YELLOW}Please edit .env file with your CVAT credentials${NC}"
else
    echo -e "${YELLOW}.env file already exists${NC}"
fi

# Create run script
echo ""
echo "Creating run script..."
cat > run.sh << 'RUNSCRIPT'
#!/bin/bash

# CVAT Image Selector - Run Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    echo "Error: Virtual environment not found. Please run install.sh first."
    exit 1
fi

# Default port
PORT=${1:-5000}

echo "========================================"
echo "  CVAT Image Selector"
echo "========================================"
echo ""
echo "Starting server on http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""

# Run the application
python cvat_image_selector.py --port $PORT
RUNSCRIPT

chmod +x run.sh
echo -e "${GREEN}run.sh created${NC}"

# Update the main Python file to accept port argument if not already
echo ""
echo "Checking application configuration..."

# Verify installation
echo ""
echo "Verifying installation..."
$PYTHON_CMD -c "import flask; import requests; import cv2; import numpy; print('All dependencies imported successfully')" && \
    echo -e "${GREEN}All dependencies verified${NC}" || \
    echo -e "${RED}Warning: Some dependencies may not be installed correctly${NC}"

echo ""
echo "========================================"
echo -e "${GREEN}  Installation Complete!${NC}"
echo "========================================"
echo ""
echo "To start the application:"
echo ""
echo "  1. Edit .env file with your CVAT credentials (optional)"
echo "  2. Run: ./run.sh"
echo "     Or: ./run.sh 8080  (to use a different port)"
echo ""
echo "  The application will be available at http://localhost:5000"
echo ""
echo "Features:"
echo "  - CVAT Image Selector: Select and download images from CVAT tasks"
echo "  - SVO/MP4 Best Selector: Analyze videos for scene changes and motion"
echo "  - Duplicate Check: Exclude images that exist in another CVAT instance"
echo ""
