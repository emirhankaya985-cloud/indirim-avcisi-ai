"""Conservative price and coupon candidate extraction.

Prices are accepted only from machine-readable product data or dedicated price
metadata. We deliberately do not guess from arbitrary prices visible on a page.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re
from xml.etree import ElementTree


@dataclass(frozen=True)
class Price:
    amount: Decimal
    currency: str
    evidence: str


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.scripts: list[str] = []
        self._json_script = False
        self._script_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        info = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'meta':
            for field in ('property', 'name', 'itemprop'):
                if info.get(field):
                    self.meta[info[field].lower()] = info.get('content', '')
        elif tag == 'script' and info.get('type', '').lower().split(';')[0].strip() == 'application/ld+json':
            self._json_script = True
            self._script_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_script:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script' and self._json_script:
            self.scripts.append(''.join(self._script_parts))
            self._json_script = False
            self._script_parts = []


def to_decimal(value: object) -> Decimal:
    """Recognize common Turkish/English prices; reject ranges/ambiguous text."""
    if isinstance(value, bool):
        raise ValueError('Boolean price is invalid')
    if isinstance(value, (int, float, Decimal)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError('Invalid decimal') from exc
        if not amount.is_finite() or amount <= 0 or amount > 100_000_000:
            raise ValueError('Price must be positive and reasonable')
        return amount.quantize(Decimal('0.01'))
    elif isinstance(value, str):
        raw = value.strip()
    else:
        raise ValueError('Missing price')
    raw = re.sub(r'(?i)\b(?:TRY|TL|USD|EUR)\b|[₺$€\s\u00a0]', '', raw)
    if not re.fullmatch(r'\d[\d.,]*', raw):
        raise ValueError(f'Invalid price: {value!r}')
    if ',' in raw and '.' in raw:
        decimal_separator = ',' if raw.rfind(',') > raw.rfind('.') else '.'
        thousand_separator = '.' if decimal_separator == ',' else ','
        raw = raw.replace(thousand_separator, '').replace(decimal_separator, '.')
    elif raw.count(',') == 1:
        a, b = raw.split(',')
        raw = a + ('' if len(b) == 3 else '.') + b
    elif raw.count('.') == 1:
        a, b = raw.split('.')
        raw = a + ('' if len(b) == 3 else '.') + b
    elif raw.count(',') > 1:
        raw = raw.replace(',', '')
    elif raw.count('.') > 1:
        raw = raw.replace('.', '')
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal') from exc
    if not amount.is_finite() or amount <= 0 or amount > 100_000_000:
        raise ValueError('Price must be positive and reasonable')
    return amount.quantize(Decimal('0.01'))


def _types(node: dict) -> set[str]:
    value = node.get('@type', [])
    types = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return {str(t).split('/')[-1].lower() for t in types}


def _walk(node: object):
    if isinstance(node, list):
        for part in node:
            yield from _walk(part)
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _walk(value)


def extract_price(html: str, expected_currency: str = 'TRY') -> Price:
    parser = MetadataParser()
    parser.feed(html)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk(data):
            if 'product' not in _types(node):
                continue
            offers = node.get('offers')
            for offer in _walk(offers):
                if not ({'offer', 'aggregateoffer'} & _types(offer)) and offer is not offers:
                    continue
                raw = offer.get('price', offer.get('lowPrice'))
                if raw is None and isinstance(offer.get('priceSpecification'), dict):
                    raw = offer['priceSpecification'].get('price')
                if raw is None:
                    continue
                currency = str(offer.get('priceCurrency', expected_currency)).upper()
                if currency != expected_currency.upper():
                    raise ValueError(f'Currency mismatch: {currency} != {expected_currency}')
                try:
                    return Price(to_decimal(raw), currency, 'Product JSON-LD')
                except ValueError:
                    continue
    meta = parser.meta
    currency = meta.get('product:price:currency', meta.get('pricecurrency', expected_currency)).upper()
    if currency != expected_currency.upper():
        raise ValueError(f'Currency mismatch: {currency} != {expected_currency}')
    for key in ('product:price:amount', 'og:price:amount', 'price', 'product:price'):
        if key in meta:
            return Price(to_decimal(meta[key]), currency, f'Meta {key}')
    raise ValueError('No reliable product price in JSON-LD or price meta tags')


COUPON_PATTERN = re.compile(r'(?i)(?:\b(?:kupon(?:u)?|coupon|promo\s+code|promosyon\s+kodu|indirim\s+kodu)\b|\bkod\s*:)')


def coupon_entries(xml_bytes: bytes) -> list[dict[str, str]]:
    """Read RSS/Atom entries. Every matched entry is an UNVERIFIED coupon lead."""
    root = ElementTree.fromstring(xml_bytes)
    entries = []
    for el in root.iter():
        if el.tag.rsplit('}', 1)[-1] not in ('item', 'entry'):
            continue
        parts: dict[str, str] = {}
        for child in el:
            name = child.tag.rsplit('}', 1)[-1]
            if name == 'link':
                parts[name] = child.attrib.get('href') or (child.text or '')
            elif name in ('title', 'description', 'summary', 'content', 'guid', 'id'):
                parts[name] = ''.join(child.itertext()).strip()
        title = parts.get('title', '')
        summary = parts.get('description', parts.get('summary', parts.get('content', '')))
        if COUPON_PATTERN.search(title + ' ' + summary):
            entries.append({'id': parts.get('guid') or parts.get('id') or parts.get('link') or title,
                            'title': title[:180], 'link': parts.get('link', '')})
    return entries
