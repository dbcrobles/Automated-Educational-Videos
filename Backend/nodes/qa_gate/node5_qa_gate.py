"""Node 5 — Final-QA gate for long-form videos (Phase 7).

When a long-form video enters QA_Final with no citation_qa_result yet, run ONE
Gemini flash structured call (mirrors _fact_check_storyboard) comparing every
beat's spoken_text against the ResearchArtifact claims + data_points. Issues
are stored in the citation_qa_result column; the dashboard blocks Approve &
Publish while unresolved issues exist. The same pass writes the YouTube
description into the caption column for Phase 8.
"""
import os
import sys
import json
import time
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from schemas.research_artifact import ResearchArtifact
from nodes.research.researcher import GEMINI_MODEL_STRUCTURED
from nodes.publisher.node6_publisher import _readable_sources
from nodes.qa_gate.prompts import citation_check_prompt

COST_CITATION_CALL = 0.01


class CitationIssue(BaseModel):
    beat_order: int
    issue_type: Literal[
        "unsupported_claim", "number_mismatch", "missing_qualifier",
        "causal_overstatement", "stale_as_current",
    ]
    message: str
    claim_id: str = ""


class CitationReview(BaseModel):
    issues: list[CitationIssue]


def check_citations(client, video):
    """One structured flash call: every beat's spoken_text vs claims/data_points."""
    artifact = json.loads(video['research_artifact'])
    beats = json.loads(video['beats_json']).get('beats', [])
    spoken = [{'order': b.get('order'), 'spoken_text': b.get('spoken_text', '')}
              for b in beats]
    response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=citation_check_prompt(
            artifact.get('claims', []), artifact.get('data_points', []), spoken),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CitationReview,
            temperature=0,
        ),
    )
    tier = database.log_cost(video['id'], COST_CITATION_CALL, 'qa',
                             provider='google', model=GEMINI_MODEL_STRUCTURED)
    if not response.text:
        raise Exception("Citation review returned no result.")
    issues = json.loads(response.text).get('issues', [])
    return [dict(issue, resolved=False) for issue in issues], tier


def generate_description(video, artifact: ResearchArtifact):
    """YouTube description: title, summary, titled sources, AI + medical disclosures."""
    seen, details = set(), []
    for claim in artifact.claims:
        for source in claim.sources:
            if source.url and source.url not in seen:
                seen.add(source.url)
                details.append({'role': 'supporting',
                                'title': source.name, 'url': source.url})
    sources_str = _readable_sources({'source_details': details, 'sources': []})
    summary = (artifact.notes or '').strip().split('\n')[0]
    return (
        f"{artifact.title or video['topic']}\n\n{summary}\n\n"
        f"Sources:\n{sources_str}\n\n"
        "This video was made with AI assistance for research and editing; "
        "the narration is the creator's own voice.\n"
        "This content is educational only and is not medical or financial advice."
    )


def run():
    videos = [v for v in database.fetch_videos_by_status('QA_Final')
              if v.get('format') == 'long' and not v.get('citation_qa_result')]
    if not videos:
        return
    print("Node 5: QA gate worker started.")
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    for video in videos:
        try:
            if not video.get('beats_json'):
                raise Exception("No beats_json — cannot run the citation gate.")
            if not video.get('research_artifact'):
                raise Exception("No research_artifact — cannot run the citation gate.")
            issues, tier = check_citations(client, video)
            artifact = ResearchArtifact.model_validate_json(video['research_artifact'])
            database.update_video(video['id'], {
                'citation_qa_result': json.dumps({'issues': issues}),
                'caption': generate_description(video, artifact),
            })
            database.resolve_pipeline_errors(video['id'], 'Node 5')
            print(f"Node 5: Video {video['id']} citation gate → "
                  f"{len(issues)} issue(s); description written.")
            if tier == 'hard':
                database.pause_for_cost(video['id'], 'qa')
        except Exception as e:
            # Leave citation_qa_result empty: publish stays blocked and the gate
            # retries next cycle — never fail a fully rendered video over QA.
            print(f"Node 5: Citation gate failed for video {video['id']}: {e}")
            database.record_pipeline_error(
                video['id'], 'Node 5', 'CITATION_QA_FAILED', str(e))


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)