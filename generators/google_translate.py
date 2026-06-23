"""Google Cloud Translation API integration using GOOGLE_API_KEY (REST, no service account)."""
import re


def translate_text(text: str, target_language: str, source_language: str = "en") -> str:
    """
    Translate text using the Google Cloud Translation REST API.
    Returns original text if GOOGLE_API_KEY not set or on any error.
    """
    try:
        import config
        api_key = getattr(config, "GOOGLE_API_KEY", "")
        if not api_key:
            return text

        import requests
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload = {
            "q": text,
            "target": target_language,
            "source": source_language,
            "format": "text",
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        translations = data.get("data", {}).get("translations", [])
        if translations:
            return translations[0].get("translatedText", text)
        return text
    except Exception as e:
        print(f"[translate] translate_text failed ({e})")
        return text


def translate_script(script: str, target_language: str, source_language: str = "en") -> str:
    """
    Translate a full video script, preserving structure.
    Chunks long scripts to stay within API limits, translates each, reassembles.
    Returns original script if GOOGLE_API_KEY not set or on any error.
    """
    try:
        import config
        api_key = getattr(config, "GOOGLE_API_KEY", "")
        if not api_key:
            return script

        # Split into paragraphs to preserve structure
        paragraphs = re.split(r'\n\n+', script)
        translated_paragraphs = []
        chunk = []
        chunk_size = 0
        max_chunk_chars = 4000

        def flush_chunk(ch):
            if not ch:
                return []
            combined = "\n\n".join(ch)
            translated = translate_text(combined, target_language, source_language)
            return translated.split("\n\n")

        for para in paragraphs:
            if chunk_size + len(para) > max_chunk_chars and chunk:
                translated_paragraphs.extend(flush_chunk(chunk))
                chunk = []
                chunk_size = 0
            chunk.append(para)
            chunk_size += len(para) + 2  # +2 for \n\n

        if chunk:
            translated_paragraphs.extend(flush_chunk(chunk))

        return "\n\n".join(translated_paragraphs)
    except Exception as e:
        print(f"[translate] translate_script failed ({e})")
        return script
