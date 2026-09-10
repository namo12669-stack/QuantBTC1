import hashlib
import io
import zipfile
import numpy as np
import pandas as pd
import pytest
from btc_quant.common import DataError,HOUR,write_json
from btc_quant.data import (PublicClient,epoch_index,_csv_from_zip,KLINE_FIELDS,normalize_klines,validate_bars,
    normalize_funding,validate_funding,archive_blob,archive_url,gap_summary,to_hourly_grid,enforce_gap_policy,
    parse_rules,fetch_live_candles,load_history,check_data)
from conftest import bars,funding

@pytest.mark.parametrize('bad',['nan','negative_price','negative_volume','bad_high','bad_low','hour','gap','naive'])
def test_invalid_candles_fail(bad):
    b=bars(20)
    if bad=='nan':b.iloc[2,0]=np.nan
    if bad=='negative_price':b.iloc[2,0]=-1
    if bad=='negative_volume':b.iloc[2,b.columns.get_loc('volume')]=-1
    if bad=='bad_high':b.iloc[2,b.columns.get_loc('high')]=1
    if bad=='bad_low':b.iloc[2,b.columns.get_loc('low')]=100000
    if bad=='hour':b.index=b.index+pd.Timedelta(minutes=1)
    if bad=='gap':b=b.drop(b.index[2])
    if bad=='naive':b.index=b.index.tz_localize(None)
    with pytest.raises(DataError):validate_bars(b,contiguous=True)

@pytest.mark.parametrize('unit,mult',[('s',1),('ms',1000),('us',1000000)])
def test_timestamp_units(unit,mult):
    ix=epoch_index([1735689600*mult])
    assert ix[0]==pd.Timestamp('2025-01-01',tz='UTC')


def test_duplicate_conflict():
    b=bars(5);assert len(validate_bars(pd.concat([b,b.iloc[:1]])))==5
    x=b.iloc[:1].copy();x['volume']+=1
    with pytest.raises(DataError,match='Conflicting'):validate_bars(pd.concat([b,x]))


def raw_payload(start,n):
    return [[int((start+i*HOUR).timestamp()*1000),100,101,99,100,200,0,20000,5,100,10000,0] for i in range(n)]

@pytest.mark.parametrize('header',[False,True])
def test_archive_csv_header(header):
    raw=pd.DataFrame(raw_payload(pd.Timestamp('2025-01-01',tz='UTC'),4),columns=KLINE_FIELDS)
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w') as z:z.writestr('price.csv',raw.to_csv(index=False,header=header))
    parsed=normalize_klines(_csv_from_zip(memory.getvalue(),KLINE_FIELDS))
    assert len(parsed)==4 and parsed.close.iloc[0]==100


def test_bad_zip():
    with pytest.raises(DataError,match='ZIP'):_csv_from_zip(b'bad',KLINE_FIELDS)

@pytest.mark.parametrize('status',[403,451,404,400])
def test_provider_no_substitution(status,monkeypatch):
    c=PublicClient(retries=1)
    class R:status_code=status;ok=False;headers={}
    monkeypatch.setattr(c.session,'get',lambda *a,**k:R())
    with pytest.raises(DataError):c.get('https://example.test')


def test_checksum_integrity(tmp_path,monkeypatch):
    blob=b'archive';digest=hashlib.sha256(blob).hexdigest()
    class Response:
        def __init__(self,c):self.content=c
    c=PublicClient(retries=1)
    monkeypatch.setattr(c,'get',lambda url:Response((digest+' file.zip').encode() if url.endswith('CHECKSUM') else blob))
    result,item=archive_blob(c,tmp_path,'https://data.binance.vision/file.zip')
    assert result==blob and item['sha256']==digest
    next(tmp_path.rglob('file.zip')).write_bytes(b'tamper')
    with pytest.raises(DataError,match='CHECKSUM_MISMATCH'):archive_blob(c,tmp_path,'https://data.binance.vision/file.zip')

