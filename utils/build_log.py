"""Per-job diagnostic build log — captures every pipeline step with timing and errors."""
import time
import traceback
import json
from datetime import datetime


class BuildLog:
    """Accumulates timestamped log entries for a single job run."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        self.entries: list[dict] = []
        self._start = time.monotonic()
        self._stage_start: float | None = None
        self._current_stage: str | None = None
        self.add("system", "Build log started", {
            "job_id": job_id,
            "timestamp": datetime.now().isoformat(),
        })

    def add(self, level: str, message: str, details: dict | None = None):
        elapsed = round(time.monotonic() - self._start, 2)
        entry = {
            "t": elapsed,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": message,
        }
        if details:
            entry["details"] = details
        self.entries.append(entry)

    def info(self, message: str, **details):
        self.add("info", message, details or None)

    def success(self, message: str, **details):
        self.add("ok", message, details or None)

    def warn(self, message: str, **details):
        self.add("warn", message, details or None)

    def error(self, message: str, exc: Exception | None = None, **details):
        if exc:
            details["error_type"] = type(exc).__name__
            details["error"] = str(exc)
            details["traceback"] = traceback.format_exc()
        self.add("ERROR", message, details or None)

    def stage_start(self, name: str, **details):
        self._current_stage = name
        self._stage_start = time.monotonic()
        self.add("stage", f"▶ {name}", details or None)

    def stage_end(self, name: str | None = None, **details):
        name = name or self._current_stage or "unknown"
        if self._stage_start is not None:
            duration = round(time.monotonic() - self._stage_start, 2)
            details["duration_s"] = duration
        self.add("stage", f"✓ {name}", details or None)
        self._stage_start = None
        self._current_stage = None

    def config(self, **params):
        self.add("config", "Job configuration", params)

    def to_text(self) -> str:
        lines = [f"=== BUILD LOG — Job #{self.job_id} ===", ""]
        for e in self.entries:
            level = e["level"].upper().ljust(6)
            line = f"[{e['ts']}] +{e['t']:>7.2f}s  {level}  {e['msg']}"
            if e.get("details"):
                for k, v in e["details"].items():
                    if k == "traceback":
                        line += f"\n{'':>30}TRACEBACK:\n{v}"
                    else:
                        val = str(v)
                        if len(val) > 200:
                            val = val[:200] + "..."
                        line += f"\n{'':>30}{k}: {val}"
            lines.append(line)
        total = round(time.monotonic() - self._start, 2)
        lines.append(f"\n=== Total elapsed: {total:.2f}s ===")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "job_id": self.job_id,
            "total_elapsed_s": round(time.monotonic() - self._start, 2),
            "entries": self.entries,
        }, indent=2)
