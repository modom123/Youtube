"""File management utilities for the Social Optimize Machine."""
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
import config


def slug(text: str, max_len: int = 40) -> str:
    """Convert text to filesystem-safe slug."""
    import re
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s)
    s = s.strip("-")
    return s[:max_len]


def job_dir(topic: str, content_type: str) -> Path:
    """Create and return a unique directory for this job."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{ts}_{slug(topic)}_{content_type}"
    path = config.OUTPUT_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_manifest(directory: Path, data: dict) -> Path:
    """Save job manifest JSON to directory."""
    manifest_path = directory / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return manifest_path


def load_manifest(directory: Path) -> Optional[dict]:
    """Load a job manifest if it exists."""
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            return json.load(f)
    return None


def list_jobs() -> list[dict]:
    """List all completed jobs from the output directory."""
    jobs = []
    for d in sorted(config.OUTPUT_DIR.iterdir(), reverse=True):
        if d.is_dir():
            manifest = load_manifest(d)
            if manifest:
                jobs.append({"directory": str(d), **manifest})
    return jobs


def get_file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def cleanup_temp_files(directory: Path, keep_patterns: list[str] = None) -> int:
    """Remove temporary files from a job directory."""
    keep_patterns = keep_patterns or ["*.mp4", "*.mp3", "*.jpg", "*.json"]
    removed = 0
    temp_dirs = ["stock_videos", "stock_images"]
    for td in temp_dirs:
        temp_path = directory / td
        if temp_path.exists():
            for f in temp_path.iterdir():
                f.unlink()
                removed += 1
            temp_path.rmdir()
    return removed