@pytest.mark.parametrize('kind',['klines','markPriceKlines','fundingRate'])
def test_official_archive_url(kind):
    url=archive_url('BTCUSDT',kind,'2025-01')
    assert url.startswith('https://data.binance.vision/data/futures/um/monthly/')
    assert kind in url and url.endswith('.zip')

@pytest.mark.parametrize('symbol',['../test','BTC/USDT','abc','BTCUSDT?x=1'])
def test_path_injection_blocked(symbol):
    with pytest.raises(DataError):archive_url(symbol,'klines','2025-01')


def test_funding_gap_rejected():
    b=bars(80);f=funding(b)
    validate_funding(f,b.index[0],b.index[-1]+HOUR)
    with pytest.raises(DataError,match='FUNDING_GAP'):validate_funding(f.drop(f.index[3]),b.index[0],b.index[-1]+HOUR)


def test_funding_normalization_conflict():
    raw=pd.DataFrame({'calc_time':[1735689600000,1735689600000],'last_funding_rate':[.001,.002]})
    with pytest.raises(DataError,match='Conflicting'):normalize_funding(raw)


def test_missing_stays_missing(cfg):
    b=bars(1000);t=b.index[20];sparse=b.drop(t)
    q=gap_summary(sparse,b.index[0],b.index[-1]+HOUR);enforce_gap_policy(q,cfg,'BTCUSDT')
    grid=to_hourly_grid(sparse,b.index[0],b.index[-1]+HOUR)
    assert q['missing_bars']==1 and pd.isna(grid.loc[t,'close'])

@pytest.mark.parametrize('fraction,run',[(.006,1),(.001,25)])
def test_excess_gaps_fail(cfg,fraction,run):
    with pytest.raises(DataError):enforce_gap_policy({'missing_fraction':fraction,'missing_bars':6,'expected_bars':1000,'max_consecutive_missing_hours':run},cfg,'BTCUSDT')


def test_pagination_excludes_unclosed(monkeypatch):
    c=PublicClient(retries=1);start=pd.Timestamp('2025-01-01',tz='UTC');calls=[]
    def fake(url,params):
        calls.append(params);t=pd.to_datetime(params['startTime'],unit='ms',utc=True)
        return raw_payload(t,3)
    monkeypatch.setattr(c,'json',fake)
    result=fetch_live_candles(c,'BTCUSDT',start,start+5*HOUR)
    assert len(result)==5 and len(calls)==2 and result.index[-1]==start+4*HOUR


def sample_rules():
    return {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','filters':[
        {'filterType':'PRICE_FILTER','tickSize':'0.1'},{'filterType':'LOT_SIZE','stepSize':'0.001','minQty':'0.001'},
        {'filterType':'MIN_NOTIONAL','notional':'100'}]}]}


def test_live_filters():
    rules=parse_rules(sample_rules());assert rules['step_size']=='0.001'

@pytest.mark.parametrize('key,value',[('status','BREAK'),('contractType','CURRENT_QUARTER'),('quoteAsset','USDC')])
def test_wrong_contract_rejected(key,value):
    p=sample_rules();p['symbols'][0][key]=value
    with pytest.raises(DataError):parse_rules(p)


def test_old_spot_manifest_rejected(tmp_path,cfg):
    write_json(tmp_path/'manifest.json',{'schema':3,'venue':'coinbase_exchange_spot'})
    with pytest.raises(DataError,match='NO_VERIFIED_BINANCE'):load_history(cfg,tmp_path)


def test_independent_history_live_check(cfg,tmp_path,monkeypatch):
    import btc_quant.data as data
    monkeypatch.setattr(data,'archive_blob',lambda *a:(b'fake',{}))
    monkeypatch.setattr(data,'_csv_from_zip',lambda blob,cols:pd.DataFrame())
    monkeypatch.setattr(data,'normalize_klines',lambda raw:None)
    monkeypatch.setattr(data,'normalize_funding',lambda raw:None)
    def denied(*a,**k):raise DataError('HTTP 451')
    monkeypatch.setattr(data,'live_snapshot',denied)
    r=check_data(cfg,tmp_path)
    assert r['status']=='HISTORY_ONLY' and r['can_research'] and not r['can_scan_live']
