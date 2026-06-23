"""Google Cloud Natural Language API integration using GOOGLE_API_KEY (REST, no service account)."""


def extract_seo_data(script: str) -> dict:
    """
    Extract entities, sentiment, and categories from a script for SEO.
    Returns dict with entities, sentiment, categories, suggested_tags, description_keywords.
    Returns empty dict if GOOGLE_API_KEY not set or on any error.
    """
    try:
        import config
        api_key = getattr(config, "GOOGLE_API_KEY", "")
        if not api_key:
            return {}

        import requests

        # Limit script to 10000 chars for API efficiency
        text = script[:10000]
        doc = {"type": "PLAIN_TEXT", "content": text}

        # 1. Analyze entities
        entities = []
        try:
            url = f"https://language.googleapis.com/v1/documents:analyzeEntities?key={api_key}"
            resp = requests.post(url, json={"document": doc, "encodingType": "UTF8"}, timeout=30)
            resp.raise_for_status()
            entity_data = resp.json().get("entities", [])
            # Sort by salience (relevance score)
            entity_data.sort(key=lambda e: e.get("salience", 0), reverse=True)
            entities = [e["name"] for e in entity_data[:20] if e.get("name")]
        except Exception as e:
            print(f"[nlp] analyzeEntities failed ({e})")

        # 2. Analyze sentiment
        sentiment_label = "neutral"
        try:
            url = f"https://language.googleapis.com/v1/documents:analyzeSentiment?key={api_key}"
            resp = requests.post(url, json={"document": doc, "encodingType": "UTF8"}, timeout=30)
            resp.raise_for_status()
            score = resp.json().get("documentSentiment", {}).get("score", 0)
            if score > 0.25:
                sentiment_label = "positive"
            elif score < -0.25:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"
        except Exception as e:
            print(f"[nlp] analyzeSentiment failed ({e})")

        # 3. Classify text
        categories = []
        try:
            url = f"https://language.googleapis.com/v1/documents:classifyText?key={api_key}"
            # classifyText requires at least 20 tokens — skip if too short
            if len(text.split()) >= 20:
                resp = requests.post(url, json={"document": doc}, timeout=30)
                resp.raise_for_status()
                cats = resp.json().get("categories", [])
                categories = [c["name"].split("/")[-1] for c in cats[:5] if c.get("name")]
        except Exception as e:
            print(f"[nlp] classifyText failed ({e})")

        # Build SEO tags from top entities + categories
        all_tags = list(dict.fromkeys(entities[:10] + categories[:5]))
        suggested_tags = [t.lower().replace(" ", "") for t in all_tags][:15]

        # Description keywords = top salience entities as readable phrases
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
