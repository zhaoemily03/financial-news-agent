"""
Briefing Generator Module
Generates structured daily briefings following the 3-tier format
"""

import openai
import os
from datetime import datetime
from typing import List, Dict, Any


class BriefingGenerator:
    """Generates structured briefings from processed content"""

    def __init__(self):
        self.openai_key = os.getenv('OPENAI_API_KEY')
        openai.api_key = self.openai_key

    def generate_briefing(self,
                         content_items: List[Dict[str, Any]],
                         tickers: List[str],
                         themes: List[str]) -> str:
        """
        Generate a structured briefing following the 3-tier template

        Args:
            content_items: List of dicts containing {'source', 'title', 'content', 'url', 'date'}
            tickers: List of tickers the analyst covers
            themes: List of investment themes being tracked

        Returns:
            Formatted briefing text (max 5 pages)
        """

        # Prepare context for LLM
        context = self._prepare_context(content_items, tickers, themes)

        # Generate briefing using GPT
        briefing = self._call_llm_for_briefing(context, tickers, themes)

        return briefing

    def _prepare_context(self,
                        content_items: List[Dict[str, Any]],
                        tickers: List[str],
                        themes: List[str]) -> str:
        """Prepare context string from all content items"""

        context_parts = []

        for idx, item in enumerate(content_items, 1):
            context_parts.append(f"""
SOURCE #{idx}
Title: {item.get('title', 'N/A')}
Source: {item.get('source', 'N/A')}
Date: {item.get('date', 'N/A')}
URL: {item.get('url', 'N/A')}
Content:
{item.get('content', '')}
---
""")

        return "\n".join(context_parts)

    def _call_llm_for_briefing(self,
                               context: str,
                               tickers: List[str],
                               themes: List[str]) -> str:
        """Call OpenAI to generate structured briefing"""

        system_prompt = f"""You are a financial analyst assistant preparing a daily briefing.

ANALYST'S COVERAGE:
Tickers: {', '.join(tickers)}
Themes: {', '.join(themes)}

OUTPUT FORMAT (STRICTLY FOLLOW THIS STRUCTURE):

# Daily Briefing - {datetime.now().strftime('%B %d, %Y')}

## TIER 1: WHAT DEMANDS ATTENTION TODAY
(Urgent, can't miss)

### Something Broke Overnight
- [Bullet points for earnings misses/beats, rating changes, breaking news]

### Something Is About to Happen
- [Bullet points for upcoming catalysts, earnings, events]

### Something Contradicts What I Believe
- [Bullet points for thesis-challenging information]

## TIER 2: WHAT'S THE SIGNAL FROM THE NOISE
(Important, not urgent)

### Synthesis Across All Reports
- [Key themes emerging across multiple sources]

### Analyst Consensus vs. Divergence
- [Where analysts agree/disagree]

### Quantitative vs. Qualitative Divergences
- [When data and narrative diverge]

## TIER 3: HOW DOES THIS AFFECT MY WORK
(Reference)

### Implications for Covered Stocks
- [Direct impact on tracked tickers]

### Implications for Investment Theses
- [How this affects tracked themes]

### Exploration Opportunities
- [New areas worth investigating]

GUIDELINES:
- Maximum 5 pages total
- Concise bullet points only, no lengthy paragraphs
- Always cite source briefly (e.g., "JPM, 1/21" or "Substack: AuthorName")
- Focus on actionability: "what does this mean" not just "what happened"
- Use **bold** for tickers, key terms, and critical catalysts
- Prioritize within each section (most critical first)
- If a section has no relevant content, write "No significant updates"
- Only include information relevant to the analyst's tickers and themes
"""

        user_prompt = f"""Based on the following sources, generate a structured daily briefing following the 3-tier format.

SOURCES:
{context}

Generate the briefing now, following the exact format specified in your instructions."""

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=3000,  # Roughly 5 pages
                temperature=0.3  # Lower temperature for more focused output
            )

            briefing = response.choices[0].message.content
            return briefing

        except Exception as e:
            return f"Error generating briefing: {str(e)}"

    def categorize_content_by_urgency(self,
                                     content_items: List[Dict[str, Any]],
                                     tickers: List[str]) -> Dict[str, List[Dict]]:
        """
        Pre-categorize content by urgency to help LLM prioritize

        Returns:
            Dict with keys: 'urgent', 'important', 'reference'
        """

        categorized = {
            'urgent': [],
            'important': [],
            'reference': []
        }

        urgent_keywords = [
            'earnings', 'downgrade', 'upgrade', 'breaking', 'alert',
            'price target', 'guidance', 'miss', 'beat', 'surprise'
        ]

        important_keywords = [
            'outlook', 'forecast', 'trend', 'consensus', 'divergence',
            'sector', 'industry', 'competition'
        ]

        for item in content_items:
            content_lower = item.get('content', '').lower()
            title_lower = item.get('title', '').lower()

            # Check for urgent signals
            is_urgent = any(keyword in content_lower or keyword in title_lower
                          for keyword in urgent_keywords)

            # Check for ticker mentions
            has_ticker = any(ticker.lower() in content_lower or ticker.lower() in title_lower
                           for ticker in tickers)

            if is_urgent and has_ticker:
                categorized['urgent'].append(item)
            elif any(keyword in content_lower or keyword in title_lower
                    for keyword in important_keywords):
                categorized['important'].append(item)
            else:
                categorized['reference'].append(item)

        return categorized


def generate_email_html(briefing_text: str) -> str:
    """
    Convert markdown briefing to HTML email format

    Args:
        briefing_text: Markdown-formatted briefing

    Returns:
        HTML string for email
    """

    # Simple markdown to HTML conversion
    # In production, use a proper markdown library like `markdown` or `mistune`

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        h3 {{
            color: #7f8c8d;
            margin-top: 20px;
        }}
        ul {{
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 8px;
        }}
        strong {{
            color: #e74c3c;
        }}
        .tier-1 {{
            background-color: #ffe6e6;
            padding: 15px;
            border-left: 4px solid #e74c3c;
            margin-bottom: 20px;
        }}
        .tier-2 {{
            background-color: #fff4e6;
            padding: 15px;
            border-left: 4px solid #f39c12;
            margin-bottom: 20px;
        }}
        .tier-3 {{
            background-color: #e6f3ff;
            padding: 15px;
            border-left: 4px solid #3498db;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <pre style="white-space: pre-wrap; font-family: inherit;">{briefing_text}</pre>
</body>
</html>
"""

    return html
