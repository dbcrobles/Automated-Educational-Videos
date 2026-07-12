import time
import os
import sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nodes.scripting import node1_scripting
from nodes.voice import node2_voice
from nodes.asset_fetcher import node3_asset_fetcher
from nodes.render_worker import node4_render_worker
from nodes.publisher import node6_publisher

HEARTBEAT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator.heartbeat')

def write_heartbeat():
    """Touch a file so the dashboard can show 'Engine Running / Stopped'."""
    try:
        with open(HEARTBEAT_PATH, 'w') as f:
            f.write(str(time.time()))
    except OSError:
        pass

def main():
    print("Starting Short-Form Video Generation Pipeline Orchestrator...")
    print("Running strictly sequentially to preserve 18GB memory footprint.")

    while True:
        write_heartbeat()
        try:
            # Node 1: Scripting (Gemini API)
            node1_scripting.run()

            # Node 2: Voice (ElevenLabs)
            node2_voice.run()

            # Node 3: Asset Fetching (Network IO)
            node3_asset_fetcher.run()

            # Node 4: Render Worker (FFmpeg - Heavy Memory)
            node4_render_worker.run()

            # Node 5: Publishing (WoopSocial API + Custom platforms)
            node6_publisher.run()

        except Exception as e:
            print(f"Error in orchestrator loop: {e}")

        print("Sleeping for 10 seconds before next polling cycle...")
        time.sleep(10)

if __name__ == "__main__":
    main()