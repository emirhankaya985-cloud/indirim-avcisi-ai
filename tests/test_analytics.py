from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from tracker.analytics import price_metrics, gtin_key, exact_match, comparable_offers
from tracker.daily_report import render
from tracker.engine import update_feed
from tracker import storage
from test_storage import _Connection

NOW=datetime(2026,11,26,6,tzinfo=timezone.utc)


class AnalyticsTests(TestCase):
    def test_baseline_not_a_discount(self):
        m=price_metrics([],Decimal('100'),None,NOW)
        self.assertIsNone(m['drop_percent'])
        self.assertIsNone(m['score'])
        self.assertIsNone(m['stock'])
        self.assertIsNone(m['total_with_shipping'])

    def test_windows_and_savings(self):
        samples=[{'time':(NOW-timedelta(days=d)).isoformat(),'price':str(p)}
                 for d,p in [(3,120),(20,90),(60,70)]]
        m=price_metrics(samples,Decimal('80'),Decimal('120'),NOW,'50')
        self.assertEqual(m['low_7d'],'80')
        self.assertEqual(m['prior_low_30d'],'90')
        self.assertEqual(m['low_90d'],'70')
        self.assertEqual(m['historical_low'],'50')
        self.assertEqual(m['saving'],'40.00')

    def test_rebound_suspicion_not_fraud_claim(self):
        m=price_metrics([{'time':(NOW-timedelta(days=1)).isoformat(),'price':'80'}],
                        Decimal('90'),Decimal('120'),NOW)
        self.assertEqual(m['fake_discount_suspicion'],'prior_low_not_beaten')

    def test_gtin_and_variants(self):
        a={'gtin':'4006381333931','model':'M','capacity':'128GB'}
        self.assertIsNotNone(gtin_key(a['gtin']))
        self.assertIsNone(gtin_key('4006381333932'))
        self.assertTrue(exact_match(a,dict(a)))
        self.assertFalse(exact_match(a,dict(a,capacity='256GB')))
        self.assertFalse(exact_match(a,{'gtin':a['gtin']}))
        self.assertFalse(exact_match({'model':'M'},{'model':'M'}))

    def test_stale_and_failed_offers_not_compared(self):
        p={'gtin':'4006381333931','model':'M'}
        cat={'a':dict(p,id='a'),'b':dict(p,id='b')}
        a={'last_checked':NOW.isoformat(),'last_price':'100','evidence':'fixture','currency':'TRY'}
        b=dict(a,last_price='90')
        self.assertEqual(len(comparable_offers(cat,{'a':a,'b':b},NOW)),1)
        self.assertFalse(comparable_offers(cat,{'a':a,'b':dict(b,last_error='blocked')},NOW))
        self.assertFalse(comparable_offers(cat,{'a':a,'b':dict(b,last_checked=(NOW-timedelta(days=2)).isoformat())},NOW))

    def test_weekly_report_and_missing_values(self):
        body=render({}, {}, False,NOW,False,days=7)
        self.assertIn('Haftalık',body)
        self.assertIn('bilinmiyor',body)
        self.assertNotIn('API kabul edilen alarm: 0',body)

    def test_candidate_metadata_retains_unknown_terms(self):
        state={}
        feed={'id':'feed','url':'https://example.org/rss','name':'Fixture'}
        update_feed(state,feed,[{'id':'one','title':'Kupon','link':'https://example.org/one'}],NOW)
        row=next(iter(state['feeds']['feed']['candidates'].values()))
        self.assertEqual(row['status'],'unverified')
        self.assertIsNone(row['expires_at'])
        self.assertIsNone(row['terms'])

    def test_saved_history_not_reinserted(self):
        state={'products':{'one':{'samples':[{'time':NOW.isoformat(),'price':'100'}]}}}
        with patch.dict('os.environ',{'NEON_DATABASE_URL':'fixture'}):
            conn=_Connection(None)
            with patch.object(storage,'_connection',return_value=conn):
                storage.persist(Path('unused'),state,1)
                self.assertEqual(len(conn.cursor_obj.sql),2)
            conn2=_Connection(None)
            with patch.object(storage,'_connection',return_value=conn2):
                storage.persist(Path('unused'),state,2)
                self.assertEqual(len(conn2.cursor_obj.sql),1)
