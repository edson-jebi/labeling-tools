# CVAT Image Selector

A web-based Python application to select and download images from CVAT jobs using the CVAT API.

## Features

- **Connect to CVAT** - Secure connection using environment variables
- **Load Images** - Load all images from a specific Task ID and Job ID
- **Random Selection** - Randomly select a customizable number of images
- **Manual Selection** - Select/deselect images with checkboxes
- **Download as ZIP** - Download selected images as a ZIP file
- **Clean Web UI** - Modern, responsive interface

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your CVAT credentials:

```env
CVAT_URL=http://35.154.159.242:8080
CVAT_USERNAME=edson@jebi.ai
CVAT_PASSWORD=your_password
```

**Important:** Never commit your `.env` file to version control!

### 3. Run the Application

```bash
python cvat_image_selector.py
```

The server will start at `http://localhost:5020`

## Usage

### 1. Connect to CVAT

- The URL and username are pre-filled from your `.env` file
- Enter your password
- Click "Connect"

### 2. Option A: Load All Images

- Enter Task ID (required)
- Enter Job ID (optional - leave empty to load entire task)
- Click "Load All Images"
- Manually select/deselect images using checkboxes

### 3. Option B: Random Selection

**Important:** The behavior changes based on whether you provide a Job ID:

**With Job ID:**
- Enter Task ID and Job ID
- Enter number of images (e.g., 10)
- Selects 10 random images from that specific job

**Without Job ID (recommended for distributed sampling):**
- Enter Task ID only
- Enter number of images per job (e.g., 10)
- Selects 10 random images from **EACH** job in the task
- Example: If task has 5 jobs and you enter 10, you'll get 50 images total (10 from each job)
- Shows a summary of how many images were selected from each job

### 4. Download Images

- After selecting images (manually or randomly)
- Click "Download as ZIP"
- Images will be downloaded as `cvat_images_[timestamp].zip`
- Files use their **original filenames** from CVAT

## Task vs Job ID

**Task ID (Required):**
- Must always be provided
- Identifies the CVAT task

**Job ID (Optional):**
- Leave empty to work with the entire task (all images)
- Provide a Job ID to work only with images from that specific job
- Useful when a task is split into multiple jobs

## Features in Detail

### Random Selection Per Job
When selecting random images without specifying a Job ID, the tool will:
1. Discover all jobs within the task
2. Select N random images from each job independently
3. Display a summary showing selections per job
4. Example: Task with 3 jobs, requesting 5 images = 15 total images (5 from each job)

This ensures representative sampling across all jobs in a task.

### Real Filenames
- The tool fetches the original filename for each image from CVAT metadata
- Images are displayed with their real filenames in the UI
- Downloaded ZIP files contain images with their original names
- Fallback to frame numbers if metadata is unavailable

### Download Format
- Images are packaged in a ZIP file
- Files use their **original filenames** from CVAT
- Original quality images are downloaded
- ZIP filename includes timestamp for easy tracking

### Selection Tools
- **Select All** - Check all displayed images
- **Clear Selection** - Uncheck all images
- **Get Selected Info** - View JSON summary of selected images

## API Endpoints

- `POST /api/test-connection` - Test CVAT connection
- `POST /api/load-images` - Load all images from job
- `POST /api/random-select` - Randomly select N images
- `POST /api/download-images` - Download selected images as ZIP

## Requirements

- Python 3.7+
- Flask 3.0+
- requests
- python-dotenv

## Troubleshooting

**Connection Failed:**
- Verify CVAT URL is correct and accessible
- Check username and password
- Ensure CVAT server is running

**Download Failed:**
- Check you have permission to access the task
- Verify the task/job IDs are correct
- Ensure frames exist in the specified range

**Random Selection Issues:**
- Make sure you've entered valid Task ID and Job ID
- The number of images cannot exceed the total available

## Security

- Credentials are stored in `.env` file (not in code)
- Session-based authentication
- Always use HTTPS in production
- Add `.env` to `.gitignore`

## Example Workflows

### Workflow 1: Random selection per job (distributed sampling)

1. Connect to CVAT server
2. Enter Task ID: `123`
3. Leave Job ID empty
4. Enter `10` in the "Number of Images per Job" field
5. Click "Select Random Images"
6. View the job summary (e.g., "Job 1: 10/50, Job 2: 10/45, Job 3: 10/60")
7. Total of 30 images selected (10 from each of the 3 jobs)
8. Click "Download as ZIP"
9. Extract `cvat_images_20250113_143022.zip` to view your images with original filenames

### Workflow 2: Random selection from specific job

1. Connect to CVAT server
2. Enter Task ID: `123` and Job ID: `456`
3. Enter `10` in the "Number of Images" field
4. Click "Select Random Images"
5. Review the 10 randomly selected images from job 456 only
6. Click "Download as ZIP"
7. Extract and review your images

### Workflow 3: Load all and manually select

1. Connect to CVAT server
2. Enter Task ID: `123` (leave Job ID empty for entire task)
3. Click "Load All Images"
4. Manually check/uncheck the images you want
5. Click "Download as ZIP"
