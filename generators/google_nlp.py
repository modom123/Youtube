"""Google Cloud Natural Language API integration using GOOGLE_API_KEY (REST, no service account)."""

_google_key_failed = False


def extract_seo_data(script: str) -> dict:
    """
    Extract entities, sentiment, and categories from a script for SEO.
    Returns dict with entities, sentiment, categories, suggested_tags, description_keywords.
    Returns empty dict if GOOGLE_API_KEY not set or on any error.
    """
    global _google_key_failed
    if _google_key_failed:
        return {}

    try:
        import config
        api_key = getattr(config, "GOOGLE_API_KEY", "")
        if not api_key:
            return {}

        import requests

        text = script[:10000]
        doc = {"type": "PLAIN_TEXT", "content": text}

        entities = []
        try:
            url = f"https://language.googleapis.com/v1/documents:analyzeEntities?key={api_key}"
            resp = requests.post(url, json={"document": doc, "encodingType": "UTF8"}, timeout=10)
            if resp.status_code in (400, 401, 403):
                print(f"[nlp] Google API key rejected ({resp.status_code}) — skipping NLP for this session")
                _google_key_failed = True
                return {}
            resp.raise_for_status()
            entity_data = resp.json().get("entities", [])
            entity_data.sort(key=lambda e: e.get("salience", 0), reverse=True)
            entities = [e["name"] for e in entity_data[:20] if e.get("name")]
        except requests.exceptions.RequestException as e:
            print(f"[nlp] analyzeEntities failed ({e})")
            return {}

        sentiment_label = "neutral"
        try:
            url = f"https://language.googleapis.com/v1/documents:analyzeSentiment?key={api_key}"
            resp = requests.post(url, json={"document": doc, "encodingType": "UTF8"}, timeout=10)
            resp.raise_for_status()
            score = resp.json().get("documentSentiment", {}).get("score", 0)
            if score > 0.25:
                sentiment_label = "positive"
            elif score < -0.25:
                sentiment_label = "negative"
        except Exception as e:
            print(f"[nlp] analyzeSentiment failed ({e})")

        categories = []
        try:
            url = f"https://language.googleapis.com/v1/documents:classifyText?key={api_key}"
            if len(text.split()) >= 20:
                resp = requests.post(url, json={"document": doc}, timeout=10)
                resp.raise_for_status()
                cats = resp.json().get("categories", [])
                categories = [c["name"].split("/")[-1] for c in cats[:5] if c.get("name")]
        except Exception as e:
            print(f"[nlp] classifyText failed ({e})")

        all_tags = list(dict.fromkeys(entities[:10] + categories[:5]))
        suggested_tags = [t.lower().replace(" ", "") for t in all_tags][:15]
        description_keywords = entities[:10]

        return {
            "entities": entities,
            "sentiment": sentiment_label,
            "categories": categories,
            "suggested_tags": suggested_tags,
            "description_keywords": description_keywords,
        }
    except Exception as e:
        print(f"[nlp] extract_seo_data failed ({e})")
        return {}
