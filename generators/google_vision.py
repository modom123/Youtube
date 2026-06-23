"""Google Cloud Vision API integration for thumbnail quality scoring (REST, no service account)."""
import base64
from pathlib import Path


def score_thumbnail(image_path: Path) -> dict:
    """
    Analyze a thumbnail image and return quality metrics using Google Cloud Vision API.
    Returns dict with score, has_face, has_text, dominant_colors, labels, brightness, safe, suggestions.
    Returns empty dict if GOOGLE_API_KEY not set or image not found or on any error.
    """
    try:
        import config
        api_key = getattr(config, "GOOGLE_API_KEY", "")
        if not api_key:
            return {}

        image_path = Path(image_path)
        if not image_path.exists():
            return {}

        import requests

        # Read and base64-encode the image
        image_bytes = image_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        payload = {
            "requests": [{
                "image": {"content": image_b64},
                "features": [
                    {"type": "LABEL_DETECTION", "maxResults": 10},
                    {"type": "FACE_DETECTION"},
                    {"type": "TEXT_DETECTION"},
                    {"type": "SAFE_SEARCH_DETECTION"},
                    {"type": "IMAGE_PROPERTIES"},
                ],
            }]
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json().get("responses", [{}])[0]

        # Parse faces
        faces = result.get("faceAnnotations", [])
        has_face = len(faces) > 0

        # Parse text
        text_annotations = result.get("textAnnotations", [])
        has_text = len(text_annotations) > 0

        # Parse labels
        labels = [la["description"] for la in result.get("labelAnnotations", [])[:10]]

        # Parse safe search
        safe_search = result.get("safeSearchAnnotation", {})
        unsafe_categories = {"LIKELY", "VERY_LIKELY"}
        is_safe = not any(
            safe_search.get(k, "UNKNOWN") in unsafe_categories
            for k in ("adult", "violence", "racy")
        )

        # Parse image properties (dominant colors)
        dominant_colors = []
        brightness_vals = []
        img_props = result.get("imagePropertiesAnnotation", {})
        color_info = img_props.get("dominantColors", {}).get("colors", [])
        for c in color_info[:5]:
            color = c.get("color", {})
            r = int(color.get("red", 0))
            g = int(color.get("green", 0))
            b = int(color.get("blue", 0))
            dominant_colors.append(f"#{r:02x}{g:02x}{b:02x}")
            # Approximate brightness using perceived luminance
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            brightness_vals.append(lum * c.get("pixelFraction", 0.1))
        brightness = round(sum(brightness_vals), 2) if brightness_vals else 0.5

        # Score calculation (0-100)
        score = 50  # base
        if has_face:
            score += 20  # faces strongly boost CTR
        if has_text:
            score += 15  # text overlay helps
        if is_safe:
            score += 10
        if brightness > 0.3:
            score += 5
        score = min(100, score)

        # Suggestions
        suggestions = []
        if not has_face:
            suggestions.append("Add a human face to boost CTR")
        if not has_text:
            suggestions.append("Add bold text overlay for context")
        if brightness < 0.3:
            suggestions.append("Increase image brightness/contrast")
        if not is_safe:
            suggestions.append("Review content — may violate platform guidelines")
        if len(labels) > 0 and labels[0].lower() in ("black", "white", "darkness"):
            suggestions.append("Use more vibrant, eye-catching colors")

        return {
            "score": score,
            "has_face": has_face,
            "has_text": has_text,
            "dominant_colors": dominant_colors,
            "labels": labels,
            "brightness": brightness,
            "safe": is_safe,
            "suggestions": suggestions,
        }
    except Exception as e:
        print(f"[vision] score_thumbnail failed ({e})")
        return {}
