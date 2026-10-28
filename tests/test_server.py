import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from reqflow.server import make_server


class ServerTests(unittest.TestCase):
    def test_read_only_live_snapshot_and_no_file_serving(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = Path(folder)
            server = make_server(flow)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                with urlopen(url) as response:
                    self.assertIn('Requirements', response.read().decode())
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                (flow / 'readiness.json').write_text(json.dumps({'approved': True, 'goal_id': 'LIVE-GOAL'}))
                with urlopen(url + '/snapshot') as response:
                    self.assertIn('LIVE-GOAL', response.read().decode())
                with self.assertRaises(HTTPError) as error:
                    urlopen(url + '/readiness.json')
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            finally:
                server.shutdown()
                worker.join()
                server.server_close()
