import hashlib
import numpy as np
import pandas as pd
import pytest

from btc_quant.common import DataError, HOUR, write_json
from btc_quant.data import (
    normalize_coinbase_candles, validate_bars, load_history,
    PublicClient, fetch_book,
)
from conftest import bars


@pytest.mark.parametrize('bad', ['nan','negative_price','negative_volume','bad_high','bad_low','hour','gap','naive'])
def test_invalid_candles_fail(bad):
    b=bars(20)
    if bad=='nan': b.iloc[2,0]=np.nan
    if bad=='negative_price': b.iloc[2,0]=-1
    if bad=='negative_volume': b.iloc[2,b.columns.get_loc('volume')]=-1
    if bad=='bad_high': b.iloc[2,b.columns.get_loc('high')]=1
    if bad=='bad_low': b.iloc[2,b.columns.get_loc('low')]=100000
    if bad=='hour': b.index=b.index+pd.Timedelta(minutes=1)
    if bad=='gap': b=b.drop(b.index[2])
    if bad=='naive': b.index=b.index.tz_localize(None)
    with pytest.raises(DataError): validate_bars(b,contiguous=True)


def test_duplicate_exact_deduplicated():
    b=bars(5)
    assert len(validate_bars(pd.concat([b,b.iloc[:1]])))==5


def test_duplicate_conflict_rejected():
    b=bars(5); dup=b.iloc[:1].copy(); dup['volume']+=1
    with pytest.raises(DataError,match='Conflicting'): validate_bars(pd.concat([b,dup]))


def test_coinbase_candle_schema_normalizes():
    payload=[[1735689600,99,101,100,100.5,200]]
    p=normalize_coinbase_candles(payload)
    assert p.index[0]==pd.Timestamp('2025-01-01',tz='UTC')
    assert p.open.iloc[0]==100
    assert p.close.iloc[0]==100.5
    assert p.volume.iloc[0]==200


@pytest.mark.parametrize('payload',[[], [[1,2,3]], {'candles':[]}])
def test_bad_coinbase_candles_rejected(payload):
    with pytest.raises(DataError): normalize_coinbase_candles(payload)


@pytest.mark.parametrize('status',[403,451,404,400])
def test_provider_denial_no_substitution(status,monkeypatch):
    c=PublicClient(retries=1,pause_seconds=0)
    class R:
        status_code=status; ok=False; headers={}
    monkeypatch.setattr(c.session,'get',lambda *a,**k:R())
    with pytest.raises(DataError): c.get('https://example.test')


def test_book_parser(monkeypatch):
    c=PublicClient(retries=1,pause_seconds=0)
    monkeypatch.setattr(c,'json',lambda *a,**k:{'bids':[['99','1',1]],'asks':[['101','1',1]]})
    b=fetch_book(c,'BTC-USD')
    assert b['bid']==99 and b['ask']==101 and b['spread_bps']==pytest.approx(200)


def test_synthetic_cannot_load_as_real(tmp_path,cfg):
    write_json(tmp_path/'manifest.json',{'source':'synthetic','status':'VERIFIED'})
    with pytest.raises(DataError,match='REAL_COINBASE'): load_history(cfg,tmp_path)


def test_processed_checksum_required(tmp_path,cfg):
    write_json(tmp_path/'manifest.json',{
        'source':'real_coinbase_spot_api','status':'VERIFIED_NORMALIZED_DATA',
        'start':cfg['data']['start'],'end_exclusive':cfg['data']['end_exclusive'],'symbols':{}
    })
    with pytest.raises(DataError,match='checksum'): load_history(cfg,tmp_path)

from btc_quant.data import gap_summary, enforce_gap_policy, to_hourly_grid

def test_small_gap_is_measured_not_filled(cfg):
    b=bars(100)
    missing_time=b.index[10]
    sparse=b.drop(missing_time)
    g=gap_summary(sparse,b.index[0],b.index[-1]+HOUR)
    assert g['missing_bars']==1
    grid=to_hourly_grid(sparse,b.index[0],b.index[-1]+HOUR)
    assert pd.isna(grid.loc[missing_time,'close'])
    assert len(grid)==100

def test_gap_policy_rejects_excess_fraction(cfg):
    cfg['data']['max_missing_fraction']=0.005
    summary={'missing_fraction':0.01,'missing_bars':10,'expected_bars':1000,'max_consecutive_missing_hours':1}
    with pytest.raises(DataError,match='exceeds'):
        enforce_gap_policy(summary,cfg,'BTC-USD')

def test_gap_policy_rejects_long_run(cfg):
    cfg['data']['max_missing_fraction']=1.0
    cfg['data']['max_consecutive_missing_hours']=3
    summary={'missing_fraction':0.01,'missing_bars':4,'expected_bars':400,'max_consecutive_missing_hours':4}
    with pytest.raises(DataError,match='longest missing run'):
        enforce_gap_policy(summary,cfg,'BTC-USD')
