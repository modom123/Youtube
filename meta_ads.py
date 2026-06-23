"""
Meta Ads Manager — create, launch, and track Meta ad campaigns.
Integrates with Facebook/Instagram Ads via the Marketing API.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests

log = logging.getLogger("meta_ads")

META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")


class MetaAdsManager:
    """Manages Meta ad campaigns for a user."""

    def __init__(self, access_token: str, ad_account_id: str):
        self.access_token = access_token
        self.ad_account_id = ad_account_id  # format: act_XXXX
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def _api(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an API call to Meta Marketing API."""
        url = f"{META_BASE_URL}/{endpoint}"
        params = kwargs.pop("params", {})
        params["access_token"] = self.access_token
        try:
            resp = requests.request(method, url, params=params, **kwargs, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.error("Meta API error: %s", e)
            return {"error": str(e)}

    # --- Campaign Management ---

    def create_campaign(self, name: str, objective: str = "OUTCOME_ENGAGEMENT",
                       budget_cents: int = 2000, budget_type: str = "daily") -> dict:
        """Create a new ad campaign."""
        data = {
            "name": name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": "[]",
        }
        if budget_type == "daily":
            data["daily_budget"] = budget_cents
        else:
            data["lifetime_budget"] = budget_cents
        return self._api("POST", f"{self.ad_account_id}/campaigns", data=data)

    def create_ad_set(self, campaign_id: str, name: str,
                     targeting: dict, budget_cents: int = 2000,
                     start_time: str = None, end_time: str = None,
                     optimization_goal: str = "LINK_CLICKS") -> dict:
        """Create an ad set with targeting."""
        data = {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal,
            "targeting": json.dumps(targeting),
            "status": "PAUSED",
        }
        if start_time:
            data["start_time"] = start_time
        if end_time:
            data["end_time"] = end_time
        return self._api("POST", f"{self.ad_account_id}/adsets", data=data)

    def build_targeting(self, countries: list = None, age_min: int = 18,
                       age_max: int = 65, genders: list = None,
                       interests: list = None) -> dict:
        """Build a targeting spec."""
        targeting = {
            "age_min": age_min,
            "age_max": age_max,
        }
        if countries:
            targeting["geo_locations"] = {"countries": countries}
        if genders:
            targeting["genders"] = genders  # [1] = male, [2] = female
        if interests:
            targeting["interests"] = [{"id": i["id"], "name": i["name"]} for i in interests]
        return targeting

    def create_ad_creative(self, name: str, page_id: str,
                          message: str, headline: str,
                          link_url: str, image_hash: str = None,
                          video_id: str = None, cta_type: str = "LEARN_MORE",
                          description: str = "") -> dict:
        """Create an ad creative (image or video)."""
        link_data = {
            "message": message,
            "link": link_url,
            "name": headline,
            "call_to_action": {"type": cta_type},
        }
        if description:
            link_data["description"] = description
        if image_hash:
            link_data["image_hash"] = image_hash

        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }

        if video_id:
            object_story_spec = {
                "page_id": page_id,
                "video_data": {
                    "video_id": video_id,
                    "message": message,
                    "title": headline,
                    "call_to_action": {"type": cta_type, "value": {"link": link_url}},
                },
            }

        data = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }
        return self._api("POST", f"{self.ad_account_id}/adcreatives", data=data)

    def create_ad(self, name: str, ad_set_id: str, creative_id: str) -> dict:
        """Create an ad linking a creative to an ad set."""
        data = {
            "name": name,
            "adset_id": ad_set_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": "PAUSED",
        }
        return self._api("POST", f"{self.ad_account_id}/ads", data=data)

    def upload_image(self, image_path: str) -> dict:
        """Upload an image and return its hash."""
        with open(image_path, "rb") as f:
            return self._api("POST", f"{self.ad_account_id}/adimages",
                           files={"filename": f})

    def upload_video(self, video_path: str, title: str = "") -> dict:
        """Upload a video for ad creative."""
        with open(video_path, "rb") as f:
            data = {}
            if title:
                data["title"] = title
            return self._api("POST", f"{self.ad_account_id}/advideos",
                           files={"source": f}, data=data)

    # --- Campaign Control ---

    def update_status(self, object_id: str, status: str) -> dict:
        """Update status of campaign/adset/ad. Status: ACTIVE, PAUSED, DELETED."""
        return self._api("POST", object_id, data={"status": status})

    def launch_campaign(self, campaign_id: str, ad_set_ids: list = None) -> dict:
        """Set campaign and its ad sets to ACTIVE."""
        results = {"campaign": self.update_status(campaign_id, "ACTIVE")}
        if ad_set_ids:
            results["ad_sets"] = [self.update_status(asid, "ACTIVE") for asid in ad_set_ids]
        return results

    def pause_campaign(self, campaign_id: str) -> dict:
        return self.update_status(campaign_id, "PAUSED")

    # --- Analytics ---

    def get_campaign_insights(self, campaign_id: str,
                             date_preset: str = "last_7d") -> dict:
        """Get campaign performance metrics."""
        params = {
            "fields": "impressions,clicks,spend,cpc,cpm,ctr,actions,cost_per_action_type,reach,frequency",
            "date_preset": date_preset,
        }
        return self._api("GET", f"{campaign_id}/insights", params=params)

    def get_ad_insights(self, ad_id: str, date_preset: str = "last_7d") -> dict:
        params = {
            "fields": "impressions,clicks,spend,cpc,ctr,actions,video_avg_time_watched_actions",
            "date_preset": date_preset,
        }
        return self._api("GET", f"{ad_id}/insights", params=params)

    def get_account_info(self) -> dict:
        """Get ad account details."""
        params = {"fields": "name,account_status,currency,timezone_name,amount_spent,balance"}
        return self._api("GET", self.ad_account_id, params=params)

    # --- Interest Search (for targeting) ---

    def search_interests(self, query: str) -> list:
        """Search for targetable interests."""
        params = {
            "type": "adinterest",
            "q": query,
        }
        result = self._api("GET", "search", params=params)
        return result.get("data", [])


