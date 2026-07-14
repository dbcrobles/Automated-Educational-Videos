"""Node 0 — Research worker (long-form pipeline).

Polls for Pending_Research videos, runs the automated researcher, converts the
dossier into a ResearchArtifact, and sets status to QA_Research for dashboard
review. Spend is logged with stage='research' so cost_events distinguishes it
from the legacy short-form script stage.
"""
import os
import sys
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from nodes.research.researcher import _build_research_dossier
from schemas.research_artifact import from_dossier, ResearchArtifact

from google import genai


def _load_accounts_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'accounts_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)


def run():
    print("Node 0: Research worker started.")
    videos = database.fetch_videos_by_status('Pending_Research')
    for video in videos:
        if video.get('format') != 'long':
            continue
        print(f"Node 0: Processing video ID {video['id']}: {video['topic']}")

        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise Exception("GEMINI_API_KEY environment variable not set.")
            client = genai.Client(api_key=api_key)

            accounts_config = _load_accounts_config()
            account_settings = accounts_config.get(video['account_id'], {})
            research_profile = account_settings.get('research_profile', {
                'anchor_source_types': ['primary research', 'official data',
                                        'reputable explanatory reporting'],
                'preferred_publishers': [],
                'required_lenses': ['mechanism', 'human impact', 'limitations'],
            })

            dossier, _verified_urls = _build_research_dossier(
                client, video['topic'], research_profile, video['id'],
                cost_stage='research')

            artifact = from_dossier(dossier, video['topic'])
            artifact_json = artifact.model_dump_json()

            cost = database.cost_status(video['id'])
            if cost == 'hard':
                database.pause_for_cost(video['id'], 'research')
                print(f"Node 0: Video {video['id']} paused at hard cost tier.")
                continue

            database.update_video(video['id'], {
                'research_dossier': json.dumps(dossier),
                'research_artifact': artifact_json,
                'status': 'QA_Research',
                'error_message': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 0')
            print(f"Node 0: Video {video['id']} → QA_Research")

        except Exception as e:
            error_str = str(e)
            print(f"Node 0: Failed for video ID {video['id']}: {error_str}")
            database.fail_video(
                video['id'], 'Node 0', 'RESEARCH_EXCEPTION', error_str,
                attempt=1)


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)