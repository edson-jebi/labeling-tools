# SVO/MP4 Best Selector - Video Frame Analysis Feature

## Overview

The **SVO/MP4 Best Selector** is a new tab added to the CVAT Image Selector application that implements state-of-the-art computer vision techniques to automatically identify the most informative frames in video files. This tool helps you:

- **Detect scene changes** in videos using advanced algorithms
- **Remove static frames** with no movement
- **Optimize frame selection** for labeling and annotation tasks

## Supported Video Formats

- MP4 (.mp4)
- AVI (.avi)
- MOV (.mov)
- SVO (.svo) - Stereolabs ZED camera format
- MKV (.mkv)

## Features

### 1. Scene Change Detection

Two state-of-the-art methods are available:

#### **Adaptive Threshold Method (Recommended)**
- Uses statistical analysis of frame differences
- Calculates adaptive thresholds based on mean and standard deviation
- Robust across various video types and lighting conditions
- Prevents false detections with minimum scene length parameter
- **Best for:** Most use cases, especially videos with varying content and lighting

#### **Histogram Comparison Method**
- Compares HSV color space histograms between consecutive frames
- Uses correlation metrics to detect significant visual changes
- Excellent for detecting color/content changes
- **Best for:** Videos with consistent lighting but different content

### 2. Motion Detection

Implements frame differencing with advanced preprocessing:
- Gaussian blur for noise reduction
- Binary thresholding for motion segmentation
- Morphological operations (dilation) to fill gaps
- Pixel-level motion scoring
- **Removes:** Static frames, paused video segments, still camera shots

### 3. Frame Filtering Strategies

Three filtering modes to suit different needs:

1. **Scene Changes Only** - Selects frames where significant visual transitions occur
2. **Frames with Motion Only** - Selects frames with detected movement (removes static frames)
3. **Scene Changes OR Motion (Union)** - Combines both criteria for maximum coverage

## How to Use

### Step 1: Upload Video
1. Navigate to the **SVO/MP4 Best Selector** tab
2. Click "Select Video File" and choose your video file
3. Supported formats will be automatically detected

### Step 2: Configure Parameters

#### Scene Detection Method
- Choose between **Adaptive** (recommended) or **Histogram** methods

#### Scene Change Sensitivity (10-80%)
- **Lower values (10-30%)**: More sensitive, detects smaller changes
- **Higher values (40-80%)**: Less sensitive, only major scene changes
- **Default: 30%**

#### Motion Detection Sensitivity (0.5-10.0)
- Threshold for detecting movement between frames
- **Lower values**: More sensitive to subtle motion
- **Higher values**: Only detect significant movement
- **Default: 2.0**

#### Minimum Scene Length (5-60 frames)
- Prevents detecting very short scene changes (reduces noise)
- Useful for filtering out camera jitter or brief transitions
- **Default: 15 frames**

### Step 3: Analyze Video
1. Click **"Analyze Video"** button
2. Wait for processing (depends on video length)
3. View results:
   - Total frames and video information
   - Scene changes detected
   - Frames with motion
   - Static frames count

### Step 4: Apply Filter
1. Select your **Frame Selection Strategy**
2. Click **"Apply Filter & Select Frames"**
3. Review the results:
   - Selected frame count
   - Removed frames (with percentage)
   - Frame indices list
   - Analysis summary

## Technical Implementation

### Computer Vision Techniques Used

1. **Adaptive Statistical Thresholding**
   - Analyzes frame difference distributions
   - Calculates dynamic thresholds: `threshold = mean + (sensitivity × std_dev)`
   - Robust to varying video characteristics

2. **HSV Color Space Analysis**
   - Converts frames to HSV color space for better color change detection
   - Calculates normalized histograms (50×60 bins)
   - Uses correlation comparison (HISTCMP_CORREL)

3. **Frame Differencing with Gaussian Blur**
   - Converts frames to grayscale
   - Applies Gaussian blur (21×21 kernel) to reduce noise
   - Computes absolute difference between consecutive frames
   - Binary thresholding (threshold=25) for motion segmentation

4. **Morphological Operations**
   - Dilation (2 iterations) to fill gaps in motion regions
   - Reduces false negatives from partial object detection

5. **Motion Scoring**
   - Counts non-zero pixels in binary difference image
   - Calculates mean frame difference as motion score
   - Dual-criteria detection: pixel count AND motion score

### Performance Optimizations

