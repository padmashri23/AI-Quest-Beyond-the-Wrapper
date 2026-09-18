import io
from decimal import Decimal
from unittest.mock import patch
import openpyxl
from PIL import Image, ImageDraw
from app.ingestion.tabular import parse_tabular, _dec
from app.ingestion.pdf_bills import parse_pdf
from app.ledger import db
from app.pipeline import Pipeline

def test_strict_numeric_ingestion():
    assert _dec('1e3')==Decimal('1000')
    assert _dec('(100)')==Decimal('-100')
    assert _dec('about 12 units') is None
    assert _dec('Infinity') is None

def test_excel_all_sheets_have_distinct_lineage():
    book=openpyxl.Workbook();book.active.title='US';book.create_sheet('GB')
    for sheet in book:
        sheet.append(['description','quantity','unit','region','period'])
        sheet.append(['Electricity supply','1000','kWh',sheet.title,'FY2025'])
    out=io.BytesIO();book.save(out)
    rows=parse_tabular('erp.xlsx',out.getvalue())
    assert len(rows)==2 and len({r.line_id for r in rows})==2
    assert {r.source_ref for r in rows}=={'sheet US, row 2','sheet GB, row 2'}

def scanned_pdf():
    image=Image.new('RGB',(500,250),'white');ImageDraw.Draw(image).text((20,30),'Electricity supply 1000 kWh',fill='black')
    out=io.BytesIO();image.save(out,format='PDF');return out.getvalue()

def test_scanned_pdf_ocr_success_is_review_marked():
    with patch('pytesseract.image_to_string',return_value='Electricity bill UK\n2025-02-01\nElectricity supply 1000 kWh'):
        rows=parse_pdf('scan.pdf',scanned_pdf())
    assert len(rows)==1 and rows[0].quantity==1000
    assert 'OCR' in rows[0].source_ref and rows[0].period=='FY2025'

def test_scanned_pdf_without_ocr_never_disappears():
    with patch('pytesseract.image_to_string',side_effect=RuntimeError('unavailable')):
        rows=parse_pdf('scan.pdf',scanned_pdf())
    assert len(rows)==1 and rows[0].quantity is None and 'OCR' in rows[0].description

def test_legacy_migration_preserves_but_does_not_invent_originals():
    s,entries,_=Pipeline().run([('gas.csv',b'description,quantity,unit,region,period\nNatural gas,100,therm,US,FY2025\n')],'Historic company')
    # Synthetic pre-upgrade schema under a distinct inventory id.
    s.run_id='legacy-test'
    with db._conn() as conn:
        conn.executescript('CREATE TABLE runs(run_id TEXT,summary TEXT); CREATE TABLE entries(run_id TEXT,entry TEXT); CREATE TABLE agent_log(run_id TEXT,entry TEXT); CREATE TABLE narratives(run_id TEXT,text TEXT);')
        conn.execute('INSERT INTO runs VALUES (?,?)',(s.run_id,s.model_dump_json()))
        for entry in entries:conn.execute('INSERT INTO entries VALUES (?,?)',(s.run_id,entry.model_dump_json()))
        conn.commit()
    assert db.migrate_legacy()==1 and db.migrate_legacy()==0
    assert db.get_run(s.run_id).org_name=='Historic company'
    assert db.documents(s.run_id)==[] and db.verify()['valid']

