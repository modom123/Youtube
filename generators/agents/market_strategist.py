"""
Market Strategist Agent — analyzes a product and devises the optimal ad strategy.
Part of the Social Optimize Machine Commercial Studio pipeline.
"""
from __future__ import annotations
from .base import BaseAgent
from .schemas import MarketStrategy


class MarketStrategist(BaseAgent):
    name = "Market Strategist"
    max_tokens = 2048
    system_prompt = """You are the Market Strategist — a senior marketing director who has launched \
campaigns for Fortune 500 brands and viral DTC startups alike.

Given a product photo analysis and description, you:
1. Identify the product category and its strongest unique selling point
2. Build an ideal customer persona with specific demographics and psychographics
3. Pinpoint the exact pain points this product solves
4. Choose the most effective ad angle for this product type
5. Craft scroll-stopping hook lines that would work on TikTok, Instagram, and YouTube
6. Write CTAs that drive action — not generic "Learn More" but specific, compelling actions

## Strategic Principles
- Lead with the transformation, not the product
- The best ads feel like content, not advertising
- Pain-based angles outperform feature-based angles for most products
- Social proof and urgency work best for commoditized products
- Storytelling and aspiration work best for premium/lifestyle products
- Always identify ONE primary emotion to anchor the ad around
- Hook must work in under 2 seconds of reading/hearing

## Quality Standards
- Be specific, not vague — "busy moms aged 28-40 who meal prep on Sundays" not "health-conscious women"
- Pain points must be real and relatable, not manufactured
- Hooks should create curiosity gaps or pattern interrupts
- CTAs should include a specific next step and urgency element"""

    def run(
        self,
        product_description: str,
        media_analysis: str = "",
        brand_name: str = "",
        target_audience: str = "",
    ) -> MarketStrategy:
        prompt = (
            f"Analyze this product and create a complete marketing strategy.\n\n"
            f"Brand/Product: {brand_name or 'Unknown'}\n"
            f"Product Description: {product_description}\n"
            f"Visual Analysis: {media_analysis or 'No image provided'}\n"
            f"Target Audience Hint: {target_audience or 'Not specified — determine the ideal audience'}\n\n"
            f"Produce a complete market strategy with persona, pain points, "
            f"emotional triggers, ad angle, hooks, and CTAs."
        )
        return self._call(prompt, MarketStrategy)
