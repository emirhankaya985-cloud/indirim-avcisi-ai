import unittest
from decimal import Decimal
from tracker.extract import extract_price, to_decimal, coupon_entries


class PriceParserTests(unittest.TestCase):
    def test_turkish_and_us_prices(self):
        self.assertEqual(to_decimal('1.234,56 TL'), Decimal('1234.56'))
        self.assertEqual(to_decimal('1,234.56 USD'), Decimal('1234.56'))
        self.assertEqual(to_decimal('1.299'), Decimal('1299.00'))
        self.assertEqual(to_decimal('199,90'), Decimal('199.90'))
        self.assertEqual(to_decimal('349'), Decimal('349.00'))
        self.assertEqual(to_decimal(1.299), Decimal('1.30'))

    def test_product_jsonld(self):
        html = '''<html><head><script type="application/ld+json">{
        "@context":"https://schema.org","@type":"Product","name":"Test",
        "offers":{"@type":"Offer","price":"1.249,90","priceCurrency":"TRY"}}
        </script></head></html>'''
        result = extract_price(html)
        self.assertEqual(result.amount, Decimal('1249.90'))
        self.assertIn('JSON-LD', result.evidence)

    def test_graph_product(self):
        html = '''<script type="application/ld+json">{"@graph":[
          {"@type":"Organization","name":"X"},
          {"@type":"Product","offers":[{"@type":"Offer","price":1200,"priceCurrency":"TRY"}]}
        ]}</script>'''
        self.assertEqual(extract_price(html).amount, Decimal('1200.00'))

    def test_meta_price(self):
        html = '<meta property="product:price:amount" content="99.99"><meta property="product:price:currency" content="TRY">'
        self.assertEqual(extract_price(html).amount, Decimal('99.99'))

    def test_no_invented_price(self):
        with self.assertRaisesRegex(ValueError, 'No reliable'):
            extract_price('<div>50% OFF ! Only 49 lira today.</div>')

    def test_currency_mismatch(self):
        html = '<meta property="product:price:amount" content="100"><meta property="product:price:currency" content="USD">'
        with self.assertRaisesRegex(ValueError, 'Currency mismatch'):
            extract_price(html, 'TRY')

    def test_invalid_price(self):
        for value in ('-1', 'N/A', '99-199', '', '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                to_decimal(value)

    def test_coupon_feed_candidates(self):
        xml = b'''<rss><channel>
          <item><title>New coupon for weekend</title><link>https://example.com/1</link></item>
          <item><title>Product review</title><link>https://example.com/2</link></item>
        </channel></rss>'''
        items = coupon_entries(xml)
        self.assertEqual(len(items), 1)
        self.assertIn('coupon', items[0]['title'])


if __name__ == '__main__':
    unittest.main()
