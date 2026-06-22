"""
gunicorn configuration for Social Optimize Machine.

Single worker process with 8 threads:
- Keeps _job_events / _studio_events dicts in shared memory (no Redis needed)
- gthread class handles SSE streaming connections without blocking
- Long worker_timeout covers video generation (can take 10+ minutes)
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
workers = 1
worker_class = "gthread"
threads = 8
worker_connections = 1000
timeout = 0          # disable per-worker timeout — generation threads are daemon
keepalive = 65       # must be > Render's 60s idle timeout
loglevel = "info"
accesslog = "-"
errorlog = "-"
preload_app = True   # load app once before forking (no fork here but good practice)
