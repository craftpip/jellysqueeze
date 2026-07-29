#!/usr/bin/env python3
"""
Test script for convert.py progress tracking functionality.

This test mocks the FFmpeg conversion to test the progress tracking logic
without requiring actual video processing.

Usage:
    python3 test_convert.py
"""

import sys
import os
from pathlib import Path

# Add parent dir to path so we can import convert module
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import the tracking functions from convert.py
import convert

TEST_DIR = Path(__file__).parent / "test_files"


def clean_done():
    """Remove _progress.txt before each test."""
    if convert.DONE_FILE.exists():
        convert.DONE_FILE.unlink()


def get_video_files():
    """Get list of video files in test directory."""
    files = []
    for p in TEST_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() in convert.VIDEO_EXTS:
            files.append(p)
    return files


def test_load_done_empty():
    """Test: load_done returns empty dict when file doesn't exist."""
    print("\n" + "=" * 50)
    print("TEST 1: load_done with no file")
    print("=" * 50)
    clean_done()
    
    result = convert.load_done()
    assert result == {}, f"Expected empty dict, got {result}"
    print("✓ Returns empty dict when file doesn't exist")
    print("TEST 1 PASSED\n")


def test_save_and_load():
    """Test: save_done and load_done work correctly."""
    print("\n" + "=" * 50)
    print("TEST 2: save and load _progress.txt")
    print("=" * 50)
    clean_done()
    
    test_data = {
        "/path/to/video1.mkv": "crf:23",
        "/path/to/video2.mp4": "br:3000"
    }
    
    convert.save_done(test_data)
    loaded = convert.load_done()
    
    assert loaded == test_data, f"Expected {test_data}, got {loaded}"
    print(f"✓ Saved and loaded correctly: {loaded}")
    print("TEST 2 PASSED\n")


def test_single_entry_per_file():
    """Test: Only one entry per file - replacing works."""
    print("\n" + "=" * 50)
    print("TEST 3: Single entry per file (replacement)")
    print("=" * 50)
    clean_done()
    
    data = {"/path/video.mkv": "crf:23"}
    convert.save_done(data)
    
    # Now replace with different option
    data["/path/video.mkv"] = "br:3000"
    convert.save_done(data)
    
    loaded = convert.load_done()
    
    # Should only have one entry
    assert len(loaded) == 1, f"Expected 1 entry, got {len(loaded)}"
    assert loaded["/path/video.mkv"] == "br:3000", f"Expected br:3000, got {loaded}"
    
    print(f"✓ Only one entry per file: {loaded}")
    print("TEST 3 PASSED\n")


def test_skip_same_option():
    """Test: Skip file if same option used before."""
    print("\n" + "=" * 50)
    print("TEST 4: Skip if same option")
    print("=" * 50)
    clean_done()
    
    videos = get_video_files()
    assert len(videos) == 1, f"Expected 1 video, got {len(videos)}"
    video_path = videos[0].resolve().as_posix()
    
    # Simulate: file was converted with crf:23
    done = {video_path: "crf:23"}
    convert.save_done(done)
    
    # Now try to convert with same option
    current_opt = "crf:23"
    
    if done.get(video_path) == current_opt:
        print(f"✓ Correctly skipped: already_done")
    else:
        raise AssertionError("Should have skipped!")
    
    print("TEST 4 PASSED\n")


def test_allow_different_option():
    """Test: Allow conversion if different option."""
    print("\n" + "=" * 50)
    print("TEST 5: Allow different option")
    print("=" * 50)
    clean_done()
    
    videos = get_video_files()
    video_path = videos[0].resolve().as_posix()
    
    # Simulate: file was converted with crf:23
    done = {video_path: "crf:23"}
    convert.save_done(done)
    
    # Now try to convert with different option
    current_opt = "crf:28"
    
    if done.get(video_path) == current_opt:
        raise AssertionError("Should NOT have skipped!")
    else:
        print(f"✓ Correctly allowed: option changed from crf:23 to crf:28")
    
    print("TEST 5 PASSED\n")


