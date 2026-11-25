from io import BytesIO
from unittest import TestCase
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser

from tracker.network import Downloader


class RedirectRobotsTests(TestCase):
    def test_redirect_to_disallowed_path_never_requested(self):
        bot = Downloader()
        rp = RobotFileParser()
        rp.parse(['User-agent: *', 'Disallow: /blocked'])
        bot.robot_cache['www.trendyol.com'] = rp
        bot.opener = MagicMock()
        url = 'https://www.trendyol.com/allowed'
        bot.opener.open.side_effect = HTTPError(
            url, 302, 'Found', {'Location': '/blocked'}, BytesIO())
        with self.assertRaises(PermissionError):
            bot.read(url, ['trendyol.com'])
        self.assertEqual(bot.opener.open.call_count, 1)

    def test_redirect_to_allowed_path_can_be_read(self):
        bot = Downloader()
        rp = RobotFileParser()
        rp.parse(['User-agent: *', 'Disallow: /blocked'])
        bot.robot_cache['www.trendyol.com'] = rp
        bot.opener = MagicMock()
        url = 'https://www.trendyol.com/allowed'
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'allowed response'
        bot.opener.open.side_effect = [
            HTTPError(url, 302, 'Found', {'Location': '/other'}, BytesIO()),
            response,
        ]
        self.assertEqual(bot.read(url, ['trendyol.com']), b'allowed response')
        self.assertEqual(bot.opener.open.call_count, 2)