# --- Helper: Quick Campaign Builder ---

def quick_campaign(access_token: str, ad_account_id: str, page_id: str,
                   campaign_name: str, headline: str, body: str,
                   link_url: str, image_path: str = None, video_path: str = None,
                   daily_budget_cents: int = 2000,
                   countries: list = None, age_min: int = 18, age_max: int = 65,
                   cta_type: str = "LEARN_MORE") -> dict:
    """
    One-call campaign builder: creates campaign → ad set → creative → ad.
    Returns dict with all created object IDs.
    """
    mgr = MetaAdsManager(access_token, ad_account_id)

    result = {"status": "created", "objects": {}}

    # 1. Campaign
    campaign = mgr.create_campaign(campaign_name, budget_cents=daily_budget_cents)
    if "error" in campaign:
        return {"status": "error", "error": campaign["error"], "step": "campaign"}
    campaign_id = campaign.get("id")
    result["objects"]["campaign_id"] = campaign_id

    # 2. Targeting
    targeting = mgr.build_targeting(
        countries=countries or ["US"],
        age_min=age_min, age_max=age_max,
    )

    # 3. Ad Set
    ad_set = mgr.create_ad_set(campaign_id, f"{campaign_name} - Ad Set", targeting,
                                budget_cents=daily_budget_cents)
    if "error" in ad_set:
        return {"status": "error", "error": ad_set["error"], "step": "ad_set"}
    ad_set_id = ad_set.get("id")
    result["objects"]["ad_set_id"] = ad_set_id

    # 4. Upload media
    image_hash = None
    video_id = None
    if video_path:
        upload = mgr.upload_video(video_path, title=campaign_name)
        video_id = upload.get("id")
        result["objects"]["video_id"] = video_id
    elif image_path:
        upload = mgr.upload_image(image_path)
        images = upload.get("images", {})
        if images:
            image_hash = list(images.values())[0].get("hash")
            result["objects"]["image_hash"] = image_hash

    # 5. Creative
    creative = mgr.create_ad_creative(
        f"{campaign_name} - Creative", page_id,
        message=body, headline=headline, link_url=link_url,
        image_hash=image_hash, video_id=video_id, cta_type=cta_type,
    )
    if "error" in creative:
        return {"status": "error", "error": creative["error"], "step": "creative"}
    creative_id = creative.get("id")
    result["objects"]["creative_id"] = creative_id

    # 6. Ad
    ad = mgr.create_ad(f"{campaign_name} - Ad", ad_set_id, creative_id)
    if "error" in ad:
        return {"status": "error", "error": ad["error"], "step": "ad"}
    result["objects"]["ad_id"] = ad.get("id")

    return result