- Frame resizing to 640×360 for faster processing
- Single-pass algorithms for real-time performance
- Efficient NumPy array operations
- Temporary file handling with automatic cleanup

## API Endpoints

### POST /api/analyze-video
Analyzes uploaded video file for scene changes and motion.

**Parameters:**
- `video` (file): Video file to analyze
- `method` (string): 'adaptive' or 'histogram'
- `scene_threshold` (float): Scene change sensitivity (10-80)
- `motion_threshold` (float): Motion detection sensitivity (0.5-10.0)
- `min_scene_length` (int): Minimum scene length in frames (5-60)

**Returns:**
```json
{
  "success": true,
  "video_info": {
    "total_frames": 1000,
    "fps": 30.0,
    "width": 1920,
    "height": 1080,
    "duration_seconds": 33.33
  },
  "scene_changes": [0, 45, 120, 305, ...],
  "scene_count": 15,
  "motion_data": {
    "0": {"motion_score": 0, "motion_pixels": 0, "has_motion": true},
    "1": {"motion_score": 2.5, "motion_pixels": 1200, "has_motion": true},
    ...
  },
  "frames_with_motion": 800,
  "frames_without_motion": 200,
  "method": "adaptive"
}
```

### POST /api/filter-frames
Filters frames based on analysis results.

**Parameters:**
```json
{
  "motion_data": {...},
  "scene_changes": [...],
  "filter_mode": "motion|scenes|both"
}
```

**Returns:**
```json
{
  "success": true,
  "selected_frames": [0, 1, 2, 5, 7, ...],
  "count": 750,
  "filter_mode": "motion"
}
```

## Use Cases

### 1. Video Annotation for Machine Learning
- Remove redundant static frames before labeling
- Focus annotation efforts on frames with meaningful content
- Reduce dataset size while maintaining information

### 2. Surveillance Video Analysis
- Extract key frames from long surveillance footage
- Identify scene transitions (person entering/leaving)
- Skip static periods with no activity

### 3. Action Recognition Datasets
- Select frames with actual movement
- Remove paused or still segments
- Ensure temporal consistency in annotations

### 4. Video Summarization
- Extract representative frames from each scene
- Create video thumbnails or previews
- Generate keyframe sequences

## Tips for Best Results

1. **Start with defaults** and adjust based on your specific video
2. **For noisy videos**: Increase minimum scene length
3. **For subtle changes**: Lower scene change sensitivity
4. **For fast-paced videos**: Use adaptive method with moderate sensitivity
5. **For static camera**: Motion detection works best
6. **For multi-scene videos**: Scene change detection is more appropriate

## Dependencies

The feature requires the following Python packages (automatically installed via requirements.txt):

```
opencv-python>=4.8.0
numpy>=1.24.0
```

## Troubleshooting

### Video won't upload
- Check file format is supported
- Ensure file size is reasonable (<500MB recommended)
- Verify video is not corrupted

### Too many/few scenes detected
- Adjust scene change sensitivity slider
- Increase/decrease minimum scene length
- Try different detection method

### Motion detection too sensitive
- Increase motion threshold
- Increase minimum motion pixels parameter
- Consider using scene detection instead

### Application crashes during analysis
- Check video file integrity
- Reduce video resolution if very large
- Ensure sufficient disk space for temporary files

## Future Enhancements

Potential improvements for future versions:

1. **PySceneDetect Integration** - Add support for more advanced scene detection algorithms
2. **Optical Flow Analysis** - Implement Lucas-Kanade or Farneback optical flow for better motion detection
3. **Deep Learning Models** - Use pre-trained models for semantic scene understanding
4. **Batch Processing** - Process multiple videos simultaneously
5. **Frame Export** - Export selected frames directly as images
6. **CVAT Integration** - Automatically upload selected frames to CVAT tasks

## References

### State-of-the-art Scene Detection
- PySceneDetect: https://scenedetect.com/
- OpenCV Video Analysis: https://docs.opencv.org/4.x/d7/d8b/tutorial_py_lucas_kanade.html

### Motion Detection Techniques
- Frame Differencing: https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html
- Gaussian Blur: https://docs.opencv.org/4.x/d4/d13/tutorial_py_filtering.html

### Color Space Analysis
- HSV Color Space: https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html
- Histogram Comparison: https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html

## License

This feature is part of the CVAT Image Selector application and follows the same license terms.
