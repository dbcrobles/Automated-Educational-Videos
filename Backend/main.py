import time
import os
import sys
import fcntl
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nodes.research import node0_research
from nodes.beat_script import node1b_beat_script
from nodes.scripting import node1_scripting
from nodes.storyboard import node3b_storyboard
from nodes.narration import node2b_narration
from nodes.asset_fetcher import node3_asset_fetcher
from nodes.render_worker import node4_render_worker
from nodes.render_worker import short_from_beat
from nodes.qa_gate import node5_qa_gate
from nodes.publisher import node6_publisher

HEARTBEAT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator.heartbeat')
LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator.lock')

def acquire_process_lock():
    """Prevent duplicate orchestrators from spending API credits on the same video.

    Open in append mode so a losing process never truncates the winner's PID;
    only write the PID after the lock is actually held.
    """
    lock_file = open(LOCK_PATH, 'a+')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another pipeline orchestrator is already running. Exiting.")
        lock_file.close()
        return None
    lock_file.truncate(0)
    lock_file.seek(0)
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
    print("Starting Video Pipeline Orchestrator (long-form + derived shorts)...")
    print("Running strictly sequentially to preserve 18GB memory footprint.")

    while True:
        write_heartbeat()
        try:
            # Node 0: Research (long-form pipeline)
            node0_research.run()

            # Node 1b: Beat Script (long-form pipeline)
            node1b_beat_script.run()

            # Node 1: Filler-short scripting (legacy pipeline, Pending_Script)
            node1_scripting.run()

            # Node 3b: Storyboard (long-form pipeline)
            node3b_storyboard.run()

            # Node 2b: Uploaded narration alignment (local Whisper)
            node2b_narration.run()

            # Node 3: Filler-short asset fetch (legacy pipeline, Pending_Assets)
            node3_asset_fetcher.run()

            # Node 4: Render Worker (Remotion/FFmpeg - Heavy Memory)
            node4_render_worker.run()

            # Phase 8: derived shorts (re-render one beat vertically)
            short_from_beat.run()

            # Node 5: Final-QA citation gate + description (long-form)
            node5_qa_gate.run()

            # Node 6: Publishing (WoopSocial API + Custom platforms)
            node6_publisher.run()

        except Exception as e:
            print(f"Error in orchestrator loop: {e}")

        print("Sleeping for 10 seconds before next polling cycle...")
        time.sleep(10)

if __name__ == "__main__":
    main()