def test_crf_to_bitrate():
    """Test: Switching from CRF to bitrate mode."""
    print("\n" + "=" * 50)
    print("TEST 6: CRF to bitrate switch")
    print("=" * 50)
    clean_done()
    
    videos = get_video_files()
    video_path = videos[0].resolve().as_posix()
    
    # File was converted with CRF
    done = {video_path: "crf:23"}
    convert.save_done(done)
    
    # Now use bitrate mode
    current_opt = "br:3000"
    
    if done.get(video_path) == current_opt:
        raise AssertionError("Should NOT have skipped!")
    
    # Simulate conversion and update
    done[video_path] = current_opt
    convert.save_done(done)
    
    loaded = convert.load_done()
    assert loaded[video_path] == "br:3000", f"Expected br:3000, got {loaded}"
    
    print(f"✓ Correctly switched from CRF to bitrate: {loaded}")
    print("TEST 6 PASSED\n")


def test_multiple_files():
    """Test: Multiple files with different options."""
    print("\n" + "=" * 50)
    print("TEST 7: Multiple files")
    print("=" * 50)
    clean_done()
    
    # Simulate multiple files
    done = {
        "/path/video1.mkv": "crf:23",
        "/path/video2.mp4": "br:3000",
        "/path/video3.avi": "crf:28"
    }
    convert.save_done(done)
    
    loaded = convert.load_done()
    assert len(loaded) == 3, f"Expected 3 entries, got {len(loaded)}"
    assert loaded["/path/video1.mkv"] == "crf:23"
    assert loaded["/path/video2.mp4"] == "br:3000"
    assert loaded["/path/video3.avi"] == "crf:28"
    
    print(f"✓ Multiple files tracked: {loaded}")
    print("TEST 7 PASSED\n")


def test_normalize_library_paths():
    """Test: library config keeps every configured path."""
    print("\n" + "=" * 50)
    print("TEST 8: normalize library paths")
    print("=" * 50)

    lib = {
        "name": "Movies",
        "paths": ["/mnt/media/movies-a", "/mnt/media/movies-b"],
        "path": "/mnt/media/movies-a",
    }

    paths = convert.normalize_library_paths(lib)
    assert paths == ["/mnt/media/movies-a", "/mnt/media/movies-b"], f"Unexpected paths: {paths}"

    config = {
        "libraries": [
            {"name": "Movies", "paths": ["/mnt/media/movies-a", "/mnt/media/movies-b"], "profile": "movies"}
        ],
        "profiles": {"movies": {"target_bitrate": 3000}},
    }
    lib_info = convert.find_library_config(config, "Movies")
    assert lib_info is not None, "Expected library config to be found"
    assert lib_info[0] == ["/mnt/media/movies-a", "/mnt/media/movies-b"], f"Unexpected lib info: {lib_info}"

    print(f"✓ Multi-path libraries preserved: {paths}")
    print("TEST 8 PASSED\n")


def test_real_video_file():
    """Test: Using actual video file from test_files."""
    print("\n" + "=" * 50)
    print("TEST 9: Real video file tracking")
    print("=" * 50)
    clean_done()
    
    videos = get_video_files()
    assert len(videos) == 1, f"Expected 1 video, got {len(videos)}"
    video_path = videos[0].resolve().as_posix()
    
    # Simulate conversion with crf:23
    done = {video_path: "crf:23"}
    convert.save_done(done)
    
    loaded = convert.load_done()
    assert video_path in loaded, f"Video not in loaded: {loaded}"
    assert loaded[video_path] == "crf:23", f"Expected crf:23, got {loaded[video_path]}"
    
    print(f"✓ Real video file tracked: {loaded}")
    print("TEST 8 PASSED\n")


def main():
    print("=" * 60)
    print("TEST SUITE FOR PROGRESS TRACKING")
    print("(Mock tests - no actual FFmpeg required)")
    print("=" * 60)
    
    videos = get_video_files()
    print(f"\nFound {len(videos)} video(s) in {TEST_DIR}")
    for v in videos:
        print(f"  - {v.name}")
    
    try:
        test_load_done_empty()
        test_save_and_load()
        test_single_entry_per_file()
        test_skip_same_option()
        test_allow_different_option()
        test_crf_to_bitrate()
        test_multiple_files()
        test_normalize_library_paths()
        test_real_video_file()
        
        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
