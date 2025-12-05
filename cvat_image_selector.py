"""
CVAT Image Selector
A simple web-based UI tool to select and view images from a CVAT job using the CVAT API.
"""

from flask import Flask, render_template, request, jsonify, session, send_file
import requests
from requests.auth import HTTPBasicAuth
import os
import random
import io
import zipfile
import re
from datetime import datetime
from dotenv import load_dotenv
import cv2
import numpy as np
from pathlib import Path
import tempfile

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# CVAT connection details from environment
CVAT_URL = os.getenv("CVAT_URL", "")
CVAT_USERNAME = os.getenv("CVAT_USERNAME", "")
CVAT_PASSWORD = os.getenv("CVAT_PASSWORD", "")


class CVATClient:
    """CVAT API client"""

    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.auth = HTTPBasicAuth(username, password)

    def test_connection(self):
        """Test connection to CVAT server"""
        try:
            response = requests.get(
                f"{self.url}/api/users/self",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            return True, "Connected successfully"
        except requests.exceptions.RequestException as e:
            return False, f"Connection failed: {str(e)}"

    def get_job_info(self, job_id):
        """Get job information"""
        try:
            response = requests.get(
                f"{self.url}/api/jobs/{job_id}",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get job info: {str(e)}")

    def get_task_info(self, task_id):
        """Get task information"""
        try:
            response = requests.get(
                f"{self.url}/api/tasks/{task_id}",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get task info: {str(e)}")

    def get_task_jobs(self, task_id):
        """Get all jobs for a task"""
        try:
            all_jobs = []

            # First try: Get jobs via task endpoint (works in newer CVAT versions)
            try:
                response = requests.get(
                    f"{self.url}/api/tasks/{task_id}/jobs",
                    auth=self.auth,
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                print(f"DEBUG: /api/tasks/{task_id}/jobs response type: {type(data)}")

                if isinstance(data, dict):
                    all_jobs = data.get('results', [])
                    print(f"DEBUG: Found {len(all_jobs)} jobs via tasks/jobs endpoint (paginated)")
                elif isinstance(data, list):
                    all_jobs = data
                    print(f"DEBUG: Found {len(all_jobs)} jobs via tasks/jobs endpoint (list)")

                if all_jobs:
                    return all_jobs
            except Exception as e:
                print(f"DEBUG: /api/tasks/{task_id}/jobs failed: {str(e)}, trying /api/jobs")

            # Second try: Get jobs via /api/jobs with task_id filter
            page = 1
            page_size = 100

            while True:
                response = requests.get(
                    f"{self.url}/api/jobs",
                    params={
                        'task_id': task_id,
                        'page': page,
                        'page_size': page_size
                    },
                    auth=self.auth,
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                print(f"DEBUG: /api/jobs response type: {type(data)}, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")

                # Handle both paginated and non-paginated responses
                if isinstance(data, dict):
                    results = data.get('results', [])
                    all_jobs.extend(results)
                    print(f"DEBUG: Page {page} returned {len(results)} jobs, total so far: {len(all_jobs)}")

                    # Check if there are more pages
                    if not data.get('next'):
                        break
                    page += 1
                else:
                    # Non-paginated response (list)
                    all_jobs = data
                    print(f"DEBUG: Non-paginated response with {len(all_jobs)} jobs")
                    break

            # Third try: Extract jobs from task info segments (older CVAT versions)
            if not all_jobs:
                print(f"DEBUG: No jobs found via API, trying to extract from task info...")
                task_info = self.get_task_info(task_id)
                print(f"DEBUG: Task info keys: {task_info.keys()}")

                # Check for 'jobs' field in task info
                if 'jobs' in task_info:
                    jobs_data = task_info['jobs']
                    print(f"DEBUG: Found 'jobs' in task info, type: {type(jobs_data)}")
                    if isinstance(jobs_data, list):
                        all_jobs = jobs_data
                    elif isinstance(jobs_data, dict) and 'results' in jobs_data:
                        all_jobs = jobs_data['results']

                # Check for 'segments' field (older CVAT versions store job info here)
                if not all_jobs and 'segments' in task_info:
                    segments = task_info['segments']
                    print(f"DEBUG: Found 'segments' in task info: {segments}")
                    for segment in segments:
                        # Each segment has jobs
                        if 'jobs' in segment:
                            for job in segment['jobs']:
                                all_jobs.append(job)
                        elif 'id' in segment:
                            # Segment itself might be the job
                            all_jobs.append(segment)

                # If still no jobs, create a synthetic job from task data
                if not all_jobs:
                    print(f"DEBUG: Creating synthetic job from task data...")
                    # Get task size to determine frame range
                    size = task_info.get('size', 0)
                    if size > 0:
                        # Create a synthetic job covering all frames
                        synthetic_job = {
                            'id': None,  # Will be handled specially
                            'task_id': task_id,
                            'start_frame': 0,
                            'stop_frame': size - 1,
                            'status': 'annotation',
                            'synthetic': True
                        }
                        all_jobs = [synthetic_job]
                        print(f"DEBUG: Created synthetic job covering frames 0-{size-1}")

            print(f"DEBUG: Total jobs found for task {task_id}: {len(all_jobs)}")
            return all_jobs
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get task jobs: {str(e)}")

    def get_frame_metadata(self, task_id, frame_number):
        """Get metadata for a specific frame including filename"""
        try:
            response = requests.get(
                f"{self.url}/api/tasks/{task_id}/data/meta",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            meta = response.json()

            # Get the frame name from frames list
            frames = meta.get('frames', [])
            if frame_number < len(frames):
                return frames[frame_number].get('name', f'frame_{frame_number}')
            return f'frame_{frame_number}'
        except Exception as e:
            return f'frame_{frame_number}'

    def get_task_images(self, task_id, include_filename=False):
        """Get all images from a task"""
        try:
            task_data = self.get_task_info(task_id)
            size = task_data.get('size', 0)

            # Get metadata if filenames are requested
            filenames = {}
            if include_filename:
                try:
                    meta = self.get_task_metadata(task_id)
                    frames = meta.get('frames', [])
                    filenames = {i: frame.get('name', f'frame_{i}') for i, frame in enumerate(frames)}
                except:
                    pass

            images = []
            for frame_num in range(size):
                image_data = {
                    'frame': frame_num,
                    'task_id': task_id,
                    'job_id': None
                }
                if include_filename:
                    image_data['filename'] = filenames.get(frame_num, f'frame_{frame_num}')
                images.append(image_data)

            return images
        except Exception as e:
            raise Exception(f"Failed to load task images: {str(e)}")

    def get_task_metadata(self, task_id):
        """Get task metadata including frame names"""
        try:
            response = requests.get(
                f"{self.url}/api/tasks/{task_id}/data/meta",
                auth=self.auth,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get task metadata: {str(e)}")

    def get_job_images(self, task_id, job_id, include_filename=False):
        """Get list of images from a job"""
        try:
            job_data = self.get_job_info(job_id)
            task_data = self.get_task_info(task_id)

            start_frame = job_data.get('start_frame', 0)
            stop_frame = job_data.get('stop_frame', 0)

            # Get metadata if filenames are requested
            filenames = {}
            if include_filename:
                try:
                    meta = self.get_task_metadata(task_id)
                    frames = meta.get('frames', [])
                    filenames = {i: frame.get('name', f'frame_{i}') for i, frame in enumerate(frames)}
                except:
                    pass

            images = []
            for frame_num in range(start_frame, stop_frame + 1):
                image_data = {
                    'frame': frame_num,
                    'task_id': task_id,
                    'job_id': job_id
                }
                if include_filename:
                    image_data['filename'] = filenames.get(frame_num, f'frame_{frame_num}')
                images.append(image_data)

            return images
        except Exception as e:
            raise Exception(f"Failed to load images: {str(e)}")

    def download_frame(self, task_id, frame_number, quality='original'):
        """Download a single frame from a task"""
        try:
            url = f"{self.url}/api/tasks/{task_id}/data"
            params = {
                'type': 'frame',
                'number': frame_number,
                'quality': quality
            }

            response = requests.get(
                url,
                params=params,
                auth=self.auth,
                timeout=30
            )
            response.raise_for_status()

            return response.content
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to download frame {frame_number}: {str(e)}")

    def get_job_annotations(self, job_id):
        """Get annotations from a job"""
        try:
            response = requests.get(
                f"{self.url}/api/jobs/{job_id}/annotations",
                auth=self.auth,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get annotations for job {job_id}: {str(e)}")

    def upload_job_annotations(self, job_id, annotations):
        """Upload annotations to a job"""
        try:
            # Try PUT first (replaces all annotations)
            response = requests.put(
                f"{self.url}/api/jobs/{job_id}/annotations",
                json=annotations,
                auth=self.auth,
                timeout=60,
                params={'action': 'create'}  # Explicitly set action
            )
            response.raise_for_status()
            result = response.json()
            print(f"DEBUG: PUT response status: {response.status_code}")
            return result
        except requests.exceptions.RequestException as e:
            # If PUT fails, try PATCH (merges annotations)
            print(f"DEBUG: PUT failed, trying PATCH: {str(e)}")
            try:
                response = requests.patch(
                    f"{self.url}/api/jobs/{job_id}/annotations",
                    json=annotations,
                    auth=self.auth,
                    timeout=60,
                    params={'action': 'create'}
                )
                response.raise_for_status()
                result = response.json()
                print(f"DEBUG: PATCH response status: {response.status_code}")
                return result
            except requests.exceptions.RequestException as e2:
                raise Exception(f"Failed to upload annotations to job {job_id}: PUT failed: {str(e)}, PATCH failed: {str(e2)}")

    def get_task_annotations(self, task_id):
        """Get annotations from a task"""
        try:
            response = requests.get(
                f"{self.url}/api/tasks/{task_id}/annotations",
                auth=self.auth,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get annotations for task {task_id}: {str(e)}")

    def upload_task_annotations(self, task_id, annotations):
        """Upload annotations to a task"""
        try:
            response = requests.put(
                f"{self.url}/api/tasks/{task_id}/annotations",
                json=annotations,
                auth=self.auth,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to upload annotations to task {task_id}: {str(e)}")

    def get_task_labels(self, task_id):
        """Get labels from a task"""
        try:
            task_info = self.get_task_info(task_id)
            print(f"DEBUG: Task info type: {type(task_info)}, keys: {task_info.keys() if isinstance(task_info, dict) else 'N/A'}")

            # Try different structures
            if isinstance(task_info, dict):
                # Try direct labels
                labels = task_info.get('labels', [])
                print(f"DEBUG: Found labels, type: {type(labels)}, value: {labels}")

                # If labels is a dict (not a list), check if it has label objects
                if isinstance(labels, dict):
                    print(f"DEBUG: Labels is a dict with keys: {labels.keys()}")

                    # Check if it's a URL reference
                    if 'url' in labels and len(labels) == 1:
                        print(f"DEBUG: Labels is a URL reference, fetching from: {labels['url']}")
                        try:
                            response = requests.get(labels['url'], auth=self.auth, timeout=30)
                            response.raise_for_status()
                            label_data = response.json()
                            print(f"DEBUG: Fetched label data type: {type(label_data)}")

                            # Extract labels from response
                            if isinstance(label_data, dict) and 'results' in label_data:
                                labels = label_data['results']
                            elif isinstance(label_data, list):
                                labels = label_data
                            else:
                                print(f"DEBUG: Unexpected label data structure")
                                return {}
                        except Exception as e:
                            print(f"DEBUG: Failed to fetch labels from URL: {str(e)}")
                            return {}
                    # Try to convert dict to list of label objects
                    elif 'results' in labels:
                        labels = labels['results']
                    elif all(isinstance(v, dict) and 'id' in v for v in labels.values()):
                        labels = list(labels.values())
                    else:
                        print(f"DEBUG: Can't parse labels dict structure - skipping validation")
                        return {}

                if isinstance(labels, list):
                    print(f"DEBUG: Found {len(labels)} labels in list")
                    if labels:
                        print(f"DEBUG: First label: {labels[0]} (type: {type(labels[0])})")

                    # If labels is just a list of IDs/strings, skip validation
                    if labels and not isinstance(labels[0], dict):
                        print(f"DEBUG: Labels appear to be IDs/URLs, not full label objects - skipping validation")
                        return {}

                if not labels:
                    # Try project -> labels
                    project = task_info.get('project')
                    if project and isinstance(project, dict):
                        labels = project.get('labels', [])
                        print(f"DEBUG: Got {len(labels)} labels from project")

                # Return dict mapping label_id to label name
                if labels and isinstance(labels, list) and isinstance(labels[0], dict):
                    return {label['id']: label['name'] for label in labels}
                else:
                    print(f"DEBUG: Unable to extract label info - skipping validation")
                    return {}
            else:
                raise Exception(f"Unexpected task_info type: {type(task_info)}")
        except Exception as e:
            import traceback
            print(f"DEBUG: Full traceback:")
            traceback.print_exc()
            raise Exception(f"Failed to get labels for task {task_id}: {str(e)}")


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html',
                         cvat_url=CVAT_URL,
                         cvat_username=CVAT_USERNAME)


@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """Test CVAT connection"""
    data = request.json
    url = data.get('url', CVAT_URL)
    username = data.get('username', CVAT_USERNAME)
    password = data.get('password', CVAT_PASSWORD)

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'Missing credentials'}), 400

    client = CVATClient(url, username, password)
    success, message = client.test_connection()

    if success:
        session['cvat_url'] = url
        session['cvat_username'] = username
        session['cvat_password'] = password

    return jsonify({'success': success, 'message': message})


@app.route('/api/load-images', methods=['POST'])
def load_images():
    """Load images from task/job"""
    data = request.json
    task_id = data.get('task_id')
    job_id = data.get('job_id')

    if not task_id:
        return jsonify({'success': False, 'message': 'Missing task_id'}), 400

    # Get credentials from session or environment
    url = session.get('cvat_url', CVAT_URL)
    username = session.get('cvat_username', CVAT_USERNAME)
    password = session.get('cvat_password', CVAT_PASSWORD)

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'Not connected to CVAT'}), 401

    try:
        client = CVATClient(url, username, password)

        # If job_id is provided, load from job, otherwise load entire task
        if job_id:
            images = client.get_job_images(task_id, job_id, include_filename=True)
            source = f"job {job_id}"
        else:
            images = client.get_task_images(task_id, include_filename=True)
            source = f"task {task_id}"

        return jsonify({
            'success': True,
            'images': images,
            'count': len(images),
            'source': source
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/get-selection', methods=['POST'])
def get_selection():
    """Process selected images"""
    data = request.json
    selected_frames = data.get('selected_frames', [])

    return jsonify({
        'success': True,
        'count': len(selected_frames),
        'frames': selected_frames
    })


@app.route('/api/debug-local-task', methods=['POST'])
def debug_local_task():
    """Debug endpoint to check jobs and images in the local/connected CVAT instance"""
    data = request.json
    task_id = data.get('task_id')

    if not task_id:
        return jsonify({'success': False, 'message': 'Missing task_id'}), 400

    # Get credentials from session or environment
    url = session.get('cvat_url', CVAT_URL)
    username = session.get('cvat_username', CVAT_USERNAME)
    password = session.get('cvat_password', CVAT_PASSWORD)

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'Not connected to CVAT'}), 401

    try:
        client = CVATClient(url, username, password)

        print(f"\n{'='*60}")
        print(f"DEBUG: Checking LOCAL CVAT at {url}")
        print(f"DEBUG: Task ID: {task_id}")
        print(f"{'='*60}")

        # Get task info
        task_info = client.get_task_info(task_id)
        print(f"DEBUG: Task name: {task_info.get('name', 'N/A')}")
        print(f"DEBUG: Task size: {task_info.get('size', 0)} frames")

        # Get jobs
        jobs = client.get_task_jobs(task_id)
        print(f"DEBUG: Found {len(jobs)} jobs")

        jobs_info = []
        for i, job in enumerate(jobs[:5]):  # First 5 jobs
            job_info = {
                'id': job.get('id'),
                'start_frame': job.get('start_frame'),
                'stop_frame': job.get('stop_frame'),
                'status': job.get('status'),
                'synthetic': job.get('synthetic', False)
            }
            jobs_info.append(job_info)
            print(f"DEBUG: Job {i+1}: {job_info}")

        # Get sample filenames from task metadata
        meta = client.get_task_metadata(task_id)
        frames = meta.get('frames', [])
        sample_filenames = []
        for i, frame in enumerate(frames[:10]):  # First 10 frames
            filename = frame.get('name', f'frame_{i}')
            normalized = normalize_filename(filename)
            sample_filenames.append({
                'original': filename,
                'normalized': normalized
            })
            print(f"DEBUG: Frame {i}: '{filename}' -> '{normalized}'")

        print(f"{'='*60}\n")

        return jsonify({
            'success': True,
            'task_info': {
                'name': task_info.get('name'),
                'size': task_info.get('size'),
                'status': task_info.get('status')
            },
            'jobs_count': len(jobs),
            'jobs': jobs_info,
            'total_frames': len(frames),
            'sample_filenames': sample_filenames
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/debug-remote-task', methods=['POST'])
def debug_remote_task():
    """Debug endpoint to check jobs and images in a remote CVAT instance"""
    data = request.json
    url = data.get('url')
    username = data.get('username')
    password = data.get('password')
    task_id = data.get('task_id')

    if not all([url, username, password, task_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        client = CVATClient(url, username, password)

        # Test connection first
        success, message = client.test_connection()
        if not success:
            return jsonify({'success': False, 'message': f'Connection failed: {message}'}), 500

        print(f"\n{'='*60}")
        print(f"DEBUG: Checking remote CVAT at {url}")
        print(f"DEBUG: Task ID: {task_id}")
        print(f"{'='*60}")

        # Get task info
        task_info = client.get_task_info(task_id)
        print(f"DEBUG: Task info keys: {task_info.keys()}")
        print(f"DEBUG: Task name: {task_info.get('name', 'N/A')}")
        print(f"DEBUG: Task size: {task_info.get('size', 0)} frames")

        # Get jobs
        jobs = client.get_task_jobs(task_id)
        print(f"DEBUG: Found {len(jobs)} jobs")

        jobs_info = []
        for i, job in enumerate(jobs):
            job_info = {
                'id': job.get('id'),
                'start_frame': job.get('start_frame'),
                'stop_frame': job.get('stop_frame'),
                'status': job.get('status'),
                'synthetic': job.get('synthetic', False)
            }
            jobs_info.append(job_info)
            print(f"DEBUG: Job {i+1}: {job_info}")

        # Get sample filenames from task metadata
        meta = client.get_task_metadata(task_id)
        frames = meta.get('frames', [])
        sample_filenames = []
        for i, frame in enumerate(frames[:10]):  # First 10 frames
            filename = frame.get('name', f'frame_{i}')
            normalized = normalize_filename(filename)
            sample_filenames.append({
                'original': filename,
                'normalized': normalized
            })
            print(f"DEBUG: Frame {i}: '{filename}' -> '{normalized}'")

        print(f"{'='*60}\n")

        return jsonify({
            'success': True,
            'task_info': {
                'name': task_info.get('name'),
                'size': task_info.get('size'),
                'status': task_info.get('status')
            },
            'jobs_count': len(jobs),
            'jobs': jobs_info,
            'total_frames': len(frames),
            'sample_filenames': sample_filenames
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


def normalize_filename(filename):
    """
    Normalize filename for comparison by:
    1. Getting just the base filename (removing path)
    2. Removing any job ID prefix patterns like '68_' (short numeric prefixes 1-4 digits)

    Examples:
    - 'dataset_baumas/ex641/250919_s1_2_3/68_1758259745_7474.jpg' -> '1758259745_7474.jpg'
    - '68_1758259745_7474.jpg' -> '1758259745_7474.jpg'
    - '1758259745_7474.jpg' -> '1758259745_7474.jpg' (no change if no prefix)
    """
    # Get just the base filename (remove path)
    if '/' in filename:
        base_filename = filename.rsplit('/', 1)[1]
    else:
        base_filename = filename

    # Remove job ID prefix: only short numeric prefixes (1-4 digits) followed by underscore
    # This avoids removing timestamps which are longer (10+ digits)
    clean_filename = re.sub(r'^\d{1,4}_', '', base_filename)

    return clean_filename


def get_existing_filenames_from_cvat(check_url, check_username, check_password, check_task_id):
    """Get all filenames from another CVAT instance for duplicate checking"""
    check_client = CVATClient(check_url, check_username, check_password)

    try:
        existing_filenames = set()

        # Get task metadata to get all filenames from entire task
        meta = check_client.get_task_metadata(check_task_id)
        frames = meta.get('frames', [])

        print(f"DEBUG: Got {len(frames)} frames from task {check_task_id}")

        # Extract base filenames (without path)
        for i, frame in enumerate(frames):
            filename = frame.get('name', '')
            clean_filename = normalize_filename(filename)
            existing_filenames.add(clean_filename)

            # Debug first few
            if i < 3:
                print(f"DEBUG: Existing frame - Original: '{filename}' -> Normalized: '{clean_filename}'")

        return existing_filenames
    except Exception as e:
        print(f"ERROR: Failed to get existing filenames: {str(e)}")
        raise


@app.route('/api/random-select', methods=['POST'])
def random_select():
    """Randomly select N images per job from the task"""
    data = request.json
    task_id = data.get('task_id')
    job_id = data.get('job_id')
    count = data.get('count', 10)
    duplicate_check = data.get('duplicate_check')  # Optional duplicate check params

    if not task_id:
        return jsonify({'success': False, 'message': 'Missing task_id'}), 400

    # Get credentials from session or environment
    url = session.get('cvat_url', CVAT_URL)
    username = session.get('cvat_username', CVAT_USERNAME)
    password = session.get('cvat_password', CVAT_PASSWORD)

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'Not connected to CVAT'}), 401

    # Validate main CVAT connection before proceeding
    try:
        print(f"DEBUG: Validating main CVAT connection to: {url}")
        test_client = CVATClient(url, username, password)
        connection_success, connection_message = test_client.test_connection()
        if not connection_success:
            return jsonify({
                'success': False,
                'message': f'Main CVAT connection failed: {connection_message}. Please reconnect to CVAT.',
                'connection_url': url
            }), 401
        print(f"DEBUG: Main CVAT connection validated successfully: {connection_message}")

        # Also verify the task exists on this CVAT instance
        try:
            task_response = requests.get(
                f"{url.rstrip('/')}/api/tasks/{task_id}",
                auth=HTTPBasicAuth(username, password),
                timeout=10
            )
            if task_response.status_code == 404:
                return jsonify({
                    'success': False,
                    'message': f'Task {task_id} not found on CVAT at {url}. You may be connected to the wrong CVAT instance.',
                    'connection_url': url
                }), 404
            task_response.raise_for_status()
            task_info = task_response.json()
            print(f"DEBUG: Task {task_id} found: '{task_info.get('name', 'Unknown')}' with {task_info.get('size', 0)} images")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return jsonify({
                    'success': False,
                    'message': f'Task {task_id} not found on CVAT at {url}. You may be connected to the wrong CVAT instance.',
                    'connection_url': url
                }), 404
            raise

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Failed to validate CVAT connection: {str(e)}. Please reconnect to CVAT.',
            'connection_url': url
        }), 401

    # Get existing filenames if duplicate check is enabled
    existing_filenames = set()
    duplicate_check_summary = None

    if duplicate_check:
        try:
            existing_filenames = get_existing_filenames_from_cvat(
                duplicate_check['check_url'],
                duplicate_check['check_username'],
                duplicate_check['check_password'],
                duplicate_check['check_task_id']
            )
            print(f"DEBUG: Found {len(existing_filenames)} existing filenames from task {duplicate_check['check_task_id']} for duplicate check")
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to connect to check CVAT: {str(e)}'}), 500

    try:
        print(f"DEBUG: Creating LOCAL client with URL: {url}")
        client = CVATClient(url, username, password)

        def select_unique_random_images(images, count, existing_filenames):
            """
            Select random images, replacing duplicates with new selections until count is reached.
            Uses a hash set for O(1) duplicate lookup.

            Args:
                images: List of image dicts with 'filename' key
                count: Desired number of unique images
                existing_filenames: Set of normalized filenames already in another CVAT instance

            Returns:
                tuple: (selected_images, duplicate_filenames_found, images_checked)
            """
            if not existing_filenames:
                # No duplicate check - simple random sample
                sample_count = min(count, len(images))
                return random.sample(images, sample_count) if sample_count > 0 else [], [], len(images)

            # Shuffle all available images for random selection
            shuffled_images = images.copy()
            random.shuffle(shuffled_images)

            selected_images = []
            duplicate_filenames_found = []
            images_checked = 0

            # Debug: Show sample of existing filenames
            if existing_filenames and images_checked == 0:
                sample_existing = list(existing_filenames)[:5]
                print(f"DEBUG: Sample existing filenames (normalized): {sample_existing}")

            for img in shuffled_images:
                images_checked += 1
                filename = img.get('filename', '')
                clean_filename = normalize_filename(filename)

                # Debug first few comparisons
                if images_checked <= 5:
                    is_dup = clean_filename in existing_filenames
                    print(f"DEBUG: Source image {images_checked}: '{filename}' -> '{clean_filename}' | Is duplicate: {is_dup}")

                # Check if this image is a duplicate
                if clean_filename in existing_filenames:
                    duplicate_filenames_found.append(clean_filename)
                    # Skip this image and continue to the next one
                    continue

                # Not a duplicate - add to selected
                selected_images.append(img)

                # Check if we've reached the desired count
                if len(selected_images) >= count:
                    break

            print(f"DEBUG: Total checked: {images_checked}, Selected: {len(selected_images)}, Duplicates skipped: {len(duplicate_filenames_found)}")
            return selected_images, duplicate_filenames_found, images_checked

        # If job_id is provided, select from that job only
        if job_id:
            all_images = client.get_job_images(task_id, job_id, include_filename=True)

            # Select random images, replacing duplicates with new selections
            if duplicate_check:
                selected_images, duplicate_filenames, images_checked = select_unique_random_images(
                    all_images, count, existing_filenames
                )
                total_candidates = len(all_images)
                duplicates_count = len(duplicate_filenames)
            else:
                # Simple random sample without duplicate check
                sample_count = min(count, len(all_images))
                selected_images = random.sample(all_images, sample_count) if sample_count > 0 else []
                duplicate_filenames = []
                duplicates_count = 0
                total_candidates = len(all_images)

            response_data = {
                'success': True,
                'images': selected_images,
                'count': len(selected_images),
                'total_available': len(all_images),
                'source': f"job {job_id}",
                'jobs_count': 1
            }

            if duplicate_check:
                response_data['duplicate_check_summary'] = {
                    'total_candidates': total_candidates,
                    'duplicates_found': duplicates_count,
                    'duplicates_skipped': duplicates_count,
                    'unique_selected': len(selected_images),
                    'requested_count': count,
                    'duplicate_filenames': duplicate_filenames
                }

            return jsonify(response_data)
        else:
            # Get all jobs in the task
            jobs = client.get_task_jobs(task_id)

            print(f"DEBUG: Found {len(jobs)} jobs for task {task_id}")
            for job in jobs:
                print(f"DEBUG: Job {job.get('id')} - Status: {job.get('status', 'unknown')}")

            if not jobs:
                return jsonify({'success': False, 'message': 'No jobs found in task'}), 404

            # Select N random images from EACH job
            all_selected_images = []
            job_summary = []
            total_candidates = 0
            total_duplicates = 0
            all_duplicate_filenames = []

            for job in jobs:
                job_id_current = job.get('id')
                is_synthetic = job.get('synthetic', False)
                print(f"DEBUG: Processing job {job_id_current} (synthetic: {is_synthetic})")

                try:
                    # For synthetic jobs (when CVAT API doesn't return job list), use task images directly
                    if is_synthetic or job_id_current is None:
                        job_images = client.get_task_images(task_id, include_filename=True)
                        # Add synthetic job_id to images for download naming
                        for img in job_images:
                            img['job_id'] = 'task'
                        print(f"DEBUG: Synthetic job - loaded {len(job_images)} images from task")
                    else:
                        job_images = client.get_job_images(task_id, job_id_current, include_filename=True)
                        print(f"DEBUG: Job {job_id_current} has {len(job_images)} images")

                    # Select random images, replacing duplicates with new selections
                    if duplicate_check:
                        selected_from_job, duplicate_filenames, images_checked = select_unique_random_images(
                            job_images, count, existing_filenames
                        )
                        total_candidates += len(job_images)
                        duplicates_count = len(duplicate_filenames)
                        total_duplicates += duplicates_count
                        all_duplicate_filenames.extend(duplicate_filenames)

                        all_selected_images.extend(selected_from_job)
                        print(f"DEBUG: Selected {len(selected_from_job)} unique images from job {job_id_current} (skipped {duplicates_count} duplicates)")

                        # Use 'Task' as job_id display for synthetic jobs
                        job_display_id = job_id_current if job_id_current else f"Task {task_id}"
                        job_summary.append({
                            'job_id': job_display_id,
                            'selected': len(selected_from_job),
                            'total': len(job_images),
                            'duplicates_skipped': duplicates_count,
                            'requested': count,
                            'note': 'Reached count' if len(selected_from_job) >= count else (
                                'All non-duplicate images selected' if len(selected_from_job) < count else None
                            )
                        })
                    else:
                        # Simple random sample without duplicate check
                        sample_count = min(count, len(job_images))
                        if sample_count > 0:
                            selected_from_job = random.sample(job_images, sample_count)
                            all_selected_images.extend(selected_from_job)
                            print(f"DEBUG: Selected {sample_count} images from job {job_id_current}")

                            job_display_id = job_id_current if job_id_current else f"Task {task_id}"
                            job_summary.append({
                                'job_id': job_display_id,
                                'selected': sample_count,
                                'total': len(job_images)
                            })
                        else:
                            job_display_id = job_id_current if job_id_current else f"Task {task_id}"
                            job_summary.append({
                                'job_id': job_display_id,
                                'selected': 0,
                                'total': len(job_images),
                                'note': 'No images'
                            })
                except Exception as e:
                    print(f"ERROR: Failed to process job {job_id_current}: {str(e)}")
                    # Add to summary showing error
                    job_display_id = job_id_current if job_id_current else f"Task {task_id}"
                    job_summary.append({
                        'job_id': job_display_id,
                        'selected': 0,
                        'total': 0,
                        'error': str(e)
                    })

            print(f"DEBUG: Total selected images: {len(all_selected_images)}")

            response_data = {
                'success': True,
                'images': all_selected_images,
                'count': len(all_selected_images),
                'source': f"task {task_id} ({len(jobs)} jobs)",
                'jobs_count': len(jobs),
                'per_job_count': count,
                'job_summary': job_summary
            }

            if duplicate_check:
                response_data['duplicate_check_summary'] = {
                    'total_candidates': total_candidates,
                    'duplicates_found': total_duplicates,
                    'duplicates_skipped': total_duplicates,
                    'unique_selected': len(all_selected_images),
                    'requested_per_job': count,
                    'duplicate_filenames': all_duplicate_filenames
                }

            return jsonify(response_data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/download-images', methods=['POST'])
def download_images():
    """Download selected images as a zip file"""
    data = request.json
    frames = data.get('frames', [])

    if not frames:
        return jsonify({'success': False, 'message': 'No frames selected'}), 400

    # Get credentials from session or environment
    url = session.get('cvat_url', CVAT_URL)
    username = session.get('cvat_username', CVAT_USERNAME)
    password = session.get('cvat_password', CVAT_PASSWORD)

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'Not connected to CVAT'}), 401

    try:
        client = CVATClient(url, username, password)

        # Create a zip file in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for frame_info in frames:
                task_id = frame_info.get('task_id')
                frame_num = frame_info.get('frame')
                job_id = frame_info.get('job_id')
                filename = frame_info.get('filename')

                try:
                    # Download the frame
                    image_data = client.download_frame(task_id, frame_num)

                    # Use real filename if available, otherwise use descriptive name
                    if filename:
                        # Split the path to get directory and filename
                        if '/' in filename:
                            parts = filename.rsplit('/', 1)
                            directory = parts[0]
                            base_filename = parts[1]
                            # Add job ID prefix to the filename
                            if job_id:
                                zip_filename = f"{directory}/{job_id}_{base_filename}"
                            else:
                                zip_filename = filename
                        else:
                            # No directory structure, just prefix the filename
                            if job_id:
                                zip_filename = f"{job_id}_{filename}"
                            else:
                                zip_filename = filename
                    else:
                        # Get file extension from content or default to jpg
                        zip_filename = f"task_{task_id}_job_{job_id}_frame_{frame_num}.jpg"

                    zip_file.writestr(zip_filename, image_data)

                except Exception as e:
                    # Continue with other frames even if one fails
                    print(f"Error downloading frame {frame_num}: {str(e)}")
                    continue

        # Prepare the zip for download
        zip_buffer.seek(0)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"cvat_images_{timestamp}.zip"

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/test-connection-dual', methods=['POST'])
def test_connection_dual():
    """Test connection to source and target CVAT instances"""
    data = request.json

    source_url = data.get('source_url')
    source_username = data.get('source_username')
    source_password = data.get('source_password')

    target_url = data.get('target_url')
    target_username = data.get('target_username')
    target_password = data.get('target_password')

    results = {}

    # Test source connection
    if all([source_url, source_username, source_password]):
        source_client = CVATClient(source_url, source_username, source_password)
        success, message = source_client.test_connection()
        results['source'] = {'success': success, 'message': message}
    else:
        results['source'] = {'success': False, 'message': 'Missing source credentials'}

    # Test target connection
    if all([target_url, target_username, target_password]):
        target_client = CVATClient(target_url, target_username, target_password)
        success, message = target_client.test_connection()
        results['target'] = {'success': success, 'message': message}
    else:
        results['target'] = {'success': False, 'message': 'Missing target credentials'}

    # Store credentials in session if both connections succeed
    if results['source']['success'] and results['target']['success']:
        session['copy_source_url'] = source_url
        session['copy_source_username'] = source_username
        session['copy_source_password'] = source_password
        session['copy_target_url'] = target_url
        session['copy_target_username'] = target_username
        session['copy_target_password'] = target_password

    return jsonify({
        'success': results['source']['success'] and results['target']['success'],
        'source': results['source'],
        'target': results['target']
    })


@app.route('/api/preview-annotations', methods=['POST'])
def preview_annotations():
    """Preview annotations from source before copying"""
    data = request.json
    source_task_id = data.get('source_task_id')
    source_job_id = data.get('source_job_id')

    # Get credentials from session
    source_url = session.get('copy_source_url')
    source_username = session.get('copy_source_username')
    source_password = session.get('copy_source_password')

    if not all([source_url, source_username, source_password]):
        return jsonify({'success': False, 'message': 'Not connected to source CVAT'}), 401

    if not source_task_id:
        return jsonify({'success': False, 'message': 'Missing source task ID'}), 400

    try:
        source_client = CVATClient(source_url, source_username, source_password)

        # Get annotations
        if source_job_id:
            annotations = source_client.get_job_annotations(source_job_id)
            # Get job info to know which frames belong to this job
            job_info = source_client.get_job_info(source_job_id)
            start_frame = job_info.get('start_frame', 0)
            stop_frame = job_info.get('stop_frame', 0)
        else:
            annotations = source_client.get_task_annotations(source_task_id)
            start_frame = None
            stop_frame = None

        # Get task metadata to map frame numbers to filenames
        task_meta = source_client.get_task_metadata(source_task_id)
        all_frames = task_meta.get('frames', [])

        # If job level, filter frames to only those in the job
        if source_job_id:
            frames = all_frames[start_frame:stop_frame + 1]
            # Create filename mapping using actual frame numbers
            frame_to_filename = {start_frame + i: frame.get('name', f'frame_{start_frame + i}')
                               for i, frame in enumerate(frames)}
        else:
            frames = all_frames
            # Create filename mapping for all frames
            frame_to_filename = {i: frame.get('name', f'frame_{i}') for i, frame in enumerate(frames)}

        # Process annotations to include filenames
        annotated_files = {}

        # Process shapes (bounding boxes, polygons, etc.)
        for shape in annotations.get('shapes', []):
            frame_num = shape.get('frame', 0)
            filename = frame_to_filename.get(frame_num, f'frame_{frame_num}')

            if filename not in annotated_files:
                annotated_files[filename] = {
                    'frame': frame_num,
                    'shapes': [],
                    'tracks': []
                }

            annotated_files[filename]['shapes'].append({
                'type': shape.get('type'),
                'label': shape.get('label_id'),
                'attributes': shape.get('attributes', {}),
                'occluded': shape.get('occluded', False)
            })

        # Process tracks (video annotations)
        for track in annotations.get('tracks', []):
            for shape in track.get('shapes', []):
                frame_num = shape.get('frame', 0)
                filename = frame_to_filename.get(frame_num, f'frame_{frame_num}')

                if filename not in annotated_files:
                    annotated_files[filename] = {
                        'frame': frame_num,
                        'shapes': [],
                        'tracks': []
                    }

                annotated_files[filename]['tracks'].append({
                    'type': track.get('type'),
                    'label': track.get('label_id'),
                    'attributes': shape.get('attributes', {}),
                    'occluded': shape.get('occluded', False)
                })

        # Sort by filename
        sorted_files = dict(sorted(annotated_files.items()))

        return jsonify({
            'success': True,
            'annotated_files': sorted_files,
            'total_files': len(sorted_files),
            'total_frames': len(frames),
            'total_shapes': len(annotations.get('shapes', [])),
            'total_tracks': len(annotations.get('tracks', [])),
            'source': f'job {source_job_id}' if source_job_id else f'task {source_task_id}'
        })

    except Exception as e:
        print(f"ERROR: Failed to preview annotations: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/preview-target-annotations', methods=['POST'])
def preview_target_annotations():
    """Preview annotations from target before copying"""
    data = request.json
    target_task_id = data.get('target_task_id')
    target_job_id = data.get('target_job_id')

    # Get credentials from session
    target_url = session.get('copy_target_url')
    target_username = session.get('copy_target_username')
    target_password = session.get('copy_target_password')

    if not all([target_url, target_username, target_password]):
        return jsonify({'success': False, 'message': 'Not connected to target CVAT'}), 401

    if not target_task_id:
        return jsonify({'success': False, 'message': 'Missing target task ID'}), 400

    try:
        target_client = CVATClient(target_url, target_username, target_password)

        # Get annotations
        if target_job_id:
            annotations = target_client.get_job_annotations(target_job_id)
            # Get job info to know which frames belong to this job
            job_info = target_client.get_job_info(target_job_id)
            start_frame = job_info.get('start_frame', 0)
            stop_frame = job_info.get('stop_frame', 0)
        else:
            annotations = target_client.get_task_annotations(target_task_id)
            start_frame = None
            stop_frame = None

        # Get task metadata to map frame numbers to filenames
        task_meta = target_client.get_task_metadata(target_task_id)
        all_frames = task_meta.get('frames', [])

        # If job level, filter frames to only those in the job
        if target_job_id:
            frames = all_frames[start_frame:stop_frame + 1]
            # Create filename mapping using actual frame numbers
            frame_to_filename = {start_frame + i: frame.get('name', f'frame_{start_frame + i}')
                               for i, frame in enumerate(frames)}
        else:
            frames = all_frames
            # Create filename mapping for all frames
            frame_to_filename = {i: frame.get('name', f'frame_{i}') for i, frame in enumerate(frames)}

        # Initialize all files with empty annotations
        all_files = {}
        for frame_num, filename in frame_to_filename.items():
            all_files[filename] = {
                'frame': frame_num,
                'shapes': [],
                'tracks': []
            }

        # Process shapes (bounding boxes, polygons, etc.)
        for shape in annotations.get('shapes', []):
            frame_num_job_relative = shape.get('frame', 0)

            # If job level, frame numbers in annotations are job-relative, convert to task-absolute
            if target_job_id:
                frame_num_absolute = frame_num_job_relative + start_frame
            else:
                frame_num_absolute = frame_num_job_relative

            filename = frame_to_filename.get(frame_num_absolute, f'frame_{frame_num_absolute}')

            if filename in all_files:
                all_files[filename]['shapes'].append({
                    'type': shape.get('type'),
                    'label': shape.get('label_id'),
                    'attributes': shape.get('attributes', {}),
                    'occluded': shape.get('occluded', False)
                })

        # Process tracks (video annotations)
        for track in annotations.get('tracks', []):
            for shape in track.get('shapes', []):
                frame_num_job_relative = shape.get('frame', 0)

                # If job level, frame numbers in annotations are job-relative, convert to task-absolute
                if target_job_id:
                    frame_num_absolute = frame_num_job_relative + start_frame
                else:
                    frame_num_absolute = frame_num_job_relative

                filename = frame_to_filename.get(frame_num_absolute, f'frame_{frame_num_absolute}')

                if filename in all_files:
                    all_files[filename]['tracks'].append({
                        'type': track.get('type'),
                        'label': track.get('label_id'),
                        'attributes': shape.get('attributes', {}),
                        'occluded': shape.get('occluded', False)
                    })

        # Sort by filename
        sorted_files = dict(sorted(all_files.items()))

        return jsonify({
            'success': True,
            'annotated_files': sorted_files,
            'total_files': len(sorted_files),
            'total_frames': len(frames),
            'total_shapes': len(annotations.get('shapes', [])),
            'total_tracks': len(annotations.get('tracks', [])),
            'source': f'job {target_job_id}' if target_job_id else f'task {target_task_id}'
        })

    except Exception as e:
        print(f"ERROR: Failed to preview target annotations: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/preview-matches', methods=['POST'])
def preview_matches():
    """Preview which source files will match with target files before copying"""
    data = request.json
    source_task_id = data.get('source_task_id')
    source_job_id = data.get('source_job_id')
    target_task_id = data.get('target_task_id')
    target_job_id = data.get('target_job_id')

    # Get credentials from session
    source_url = session.get('copy_source_url')
    source_username = session.get('copy_source_username')
    source_password = session.get('copy_source_password')
    target_url = session.get('copy_target_url')
    target_username = session.get('copy_target_username')
    target_password = session.get('copy_target_password')

    if not all([source_url, source_username, source_password, target_url, target_username, target_password]):
        return jsonify({'success': False, 'message': 'Not connected to both CVAT instances'}), 401

    if not source_task_id or not target_task_id:
        return jsonify({'success': False, 'message': 'Missing task IDs'}), 400

    try:
        source_client = CVATClient(source_url, source_username, source_password)
        target_client = CVATClient(target_url, target_username, target_password)

        # Get metadata for both source and target
        source_meta = source_client.get_task_metadata(source_task_id)
        target_meta = target_client.get_task_metadata(target_task_id)

        source_all_frames = source_meta.get('frames', [])
        target_all_frames = target_meta.get('frames', [])

        # Filter frames based on job if specified
        if source_job_id:
            source_job_info = source_client.get_job_info(source_job_id)
            source_start = source_job_info.get('start_frame', 0)
            source_stop = source_job_info.get('stop_frame', 0)
            source_frames = source_all_frames[source_start:source_stop + 1]
        else:
            source_frames = source_all_frames

        if target_job_id:
            target_job_info = target_client.get_job_info(target_job_id)
            target_start = target_job_info.get('start_frame', 0)
            target_stop = target_job_info.get('stop_frame', 0)
            target_frames = target_all_frames[target_start:target_stop + 1]
        else:
            target_frames = target_all_frames

        # Create mapping: source_frame_num -> source_filename (base name only)
        source_frame_to_basename = {}
        for i, frame in enumerate(source_frames):
            source_full_path = frame.get('name', f'frame_{i}')
            if '/' in source_full_path:
                source_basename = source_full_path.rsplit('/', 1)[1]
            else:
                source_basename = source_full_path
            source_frame_to_basename[i] = source_basename

        # Create mapping: target_filename -> target_frame_num
        target_basename_to_frame = {}
        target_frame_to_fullpath = {}
        for i, frame in enumerate(target_frames):
            target_filename = frame.get('name', f'frame_{i}')
            target_frame_to_fullpath[i] = target_filename

            if '/' in target_filename:
                target_basename = target_filename.rsplit('/', 1)[1]
            else:
                target_basename = target_filename

            # Remove job ID prefix (e.g., "30_") from filename
            clean_basename = re.sub(r'^\d+_', '', target_basename)
            target_basename_to_frame[clean_basename] = i

        # Find matches
        matched_files = []
        unmatched_source = []
        unmatched_target = list(target_frame_to_fullpath.values())  # Start with all target files

        for source_frame_num, source_basename in source_frame_to_basename.items():
            if source_basename in target_basename_to_frame:
                target_frame_num = target_basename_to_frame[source_basename]
                target_fullpath = target_frame_to_fullpath[target_frame_num]

                # Get source full path
                source_fullpath = source_frames[source_frame_num].get('name', f'frame_{source_frame_num}')

                matched_files.append({
                    'source': source_fullpath,
                    'target': target_fullpath,
                    'base_filename': source_basename
                })

                # Remove from unmatched target list
                if target_fullpath in unmatched_target:
                    unmatched_target.remove(target_fullpath)
            else:
                source_fullpath = source_frames[source_frame_num].get('name', f'frame_{source_frame_num}')
                unmatched_source.append(source_fullpath)

        return jsonify({
            'success': True,
            'matched_files': matched_files,
            'matched_count': len(matched_files),
            'unmatched_source': unmatched_source,
            'unmatched_source_count': len(unmatched_source),
            'unmatched_target': unmatched_target,
            'unmatched_target_count': len(unmatched_target),
            'total_source_files': len(source_frames),
            'total_target_files': len(target_frames)
        })

    except Exception as e:
        print(f"ERROR: Failed to preview matches: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/copy-annotations', methods=['POST'])
def copy_annotations():
    """Copy annotations from source to target CVAT instance with filename matching"""
    data = request.json
    source_task_id = data.get('source_task_id')
    source_job_id = data.get('source_job_id')
    target_task_id = data.get('target_task_id')
    target_job_id = data.get('target_job_id')

    # Get credentials from session
    source_url = session.get('copy_source_url')
    source_username = session.get('copy_source_username')
    source_password = session.get('copy_source_password')
    target_url = session.get('copy_target_url')
    target_username = session.get('copy_target_username')
    target_password = session.get('copy_target_password')

    if not all([source_url, source_username, source_password, target_url, target_username, target_password]):
        return jsonify({'success': False, 'message': 'Not connected to both CVAT instances'}), 401

    if not source_task_id or not target_task_id:
        return jsonify({'success': False, 'message': 'Missing task IDs'}), 400

    try:
        source_client = CVATClient(source_url, source_username, source_password)
        target_client = CVATClient(target_url, target_username, target_password)

        # Get source annotations and job info if needed
        if source_job_id:
            source_annotations = source_client.get_job_annotations(source_job_id)
            source_job_info = source_client.get_job_info(source_job_id)
            source_start_frame = source_job_info.get('start_frame', 0)
            source_stop_frame = source_job_info.get('stop_frame', 0)
            print(f"DEBUG: Source job {source_job_id} frame range: {source_start_frame} to {source_stop_frame}")
        else:
            source_annotations = source_client.get_task_annotations(source_task_id)
            source_start_frame = 0
            source_stop_frame = None

        # Get metadata for both source and target
        source_meta = source_client.get_task_metadata(source_task_id)
        target_meta = target_client.get_task_metadata(target_task_id)

        source_frames = source_meta.get('frames', [])
        target_frames = target_meta.get('frames', [])

        # Get target job frame range if uploading to a job
        if target_job_id:
            target_job_info = target_client.get_job_info(target_job_id)
            target_start_frame = target_job_info.get('start_frame', 0)
            target_stop_frame = target_job_info.get('stop_frame', 0)
            print(f"DEBUG: Target job {target_job_id} frame range: {target_start_frame} to {target_stop_frame}")
        else:
            target_start_frame = 0
            target_stop_frame = len(target_frames) - 1

        print(f"DEBUG: Source has {len(source_frames)} frames, Target has {len(target_frames)} frames")

        # Create mapping: source_frame_num -> source_filename (base name only)
        # Extract just the base filename from source for matching
        # Example: dataset_baumas/ex641/250910_s1/image_5585.jpg -> image_5585.jpg
        import re
        source_frame_to_basename = {}

        # If source is a job, we need to filter to only frames in that job
        if source_job_id:
            # Get only the frames that belong to this job
            source_job_frames = source_frames[source_start_frame:source_stop_frame + 1]
            for i, frame in enumerate(source_job_frames):
                # Use absolute task frame number as the key
                absolute_frame_num = source_start_frame + i
                source_full_path = frame.get('name', f'frame_{absolute_frame_num}')
                # Get just the filename part
                if '/' in source_full_path:
                    source_basename = source_full_path.rsplit('/', 1)[1]
                else:
                    source_basename = source_full_path
                source_frame_to_basename[absolute_frame_num] = source_basename
                if i < 5:  # Only print first 5 to reduce spam
                    print(f"DEBUG: Source mapping: frame {absolute_frame_num} -> {source_full_path} -> basename: {source_basename}")
        else:
            # For task-level, use all frames
            for i, frame in enumerate(source_frames):
                source_full_path = frame.get('name', f'frame_{i}')
                # Get just the filename part
                if '/' in source_full_path:
                    source_basename = source_full_path.rsplit('/', 1)[1]
                else:
                    source_basename = source_full_path
                source_frame_to_basename[i] = source_basename
                if i < 5:  # Only print first 5 to reduce spam
                    print(f"DEBUG: Source mapping: frame {i} -> {source_full_path} -> basename: {source_basename}")

        # Create mapping: target_filename -> target_frame_num
        # Remove job ID prefix from target filename for matching
        target_basename_to_frame = {}

        # If target is a job, we need to filter to only frames in that job
        if target_job_id:
            # Get only the frames that belong to this job
            target_job_frames = target_frames[target_start_frame:target_stop_frame + 1]
            for i, frame in enumerate(target_job_frames):
                # Use absolute task frame number as the key
                absolute_frame_num = target_start_frame + i
                target_filename = frame.get('name', f'frame_{absolute_frame_num}')

                if '/' in target_filename:
                    target_basename = target_filename.rsplit('/', 1)[1]
                else:
                    target_basename = target_filename

                # Remove job ID prefix (e.g., "30_") from filename
                clean_basename = re.sub(r'^\d+_', '', target_basename)

                # Store with absolute frame number
                target_basename_to_frame[clean_basename] = absolute_frame_num
                if i < 5:  # Only print first 5 to reduce spam
                    print(f"DEBUG: Target mapping: {target_filename} -> basename: {clean_basename} -> frame {absolute_frame_num}")
        else:
            # For task-level, use all frames
            for i, frame in enumerate(target_frames):
                target_filename = frame.get('name', f'frame_{i}')

                if '/' in target_filename:
                    target_basename = target_filename.rsplit('/', 1)[1]
                else:
                    target_basename = target_filename

                # Remove job ID prefix (e.g., "30_") from filename
                clean_basename = re.sub(r'^\d+_', '', target_basename)

                # Store just the base filename for matching
                target_basename_to_frame[clean_basename] = i
                if i < 5:  # Only print first 5 to reduce spam
                    print(f"DEBUG: Target mapping: {target_filename} -> basename: {clean_basename} -> frame {i}")

        # Create frame mapping: source_frame -> target_frame
        frame_mapping = {}
        matched_count = 0

        # Check if we have generic frame names (frame_N) - if so, match by position
        source_sample = list(source_frame_to_basename.values())[0] if source_frame_to_basename else ""
        target_sample = list(target_basename_to_frame.keys())[0] if target_basename_to_frame else ""

        use_position_matching = (source_sample.startswith('frame_') and target_sample.startswith('frame_'))

        if use_position_matching:
            print(f"DEBUG: Using position-based matching (generic frame names detected)")
            # Match by position within job
            source_frames_list = sorted(source_frame_to_basename.keys())
            target_frames_list = sorted(target_basename_to_frame.values())

            # Match frame-by-frame based on position
            for i, source_frame_num in enumerate(source_frames_list):
                if i < len(target_frames_list):
                    target_frame_num = target_frames_list[i]
                    frame_mapping[source_frame_num] = target_frame_num
                    matched_count += 1
                    if matched_count <= 5:  # Show first 5
                        print(f"DEBUG: Position match #{i}: source frame {source_frame_num} -> target frame {target_frame_num}")
        else:
            # Match by filename
            print(f"DEBUG: Using filename-based matching")
            for source_frame_num, source_basename in source_frame_to_basename.items():
                if source_basename in target_basename_to_frame:
                    target_frame_num = target_basename_to_frame[source_basename]
                    frame_mapping[source_frame_num] = target_frame_num
                    matched_count += 1
                    if matched_count <= 5:  # Show first 5
                        print(f"DEBUG: Matched {source_basename}: source frame {source_frame_num} -> target frame {target_frame_num}")

        print(f"DEBUG: Matched {matched_count} out of {len(source_frame_to_basename)} source frames")

        if matched_count == 0:
            # Show sample filenames to help diagnose the issue
            print(f"\n{'='*80}")
            print(f"ERROR: No filenames matched between source and target!")
            print(f"{'='*80}")
            print(f"Sample source basenames (first 10):")
            for basename in list(source_frame_to_basename.values())[:10]:
                print(f"  - {basename}")
            print(f"\nSample target basenames (first 10):")
            for basename in list(target_basename_to_frame.keys())[:10]:
                print(f"  - {basename}")
            print(f"{'='*80}\n")

            return jsonify({
                'success': False,
                'message': 'No matching frames found between source and target. Check that filenames match (ignoring job ID prefix).'
            }), 400

        # Remap annotations to target frame numbers
        remapped_annotations = {
            'version': source_annotations.get('version', 0),
            'tags': source_annotations.get('tags', []),
            'shapes': [],
            'tracks': []
        }

        skipped_shapes = 0
        skipped_tracks = 0

        # Debug: Show first few source annotation frame numbers
        print(f"DEBUG: First 5 source annotation frames (job-relative): {[s.get('frame') for s in source_annotations.get('shapes', [])[:5]]}")

        # Remap shapes
        for shape in source_annotations.get('shapes', []):
            source_frame_job_relative = shape.get('frame')

            # If source is a job, check if frame is already absolute or job-relative
            if source_job_id:
                # Check if frame number is already in valid range (task-absolute)
                if source_start_frame <= source_frame_job_relative <= source_stop_frame:
                    # Frame is already task-absolute
                    source_frame_absolute = source_frame_job_relative
                    if skipped_shapes == 0:
                        print(f"DEBUG: Frame {source_frame_job_relative} is already task-absolute (in range {source_start_frame}-{source_stop_frame})")
                else:
                    # Frame is job-relative, convert to task-absolute
                    source_frame_absolute = source_frame_job_relative + source_start_frame
                    if skipped_shapes == 0:
                        print(f"DEBUG: Converting frame {source_frame_job_relative} (job-relative) -> {source_frame_absolute} (task-absolute)")
            else:
                source_frame_absolute = source_frame_job_relative

            if source_frame_absolute in frame_mapping:
                target_frame = frame_mapping[source_frame_absolute]
                # Validate that target frame is within the target job's range
                if target_start_frame <= target_frame <= target_stop_frame:
                    import copy
                    new_shape = copy.deepcopy(shape)

                    # Remove fields that shouldn't be copied (server-generated)
                    new_shape.pop('id', None)
                    new_shape.pop('source', None)

                    # IMPORTANT: CVAT expects task-absolute frame numbers even when uploading to a job!
                    # Do NOT convert to job-relative
                    new_shape['frame'] = target_frame
                    if remapped_annotations['shapes'] and len(remapped_annotations['shapes']) < 3:
                        print(f"DEBUG: Target shape frame {target_frame} (task-absolute, NOT converting to job-relative)")
                    remapped_annotations['shapes'].append(new_shape)
                else:
                    print(f"DEBUG: Skipping shape - target frame {target_frame} outside job range [{target_start_frame}, {target_stop_frame}]")
                    skipped_shapes += 1
            else:
                if skipped_shapes < 5:  # Only show first 5 to avoid spam
                    source_filename = source_frames[source_frame_absolute].get('name', f'frame_{source_frame_absolute}') if source_frame_absolute < len(source_frames) else f'frame_{source_frame_absolute}'
                    print(f"DEBUG: Skipping shape - source frame {source_frame_absolute} ({source_filename}) not in frame_mapping")
                skipped_shapes += 1

        # Remap tracks
        import copy
        for track in source_annotations.get('tracks', []):
            new_track = copy.deepcopy(track)
            new_track['shapes'] = []

            # Remove server-generated fields
            new_track.pop('id', None)
            new_track.pop('source', None)

            for shape in track.get('shapes', []):
                source_frame_job_relative = shape.get('frame')

                # If source is a job, convert job-relative frame to absolute task frame
                if source_job_id:
                    source_frame_absolute = source_frame_job_relative + source_start_frame
                    print(f"DEBUG: Source track shape frame {source_frame_job_relative} (job-relative) -> {source_frame_absolute} (task-absolute)")
                else:
                    source_frame_absolute = source_frame_job_relative

                if source_frame_absolute in frame_mapping:
                    target_frame = frame_mapping[source_frame_absolute]
                    # Validate that target frame is within the target job's range
                    if target_start_frame <= target_frame <= target_stop_frame:
                        new_shape = copy.deepcopy(shape)

                        # Remove server-generated fields
                        new_shape.pop('id', None)
                        new_shape.pop('source', None)

                        # IMPORTANT: CVAT expects task-absolute frame numbers even when uploading to a job!
                        # Do NOT convert to job-relative
                        new_shape['frame'] = target_frame
                        new_track['shapes'].append(new_shape)
                    else:
                        print(f"DEBUG: Skipping track shape - target frame {target_frame} outside job range [{target_start_frame}, {target_stop_frame}]")
                        skipped_tracks += 1
                else:
                    skipped_tracks += 1

            # Only add track if it has shapes
            if new_track['shapes']:
                remapped_annotations['tracks'].append(new_track)

        import json

        print(f"DEBUG: Remapped {len(remapped_annotations['shapes'])} shapes, skipped {skipped_shapes}")
        print(f"DEBUG: Remapped {len(remapped_annotations['tracks'])} tracks, skipped {skipped_tracks} track shapes")

        # Debug: Show a sample of what we're uploading
        if remapped_annotations['shapes']:
            print(f"DEBUG: Sample shape being uploaded:")
            print(json.dumps(remapped_annotations['shapes'][0], indent=2))
        if remapped_annotations['tracks']:
            print(f"DEBUG: Sample track being uploaded:")
            print(json.dumps(remapped_annotations['tracks'][0], indent=2))

        print(f"DEBUG: Full remapped annotations structure:")
        print(f"  - Version: {remapped_annotations.get('version')}")
        print(f"  - Shapes count: {len(remapped_annotations['shapes'])}")
        print(f"  - Tracks count: {len(remapped_annotations['tracks'])}")
        print(f"  - Tags count: {len(remapped_annotations['tags'])}")

        # Show full payload being sent (first 3 shapes)
        if remapped_annotations['shapes']:
            print(f"DEBUG: First 3 shapes payload:")
            print(json.dumps(remapped_annotations['shapes'][:3], indent=2))
        else:
            print(f"DEBUG: WARNING - No shapes to upload!")

        if not remapped_annotations['shapes'] and not remapped_annotations['tracks']:
            return jsonify({
                'success': False,
                'message': 'No annotations were remapped. Check that source has annotations and filenames match between source and target.'
            }), 400

        # Remap label IDs by matching label names
        print(f"DEBUG: Remapping label IDs...")
        try:
            source_labels = source_client.get_task_labels(source_task_id)
            target_labels = target_client.get_task_labels(target_task_id)

            print(f"DEBUG: Source task has labels: {source_labels}")
            print(f"DEBUG: Target task has labels: {target_labels}")

            # Create name-based mapping: source_id -> target_id
            label_id_mapping = {}
            source_name_to_id = {name: lid for lid, name in source_labels.items()}
            target_name_to_id = {name: lid for lid, name in target_labels.items()}

            for source_id, source_name in source_labels.items():
                if source_name in target_name_to_id:
                    target_id = target_name_to_id[source_name]
                    label_id_mapping[source_id] = target_id
                    print(f"DEBUG: Label mapping: '{source_name}' {source_id} -> {target_id}")

            print(f"DEBUG: Created label ID mapping: {label_id_mapping}")

            # Remap label_ids in all shapes and tracks, removing unmapped ones
            unmapped_labels = set()
            valid_shapes = []
            skipped_label_count = 0

            for shape in remapped_annotations['shapes']:
                old_label_id = shape.get('label_id')
                if old_label_id in label_id_mapping:
                    shape['label_id'] = label_id_mapping[old_label_id]
                    valid_shapes.append(shape)
                else:
                    unmapped_labels.add(old_label_id)
                    skipped_label_count += 1

            remapped_annotations['shapes'] = valid_shapes

            valid_tracks = []
            for track in remapped_annotations['tracks']:
                old_label_id = track.get('label_id')
                if old_label_id in label_id_mapping:
                    track['label_id'] = label_id_mapping[old_label_id]
                    valid_tracks.append(track)
                else:
                    unmapped_labels.add(old_label_id)
                    skipped_label_count += 1

            remapped_annotations['tracks'] = valid_tracks

            if unmapped_labels:
                unmapped_names = [source_labels.get(lid, f'ID {lid}') for lid in unmapped_labels]
                print(f"WARNING: Skipped {skipped_label_count} annotations with unmapped labels: {unmapped_names}")
                print(f"WARNING: These labels don't exist in target task")

            print(f"DEBUG: After label remapping: {len(remapped_annotations['shapes'])} shapes, {len(remapped_annotations['tracks'])} tracks")

        except Exception as e:
            print(f"WARNING: Could not remap labels: {str(e)}")
            import traceback
            traceback.print_exc()

        # Upload remapped annotations to target
        if target_job_id:
            print(f"DEBUG: Uploading to target job {target_job_id}...")
            print(f"DEBUG: Target job range: frames {target_start_frame}-{target_stop_frame} (task-absolute)")
            print(f"DEBUG: Target job expects frame numbers: 0-{target_stop_frame - target_start_frame} (job-relative)")
            print(f"DEBUG: Uploading {len(remapped_annotations['shapes'])} shapes with frame numbers:")
            frame_numbers = [s.get('frame') for s in remapped_annotations['shapes'][:10]]
            print(f"DEBUG: First 10 frame numbers: {frame_numbers}")
            print(f"DEBUG: Frame number range: {min([s.get('frame') for s in remapped_annotations['shapes']])} to {max([s.get('frame') for s in remapped_annotations['shapes']])}")

            result = target_client.upload_job_annotations(target_job_id, remapped_annotations)
            print(f"DEBUG: Upload result: {result}")
            target_desc = f'job {target_job_id}'

            # Verify annotations were saved - wait a moment for CVAT to process
            import time
            print(f"DEBUG: Waiting 2 seconds for CVAT to process...")
            time.sleep(2)

            print(f"DEBUG: Verifying annotations were saved...")
            verification = target_client.get_job_annotations(target_job_id)
            verification_count = len(verification.get('shapes', []))
            print(f"DEBUG: Verification - Found {verification_count} shapes and {len(verification.get('tracks', []))} tracks in target")

            if verification_count > 0:
                # Check what frame numbers CVAT actually saved
                saved_frames = [s.get('frame') for s in verification.get('shapes', [])[:10]]
                print(f"DEBUG: CVAT saved first 10 shapes with frame numbers: {saved_frames}")
                print(f"DEBUG: Expected frame range: 0-{target_stop_frame - target_start_frame}")

            if verification_count == 0:
                print(f"ERROR: Upload succeeded but verification found 0 annotations!")
                print(f"ERROR: This might be a CVAT API issue or permissions problem")
                return jsonify({
                    'success': False,
                    'message': 'Upload succeeded but annotations are not visible in target job. Check CVAT permissions and job status.'
                }), 500
            elif verification_count != len(remapped_annotations['shapes']):
                print(f"WARNING: Uploaded {len(remapped_annotations['shapes'])} shapes but only {verification_count} were saved")
                print(f"WARNING: Some annotations may have been rejected by CVAT")
        else:
            print(f"DEBUG: Uploading to target task {target_task_id}...")
            result = target_client.upload_task_annotations(target_task_id, remapped_annotations)
            print(f"DEBUG: Upload result: {result}")
            target_desc = f'task {target_task_id}'

            # Verify annotations were saved
            print(f"DEBUG: Verifying annotations were saved...")
            verification = target_client.get_task_annotations(target_task_id)
            print(f"DEBUG: Verification - Found {len(verification.get('shapes', []))} shapes and {len(verification.get('tracks', []))} tracks in target")

        source_desc = f'job {source_job_id}' if source_job_id else f'task {source_task_id}'

        return jsonify({
            'success': True,
            'message': f'Successfully copied annotations from {source_desc} to {target_desc}',
            'annotations_count': len(remapped_annotations['shapes']) + len(remapped_annotations['tracks']),
            'matched_frames': matched_count,
            'source_frames': len(source_frames),
            'target_frames': len(target_frames),
            'skipped_annotations': skipped_shapes + skipped_tracks,
            'source': source_desc,
            'target': target_desc
        })

    except Exception as e:
        print(f"ERROR: Failed to copy annotations: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


class VideoFrameAnalyzer:
    """Analyzes video files to detect scene changes and motion"""

    def __init__(self):
        self.supported_formats = ['.mp4', '.avi', '.mov', '.svo', '.mkv']

    def detect_scene_changes_histogram(self, video_path, threshold=30.0, target_fps=None):
        """
        Detect scene changes using histogram comparison
        Returns list of frame indices where scene changes occur
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise Exception(f"Cannot open video file: {video_path}")

        # Calculate frame skip based on target FPS
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_skip = 1
        if target_fps and target_fps < video_fps:
            frame_skip = int(video_fps / target_fps)

        scene_changes = []
        prev_hist = None
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Skip frames if target FPS is set
            if frame_idx % frame_skip != 0:
                frame_idx += 1
                continue

            # Calculate histogram
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

            if prev_hist is not None:
                # Compare histograms using correlation
                correlation = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                # Lower correlation = more different = potential scene change
                if correlation < (1.0 - threshold / 100.0):
                    scene_changes.append(frame_idx)

            prev_hist = hist
            frame_idx += 1

        cap.release()
        return scene_changes

    def detect_scene_changes_adaptive(self, video_path, threshold=30.0, min_scene_len=15, target_fps=None):
        """
        Adaptive threshold scene detection using frame difference
        More robust for various video types
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise Exception(f"Cannot open video file: {video_path}")

        # Calculate frame skip based on target FPS
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_skip = 1
        if target_fps and target_fps < video_fps:
            frame_skip = int(video_fps / target_fps)

        scene_changes = [0]  # First frame is always a scene boundary
        prev_frame = None
        frame_idx = 0
        differences = []

        # First pass: collect frame differences
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Skip frames if target FPS is set
            if frame_idx % frame_skip != 0:
                frame_idx += 1
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (640, 360))  # Resize for faster processing

            if prev_frame is not None:
                diff = cv2.absdiff(prev_frame, gray)
                mean_diff = np.mean(diff)
                differences.append((frame_idx, mean_diff))

            prev_frame = gray
            frame_idx += 1

        cap.release()

        if not differences:
            return scene_changes

        # Calculate adaptive threshold
        diff_values = [d[1] for d in differences]
        mean_diff = np.mean(diff_values)
        std_diff = np.std(diff_values)
        adaptive_threshold = mean_diff + (threshold / 100.0) * std_diff

        # Find scene changes using adaptive threshold
        last_scene_frame = 0
        for frame_idx, diff_value in differences:
            if diff_value > adaptive_threshold and (frame_idx - last_scene_frame) >= min_scene_len:
                scene_changes.append(frame_idx)
                last_scene_frame = frame_idx

        return scene_changes

    def detect_motion_frames(self, video_path, motion_threshold=2.0, min_motion_pixels=500, target_fps=None):
        """
        Detect frames with motion using frame differencing
        Returns dict with frame indices and motion scores
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise Exception(f"Cannot open video file: {video_path}")

        # Calculate frame skip based on target FPS
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_skip = 1
        if target_fps and target_fps < video_fps:
            frame_skip = int(video_fps / target_fps)

        motion_data = {}
        prev_frame = None
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Skip frames if target FPS is set
            if frame_idx % frame_skip != 0:
                frame_idx += 1
                continue

            # Convert to grayscale and blur to reduce noise
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            gray = cv2.resize(gray, (640, 360))

            if prev_frame is None:
                prev_frame = gray
                motion_data[frame_idx] = {'motion_score': 0.0, 'motion_pixels': 0, 'has_motion': True}  # Keep first frame
                frame_idx += 1
                continue

            # Calculate frame difference
            frame_diff = cv2.absdiff(prev_frame, gray)
            thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]

            # Dilate to fill gaps
            thresh = cv2.dilate(thresh, None, iterations=2)

            # Count motion pixels
            motion_pixels = cv2.countNonZero(thresh)
            motion_score = np.mean(frame_diff)

            has_motion = motion_pixels > min_motion_pixels or motion_score > motion_threshold

            motion_data[frame_idx] = {
                'motion_score': float(motion_score),
                'motion_pixels': int(motion_pixels),
                'has_motion': bool(has_motion)
            }

            prev_frame = gray
            frame_idx += 1

        cap.release()
        return motion_data

    def get_video_info(self, video_path):
        """Get basic video information"""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise Exception(f"Cannot open video file: {video_path}")

        info = {
            'total_frames': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            'fps': cap.get(cv2.CAP_PROP_FPS),
            'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            'duration_seconds': 0
        }

        if info['fps'] > 0:
            info['duration_seconds'] = info['total_frames'] / info['fps']

        cap.release()
        return info


@app.route('/api/analyze-video', methods=['POST'])
def analyze_video():
    """Analyze video file for scene changes and motion"""
    if 'video' not in request.files:
        return jsonify({'success': False, 'message': 'No video file uploaded'}), 400

    video_file = request.files['video']
    if video_file.filename == '':
        return jsonify({'success': False, 'message': 'No video file selected'}), 400

    # Get analysis parameters
    method = request.form.get('method', 'adaptive')
    scene_threshold = float(request.form.get('scene_threshold', 30.0))
    motion_threshold = float(request.form.get('motion_threshold', 2.0))
    min_scene_length = int(request.form.get('min_scene_length', 15))
    min_motion_pixels = int(request.form.get('min_motion_pixels', 500))
    target_fps = request.form.get('target_fps')
    if target_fps:
        target_fps = float(target_fps)

    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(video_file.filename).suffix) as tmp_file:
            video_file.save(tmp_file.name)
            tmp_path = tmp_file.name

        analyzer = VideoFrameAnalyzer()

        # Get video info
        video_info = analyzer.get_video_info(tmp_path)

        # Detect scene changes
        if method == 'histogram':
            scene_changes = analyzer.detect_scene_changes_histogram(tmp_path, scene_threshold, target_fps)
        else:  # adaptive
            scene_changes = analyzer.detect_scene_changes_adaptive(tmp_path, scene_threshold, min_scene_length, target_fps)

        # Detect motion
        motion_data = analyzer.detect_motion_frames(tmp_path, motion_threshold, min_motion_pixels, target_fps)

        # Calculate statistics
        frames_with_motion = sum(1 for data in motion_data.values() if data['has_motion'])
        frames_without_motion = len(motion_data) - frames_with_motion

        # Calculate analyzed frame info
        analyzed_frames = len(motion_data)
        if target_fps:
            video_fps = video_info['fps']
            frame_skip = int(video_fps / target_fps) if target_fps < video_fps else 1
            video_info['analyzed_frames'] = analyzed_frames
            video_info['frame_skip'] = frame_skip
            video_info['target_fps'] = target_fps
            video_info['original_fps'] = video_fps
        else:
            video_info['analyzed_frames'] = video_info['total_frames']

        # Clean up
        os.unlink(tmp_path)

        return jsonify({
            'success': True,
            'video_info': video_info,
            'scene_changes': scene_changes,
            'scene_count': len(scene_changes),
            'motion_data': motion_data,
            'frames_with_motion': frames_with_motion,
            'frames_without_motion': frames_without_motion,
            'method': method
        })

    except Exception as e:
        # Clean up on error
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/filter-frames', methods=['POST'])
def filter_frames():
    """Filter frames based on scene changes and motion detection"""
    data = request.json

    motion_data = data.get('motion_data', {})
    scene_changes = data.get('scene_changes', [])
    filter_mode = data.get('filter_mode', 'motion')  # 'motion', 'scenes', 'both'

    selected_frames = []

    if filter_mode == 'scenes':
        # Select frames at scene boundaries
        selected_frames = scene_changes
    elif filter_mode == 'motion':
        # Select frames with motion
        selected_frames = [int(frame_idx) for frame_idx, data in motion_data.items() if data.get('has_motion', False)]
    elif filter_mode == 'both':
        # Select frames that are either scene changes OR have motion
        motion_frames = set(int(frame_idx) for frame_idx, data in motion_data.items() if data.get('has_motion', False))
        scene_frames = set(scene_changes)
        selected_frames = sorted(list(motion_frames | scene_frames))

    return jsonify({
        'success': True,
        'selected_frames': selected_frames,
        'count': len(selected_frames),
        'filter_mode': filter_mode
    })


@app.route('/api/download-video-frames', methods=['POST'])
def download_video_frames():
    """Extract and download selected frames from video as ZIP file"""
    if 'video' not in request.files:
        return jsonify({'success': False, 'message': 'No video file uploaded'}), 400

    video_file = request.files['video']
    if video_file.filename == '':
        return jsonify({'success': False, 'message': 'No video file selected'}), 400

    # Get selected frame indices
    try:
        import json
        frame_indices_str = request.form.get('frame_indices', '[]')
        frame_indices = json.loads(frame_indices_str)
        frame_indices = [int(idx) for idx in frame_indices]
    except Exception as e:
        return jsonify({'success': False, 'message': f'Invalid frame indices: {str(e)}'}), 400

    if not frame_indices:
        return jsonify({'success': False, 'message': 'No frames selected'}), 400

    try:
        # Save uploaded video temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(video_file.filename).suffix) as tmp_video:
            video_file.save(tmp_video.name)
            tmp_video_path = tmp_video.name

        # Open video file
        cap = cv2.VideoCapture(tmp_video_path)
        if not cap.isOpened():
            os.unlink(tmp_video_path)
            return jsonify({'success': False, 'message': 'Cannot open video file'}), 500

        # Create a ZIP file in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            for frame_idx in frame_indices:
                if frame_idx >= total_frames:
                    continue

                # Seek to the specific frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()

                if not ret:
                    print(f"Warning: Could not read frame {frame_idx}")
                    continue

                # Encode frame as JPEG
                success, buffer = cv2.imencode('.jpg', frame)
                if not success:
                    print(f"Warning: Could not encode frame {frame_idx}")
                    continue

                # Add to ZIP with padded filename for proper sorting
                filename = f"frame_{frame_idx:06d}.jpg"
                zip_file.writestr(filename, buffer.tobytes())

        cap.release()
        os.unlink(tmp_video_path)

        # Prepare ZIP for download
        zip_buffer.seek(0)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"selected_frames_{timestamp}.zip"

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )

    except Exception as e:
        # Clean up on error
        if 'tmp_video_path' in locals() and os.path.exists(tmp_video_path):
            os.unlink(tmp_video_path)
        if 'cap' in locals():
            cap.release()
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)

    print("=" * 60)
    print("CVAT Image Selector")
    print("=" * 60)
    print(f"CVAT URL: {CVAT_URL or 'Not set'}")
    print(f"Username: {CVAT_USERNAME or 'Not set'}")
    print("=" * 60)
    print("\nStarting server at http://localhost:5000")
    print("Press Ctrl+C to stop\n")

    app.run(debug=True, host='0.0.0.0', port=5020)
