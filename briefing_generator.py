"""
Briefing Generator
Two-pass approach:
  1. Summarize each report individually (handles large PDFs)
  2. Synthesize all summaries into a 3-tier daily briefing
"""

import os
from datetime import datetime
from typing import List, Dict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class BriefingGenerator:

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.model = "gpt-4o"

    # ------------------------------------------------------------------
    # Pass 1: Summarize each report
    # ------------------------------------------------------------------

    def summarize_report(self, report: Dict) -> Dict:
        """Extract key data from a single report."""
        # Truncate content to fit context window (~100K chars ≈ 25K tokens)
        content = report.get('content', '')[:100000]

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": """You are a sell-side research analyst assistant.
Extract the following from this research report in concise bullet points:
- **Ticker(s)** covered
- **Rating** and **Price Target** (if mentioned)
- **Key thesis / conclusion** (1-2 sentences)
- **Notable data points** (revenue, EPS, growth figures, survey results)
- **Rating or price target changes** (upgrades, downgrades, PT revisions)
- **Catalysts** (upcoming events, earnings dates, product launches)
- **Risks** mentioned
Keep it concise. Use exact numbers from the report."""},
                {"role": "user", "content": f"Report by {report.get('analyst', 'Unknown')} "
                 f"({report.get('source', 'Unknown')}, {report.get('date', 'Unknown')}):\n\n{content}"}
            ],
        )

        summary = response.choices[0].message.content
        return {**report, 'summary': summary, 'content': content[:500] + '...'}

    # ------------------------------------------------------------------
    # Pass 2: Synthesize into 3-tier briefing
    # ------------------------------------------------------------------

    def generate_briefing(self, summaries: List[Dict],
                          tickers: List[str], themes: List[str]) -> str:
        """Synthesize report summaries into a 3-tier daily briefing."""

        summaries_text = ""
        for i, s in enumerate(summaries, 1):
            summaries_text += (
                f"\n--- Report {i} ---\n"
                f"Analyst: {s.get('analyst', 'N/A')}\n"
                f"Source: {s.get('source', 'N/A')}\n"
                f"Date: {s.get('date', 'N/A')}\n"
                f"Summary:\n{s.get('summary', 'N/A')}\n"
            )

        date_str = datetime.now().strftime('%B %d, %Y')

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": f"""You are preparing a daily briefing for a portfolio analyst.

ANALYST'S COVERAGE:
Tickers: {', '.join(tickers)}
Themes: {', '.join(themes)}

OUTPUT FORMAT (follow exactly):

# Daily Briefing - {date_str}

## TIER 1: WHAT DEMANDS ATTENTION TODAY
(Urgent — something broke, is about to happen, or contradicts current thesis)
- [Concise bullets with tickers in **bold**, cite source briefly e.g. "Thill, Jefferies 1/21"]

## TIER 2: WHAT'S THE SIGNAL FROM THE NOISE
(Important — synthesis across reports, where analysts agree/disagree)
- [Cross-report themes, consensus vs. divergence, data vs. narrative gaps]

## TIER 3: HOW DOES THIS AFFECT MY WORK
(Reference — implications for covered stocks and investment theses)
- [Direct impact on tracked tickers and themes, exploration opportunities]

RULES:
- Max 5 pages. Concise bullets only.
- Bold all **tickers** and **key terms**.
- Prioritize actionability: "what does this mean" not just "what happened".
- If a section has nothing relevant, write "No significant updates".
- Only include information relevant to the analyst's tickers and themes."""},
                {"role": "user", "content": f"Here are today's report summaries:\n{summaries_text}\n\n"
                 "Generate the daily briefing."}
            ],
        )

        return response.choices[0].message.content


def generate_email_html(briefing_text: str) -> str:
    """Convert markdown briefing to styled HTML for email delivery."""
    return f"""<!DOCTYPE html>
<html><head><style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; line-height: 1.6;
       color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
h2 {{ color: #34495e; margin-top: 30px; border-bottom: 2px solid #ecf0f1; padding-bottom: 5px; }}
li {{ margin-bottom: 8px; }}
strong {{ color: #e74c3c; }}
</style></head>
<body><pre style="white-space: pre-wrap; font-family: inherit;">{briefing_text}</pre></body></html>"""
