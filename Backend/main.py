import time
import os
import sys
import fcntl
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nodes.research import node0_research
from nodes.beat_script import node1b_beat_script
from nodes.storyboard import node3b_storyboard
from nodes.scripting import node1_scripting
from nodes.voice import node2_voice
from nodes.asset_fetcher import node3_asset_fetcher
from nodes.render_worker import node4_render_worker
from nodes.publisher import node6_publisher

HEARTBEAT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator.heartbeat')
LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator.lock')

def acquire_process_lock():
    """Prevent duplicate orchestrators from spending API credits on the same video."""
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another pipeline orchestrator is already running. Exiting.")
        lock_file.close()
        return None
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file

def write_heartbeat():
    """Touch a file so the dashboard can show 'Engine Running / Stopped'."""
    try:
        with open(HEARTBEAT_PATH, 'w') as f:
            f.write(str(time.time()))
    except OSError:
        pass

def main():
    process_lock = acquire_process_lock()
    if not process_lock:
        return
    print("Starting Short-Form Video Generation Pipeline Orchestrator...")
    print("Running strictly sequentially to preserve 18GB memory footprint.")

    while True:
        write_heartbeat()
        try:
            # Node 0: Research (long-form pipeline)
            node0_research.run()

            # Node 1b: Beat Script (long-form pipeline)
            node1b_beat_script.run()

            # Node 3b: Storyboard (long-form pipeline)
            node3b_storyboard.run()

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