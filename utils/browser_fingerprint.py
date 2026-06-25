"""
Browser Fingerprint Manager — anti-detection for multi-account automation.
Generates unique browser profiles with isolated cookies, user agents,
canvas fingerprints, and WebGL parameters per account.
"""
from __future__ import annotations
import hashlib
import json
import random
from pathlib import Path


CHROME_VERSIONS = [
    "120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0",
    "124.0.0.0", "125.0.0.0", "126.0.0.0", "127.0.0.0",
]

OS_PLATFORMS = [
    ("Windows NT 10.0; Win64; x64", "Win32"),
    ("Macintosh; Intel Mac OS X 10_15_7", "MacIntel"),
    ("X11; Linux x86_64", "Linux x86_64"),
    ("X11; Ubuntu; Linux x86_64", "Linux x86_64"),
]

SCREEN_RESOLUTIONS = [
    (1920, 1080), (2560, 1440), (1366, 768), (1536, 864),
    (1440, 900), (1680, 1050), (1280, 720), (3840, 2160),
]

WEBGL_VENDORS = [
    "Google Inc. (NVIDIA)",
    "Google Inc. (AMD)",
    "Google Inc. (Intel)",
    "Google Inc.",
]

WEBGL_RENDERERS = [
    "ANGLE (NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
]

LANGUAGES = [
    ["en-US", "en"],
    ["en-GB", "en"],
    ["en-US", "en", "es"],
    ["en-US", "en", "fr"],
]

TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "Europe/London", "Europe/Berlin",
    "Asia/Tokyo", "Australia/Sydney",
]


def generate_fingerprint(account_id: str, seed: str = None) -> dict:
    """Generate a deterministic but unique fingerprint for an account."""
    rng = random.Random(seed or account_id)

    os_info, platform = rng.choice(OS_PLATFORMS)
    chrome_ver = rng.choice(CHROME_VERSIONS)
    screen_w, screen_h = rng.choice(SCREEN_RESOLUTIONS)

    user_agent = (
        f"Mozilla/5.0 ({os_info}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_ver} Safari/537.36"
    )

    canvas_hash = hashlib.md5(f"canvas_{account_id}_{seed}".encode()).hexdigest()[:16]

    return {
        "user_agent": user_agent,
        "platform": platform,
        "screen_width": screen_w,
        "screen_height": screen_h,
        "color_depth": rng.choice([24, 32]),
        "timezone": rng.choice(TIMEZONES),
        "languages": rng.choice(LANGUAGES),
        "webgl_vendor": rng.choice(WEBGL_VENDORS),
        "webgl_renderer": rng.choice(WEBGL_RENDERERS),
        "canvas_hash": canvas_hash,
        "hardware_concurrency": rng.choice([2, 4, 8, 12, 16]),
        "device_memory": rng.choice([2, 4, 8, 16]),
        "do_not_track": rng.choice(["1", None]),
    }


def get_playwright_context_options(fingerprint: dict, proxy: dict = None) -> dict:
    """Convert a fingerprint to Playwright browser context options."""
    options = {
        "viewport": {
            "width": fingerprint["screen_width"],
            "height": fingerprint["screen_height"],
        },
        "user_agent": fingerprint["user_agent"],
        "locale": fingerprint["languages"][0],
        "timezone_id": fingerprint["timezone"],
        "color_scheme": "light",
        "device_scale_factor": 1,
    }
    if proxy:
        options["proxy"] = proxy
    return options


_ANTI_DETECT_JS = """
() => {
    // Override navigator.platform
    Object.defineProperty(navigator, 'platform', {
        get: () => '%PLATFORM%'
    });

    // Override navigator.hardwareConcurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => %HARDWARE_CONCURRENCY%
    });

    // Override navigator.deviceMemory
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => %DEVICE_MEMORY%
    });

    // Override navigator.languages
    Object.defineProperty(navigator, 'languages', {
        get: () => %LANGUAGES%
    });

    // Override WebGL renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return '%WEBGL_VENDOR%';
        if (parameter === 37446) return '%WEBGL_RENDERER%';
        return getParameter.call(this, parameter);
    };

    // Override canvas fingerprint
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] ^= %CANVAS_NOISE%;
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return toDataURL.call(this, type);
    };
}
"""


def get_anti_detect_script(fingerprint: dict) -> str:
    """Generate JavaScript to inject into page for fingerprint spoofing."""
    canvas_noise = int(fingerprint["canvas_hash"][:2], 16) % 5
    script = _ANTI_DETECT_JS
    script = script.replace("%PLATFORM%", fingerprint["platform"])
    script = script.replace("%HARDWARE_CONCURRENCY%", str(fingerprint["hardware_concurrency"]))
    script = script.replace("%DEVICE_MEMORY%", str(fingerprint["device_memory"]))
    script = script.replace("%LANGUAGES%", json.dumps(fingerprint["languages"]))
    script = script.replace("%WEBGL_VENDOR%", fingerprint["webgl_vendor"])
    script = script.replace("%WEBGL_RENDERER%", fingerprint["webgl_renderer"])
    script = script.replace("%CANVAS_NOISE%", str(canvas_noise))
    return script


PROFILE_DIR = Path.home() / ".social_optimize" / "browser_profiles"


def get_profile_path(account_id: str) -> Path:
    """Return isolated storage directory for an account's browser profile."""
    path = PROFILE_DIR / account_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_stealth_context(
    playwright_browser,
    account_id: str,
    proxy: dict = None,
    seed: str = None,
):
    """Create a Playwright browser context with full anti-detection."""
    fingerprint = generate_fingerprint(account_id, seed)
    ctx_options = get_playwright_context_options(fingerprint, proxy)
    profile_path = get_profile_path(account_id)

    ctx_options["storage_state"] = str(profile_path / "storage.json") \
        if (profile_path / "storage.json").exists() else None

    context = playwright_browser.new_context(**{
        k: v for k, v in ctx_options.items() if v is not None
    })

    context.add_init_script(get_anti_detect_script(fingerprint))

    return context, fingerprint
