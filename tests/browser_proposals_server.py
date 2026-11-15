# Throwaway server for tests/browser_proposals_panel.mjs: the real app pointed at a proposals folder given on the command line. Nothing is faked.
# Usage: python3 -I tests/browser_proposals_server.py <proposals folder> <port>. The features folder is a sibling of the proposals folder.
import os
import sys
from pathlib import Path

proposals, port = Path(sys.argv[1]), int(sys.argv[2])
features = proposals.parent / 'features'
features.mkdir(parents=True, exist_ok=True)
os.environ['REPOSCOUT_PROPOSALS_DIR'] = str(proposals)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.app import create_app

create_app(features).run(host='127.0.0.1', port=port)
