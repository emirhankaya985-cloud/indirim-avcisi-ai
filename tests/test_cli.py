from __future__ import annotations
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tracker.__main__ import main


class CLITests(TestCase):
    def test_empty_config_exits_without_faking_scan(self):
        with TemporaryDirectory() as directory:
            p = Path(directory) / 'config.json'
            p.write_text('{"products":[],"coupon_feeds":[]}')
            stderr = io.StringIO()
            with patch.object(sys, 'argv', ['tracker', 'run', '--config', str(p), '--state', str(Path(directory)/'state.json')]), redirect_stderr(stderr):
                code = main()
            self.assertEqual(code, 2)
            self.assertIn('At least one', stderr.getvalue())
            self.assertFalse((Path(directory)/'state.json').exists())

    def test_status_tells_truth_about_no_scan(self):
        with TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with patch.object(sys, 'argv', ['tracker', 'status', '--state', str(Path(directory)/'state.json')]), redirect_stdout(stdout):
                code = main()
            self.assertEqual(code, 0)
            data = json.loads(stdout.getvalue())
            self.assertIsNone(data['last_successful_price_scan'])
            self.assertEqual(data['tracked_products'], 0)
            self.assertEqual(data['storage_backend'], 'git-json')
