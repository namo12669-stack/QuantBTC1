import hashlib
import io
import zipfile
import numpy as np
import pandas as pd
import pytest
from btc_quant.common import DataError, HOUR, write_json
from btc_quant.data import (epoch_index, normalize_klines, normalize_funding,
                           validate_bars, validate_funding, _csv_from_zip, KLINE_FIELDS,
                           load_history, archive_blob, PublicClient)
from conftest import bars, funding

@pytest.mark.parametrize('scale', [1,1000,1000000])
def test_timestamp_units(scale):
    assert epoch_index([1735689600*scale])[0] == pd.Timestamp('2025-01-01',tz='UTC')

@pytest.mark.parametrize('bad', ['nan','negative_price','negative_volume','bad_high','bad_low','hour','gap','naive'])
def test_invalid_candles_fail(bad):
    b=bars(20)
    if bad=='nan': b.iloc[2,0]=np.nan
    if bad=='negative_price': b.iloc[2,0]=-1
    if bad=='negative_volume': b.iloc[2,4]=-1
    if bad=='bad_high': b.iloc[2,1]=1
    if bad=='bad_low': b.iloc[2,2]=100000
    if bad=='hour': b.index=b.index+pd.Timedelta(minutes=1)
    if bad=='gap': b=b.drop(b.index[2])
    if bad=='naive': b.index=b.index.tz_localize(None)
    with pytest.raises(DataError): validate_bars(b,contiguous=True)

def test_duplicate_exact_deduplicated():
    b=bars(5); assert len(validate_bars(pd.concat([b,b.iloc[:1]])))==5

def test_duplicate_conflict_rejected():
    b=bars(5); dup=b.iloc[:1].copy(); dup['volume']+=1
    with pytest.raises(DataError,match='Conflicting'): validate_bars(pd.concat([b,dup]))

@pytest.mark.parametrize('header',[True,False])
def test_kline_zip_header_and_no_header(header):
    r=pd.DataFrame([[1735689600000,100,101,99,100.5,200,1735693199999,20100,2,50,5000,0]],columns=KLINE_FIELDS)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z: z.writestr('a.csv',r.to_csv(index=False,header=header))
    p=normalize_klines(_csv_from_zip(out.getvalue(),KLINE_FIELDS))
    assert p.close.iloc[0]==100.5
    assert p.quote_volume.iloc[0]==20100

def test_missing_quote_volume_rejected():
    r=pd.DataFrame({'open_time':[1735689600000],'open':[100],'high':[101],'low':[99],'close':[100],'volume':[1]})
    with pytest.raises(DataError,match='quote_volume'): normalize_klines(r)

def test_invalid_zip_rejected():
    with pytest.raises(DataError): _csv_from_zip(b'not a zip',KLINE_FIELDS)

def test_funding_normalization_and_coverage():
    ix=pd.date_range('2025-01-01',periods=3,freq='8h',tz='UTC')
    raw=pd.DataFrame({'calc_time':ix.asi8//1000000,'funding_interval_hours':8,'last_funding_rate':.0001})
    f=normalize_funding(raw)
    validate_funding(f,ix[0],ix[0]+pd.Timedelta(days=1))
    assert f.rate.iloc[0]==.0001

@pytest.mark.parametrize('variant',['empty','start','end','gap'])
def test_funding_missing_fails(variant):
    b=bars(72); f=funding(b)
    if variant=='empty': f=f.iloc[:0]
    if variant=='start': f=f.iloc[2:]
    if variant=='end': f=f.iloc[:-2]
    if variant=='gap': f=f.drop(f.index[2])
    with pytest.raises(DataError): validate_funding(f,b.index[0],b.index[-1]+HOUR)

def test_archive_bad_checksum_fails(tmp_path):
    class C:
        def get(self,url):
            class R: content=(b'0'*64+b' a.zip') if url.endswith('CHECKSUM') else b'badzip'
            return R()
    with pytest.raises(DataError,match='CHECKSUM'): archive_blob(C(),tmp_path,'https://test.test/a.zip')

def test_archive_uses_verified_cache(tmp_path):
    blob=b'example bytes'; sha=hashlib.sha256(blob).hexdigest()
    class C:
        calls=0
        def get(self,url):
            self.calls+=1
            class R: content=(sha+' a.zip').encode() if url.endswith('CHECKSUM') else blob
            return R()
    c=C()
    assert archive_blob(c,tmp_path,'https://test.test/a.zip')[0]==blob
    archive_blob(c,tmp_path,'https://test.test/a.zip')
    assert c.calls==2

@pytest.mark.parametrize('status',[403,451,404,400])
def test_provider_denial_no_substitution(status,monkeypatch):
    c=PublicClient(retries=1)
    class R: status_code=status; ok=False; headers={}
    monkeypatch.setattr(c.session,'get',lambda *a,**k:R())
    with pytest.raises(DataError): c.get('https://example.test')

def test_synthetic_cannot_load_as_real(tmp_path,cfg):
    write_json(tmp_path/'manifest.json',{'source':'synthetic','status':'VERIFIED'})
    with pytest.raises(DataError,match='REAL_ARCHIVE'): load_history(cfg,tmp_path)

def test_processed_checksum_required(tmp_path,cfg):
    write_json(tmp_path/'manifest.json',{'source':'real_exchange_archive','status':'VERIFIED','start':cfg['data']['start'],
               'end_exclusive':cfg['data']['end_exclusive'],'symbols':{}})
    with pytest.raises(DataError,match='checksum'): load_history(cfg,tmp_path)
