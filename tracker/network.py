"""HTTPS-only downloader with explicit redirect checks and robots compliance."""
from __future__ import annotations

from ipaddress import ip_address
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import build_opener, Request, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

USER_AGENT = 'IndirimAvcisiAI/1.0 (+personal price tracking; compliant bot)'
MAX_BYTES = 2 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_url(url: str, permitted_hosts: list[str]) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().rstrip('.')
    if parts.scheme != 'https' or not host or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError('Only ordinary HTTPS product/feed URLs are allowed')
    try:
        ip_address(host)
        raise ValueError('Literal IP addresses are not allowed')
    except ValueError as err:
        if str(err) == 'Literal IP addresses are not allowed':
            raise
    if host in ('localhost',) or host.endswith(('.local', '.internal', '.localhost', '.test')) or '.' not in host or not any(host == h or host.endswith('.' + h) for h in permitted_hosts):
        raise ValueError(f'Host is not approved: {host}')
    return url


class Downloader:
    def __init__(self) -> None:
        self.opener = build_opener(_NoRedirect())
        self.robot_cache: dict[str, RobotFileParser] = {}

    def _download(self, url: str, hosts: list[str], robots: RobotFileParser | None = None) -> bytes:
        for _ in range(4):
            validate_url(url, hosts)
            if robots is not None and not robots.can_fetch(USER_AGENT, url):
                raise PermissionError('Robots disallows requested or redirected path')
            try:
                with self.opener.open(Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html, application/xml, text/xml, */*'}), timeout=20) as resp:
                    raw = resp.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('Response exceeds 2 MB')
                    return raw
            except HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                location = exc.headers.get('Location')
                if not location:
                    raise ValueError('Redirect lacks location') from exc
                next_url = urljoin(url, location)
                validate_url(next_url, hosts)
                if urlsplit(next_url).hostname != urlsplit(url).hostname:
                    raise PermissionError('Cross-host redirect requires an independent robots check')
                url = next_url
        raise ValueError('Too many redirects')

    def read(self, url: str, hosts: list[str], respect_robots: bool = True) -> bytes:
        validate_url(url, hosts)
        if respect_robots:
            parts = urlsplit(url)
            domain = parts.hostname or ''
            if domain not in self.robot_cache:
                rp = RobotFileParser()
                robots_url = f'https://{domain}/robots.txt'
                try:
                    robots = self._download(robots_url, hosts).decode('utf-8', errors='replace')
                    rp.parse(robots.splitlines())
                except HTTPError as exc:
                    if exc.code == 404:
                        rp.parse([])
                    else:
                        raise RuntimeError(f'Robots check HTTP {exc.code} for {domain}') from exc
                except (URLError, TimeoutError) as exc:
                    raise RuntimeError(f'Robots check unavailable for {domain}') from exc
                self.robot_cache[domain] = rp
            if not self.robot_cache[domain].can_fetch(USER_AGENT, url):
                raise PermissionError(f'Robots disallows: {domain}')
        return self._download(url, hosts, self.robot_cache[domain] if respect_robots else None)
