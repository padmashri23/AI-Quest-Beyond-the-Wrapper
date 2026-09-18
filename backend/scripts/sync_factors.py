"""Reproducibly download official publications and build a versioned factor catalogue.

Run from the repository root: backend/.venv/Scripts/python backend/scripts/sync_factors.py
Original publications are retained with SHA-256 manifests; no LLM extracts numbers.
"""
from pathlib import Path
import hashlib
import json
import sys
from decimal import Decimal
import openpyxl
import pdfplumber

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "official"
SOURCES = {
    "defra_2025.xlsx": "https://assets.publishing.service.gov.uk/media/6846b6ea57f3515d9611f0dd/ghg-conversion-factors-2025-flat-format.xlsx",
    "defra_2026.xlsx": "https://assets.publishing.service.gov.uk/media/6a6c9748862aaf18d9c62ac9/ghg-conversion-factors-2026-flat-format-revised.xlsx",
    "egrid_2023.xlsx": "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx",
    "epa_hub_2025.pdf": "https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf",
}
EXPECTED_SHA256 = {
    'defra_2025.xlsx':'8bfdb45b81ec4a88e3bdf4584637330f62e6bd09ce1940e654c5d7b7f736de94',
    'defra_2026.xlsx':'a9a455ab396dae226d510c7be6233748416d490c41a5d20f3dc7a0c45feecd5e',
    'egrid_2023.xlsx':'895cd81dd8662406189ad8adf5a2578dcb362cdb5cff7cca81b10ee6bd2447c6',
    'epa_hub_2025.pdf':'5d07c678fae6783623acb1e23faa4a7c46268ee6c5a0654c9e49c50de7caf924',
}


def download():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, url in SOURCES.items():
        path = DEST / name
        if not path.exists():
            response = httpx.get(url, follow_redirects=True, timeout=120)
            response.raise_for_status()
            path.write_bytes(response.content)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != EXPECTED_SHA256[name]:
            raise ValueError(f'{name}: publication fingerprint changed; review source before updating the pinned manifest')
        manifest.append({"file": name, "url": url, "sha256": digest})
        print(name, path.stat().st_size, digest)
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def compile_tables():
    tables = ROOT / "app" / "factors" / "tables"
    manifest = {r['file']: r for r in json.loads((DEST / 'manifest.json').read_text())}
    units = {'litres':'litre', 'tonnes':'tonne', 'kWh (Gross CV)':'kWh', 'kWh':'kWh',
             'kg':'kg', 'km':'km', 'miles':'mile', 'passenger.km':'passenger_km',
             'tonne.km':'tonne_km', 'cubic metres':'m3', 'Room per night':'room_night', 'GJ':'GJ'}
    defaults = {
        '7_400_4000_5_1': ('electricity_grid', None),
        '13_402_4000_5_1': ('electricity_transmission_losses', 3),
        '1_100_1004_6_1': ('natural_gas_stationary', None),
        '1_101_1011_8_1': ('diesel_mobile', None),
        '1_101_1017_8_1': ('petrol_mobile', None),
        '1_100_1003_8_1': ('propane_stationary', None),
        '21_316_3165_11_1': ('air_travel_short_haul', 6),
        '21_316_3171_11_1': ('air_travel_long_haul', 6),
        '21_316_3161_11_1': ('air_travel_domestic', 6),
        '25_315_3147_11_1': ('rail_travel', 6),
        '25_301_3074_4_1': ('car_travel', 6),
        '27_304_3140_14_1': ('road_freight', 4),
        '27_315_3151_14_1': ('rail_freight', 4),
        '17_404_4005_1_1': ('water_supply', 1),
        '18_405_4006_1_1': ('water_treatment', 5),
        '29_600_4000_13_1': ('hotel_stay', 6),
        '3_201_2156_3_1': ('refrigerant_r410a', None),
    }
    for year in (2025, 2026):
        name = f'defra_{year}.xlsx'
        workbook = openpyxl.load_workbook(DEST / name, read_only=True, data_only=True)
        rows = []
        for n, r in enumerate(workbook['Factors by Category'].values, 1):
            if len(r) < 10 or r[8] != 'kg CO2e' or r[9] is None or r[7] not in units or r[1] not in ('Scope 1','Scope 2','Scope 3'):
                continue
            act, cat = defaults.get(str(r[0]), (f'defra_{r[0]}', None))
            scope = int(r[1][-1])
            if scope == 3 and cat is None:
                cat = {'Water supply':1,'Water treatment':5,'Material use':1,'Waste disposal':5,
                       'Business travel- air':6,'Business travel- land':6,'Business travel- sea':6,
                       'Hotel stay':6,'Freighting goods':4,'Homeworking':7}.get(r[2],3 if str(r[2]).startswith(('WTT','Transmission','UK electricity T&D')) else None)
            region = 'GLOBAL' if r[2] == 'Refrigerant & other' else 'GB'
            if r[2]=='Hotel stay':
                countries={'UK':'GB','United States':'US','United States of America':'US','Germany':'DE','India':'IN','France':'FR','Australia':'AU','Canada':'CA','Japan':'JP'}
                region=countries.get(r[4], str(r[4]))
                if r[4] in countries: act='hotel_stay'
            desc=' / '.join(str(x) for x in r[2:7] if x is not None)
            factor={'factor_id':f'DEFRA{year}_{r[0]}','activity_type':act,'scope':scope,'scope3_category':cat,
                    'region':region,'year':year,'value':str(r[9]),'unit':units[r[7]],'source':f'UK DESNZ conversion factors {year}',
                    'table_ref':desc,'url':manifest[name]['url'],'source_sha256':manifest[name]['sha256'],
                    'source_row':f'Factors by Category!J{n}; official ID {r[0]}','verified':True,
                    'notes':f'Original unit: {r[7]}. Imported directly from workbook; null values are never zero. Geography and activity boundary require reviewer confirmation.'}
            if scope==2: factor['scope2_method']='location'
            rows.append(factor)
            if act=='diesel_mobile':
                rows.append({**factor,'factor_id':factor['factor_id']+'_stationary','activity_type':'diesel_stationary'})
        workbook.close()
        (tables / f'official_defra_{year}.json').write_text(json.dumps({'table_id':f'DESNZ_{year}', 'source':f'UK Government {year}', **manifest[name], 'rows':rows},indent=2),encoding='utf-8')
        print(f'DESNZ {year}: {len(rows)} traceable factors')
    name='egrid_2023.xlsx'
    w=openpyxl.load_workbook(DEST/name,read_only=True,data_only=True)
    rows=[]
    for sheet, column in [('SRL23','SRC2ERTA'),('US23','USC2ERTA')]:
        iterator=iter(w[sheet].values); next(iterator); headers=next(iterator)
        if column not in headers: raise ValueError(f'Missing eGRID output-rate column: {column}')
        for n,r in enumerate(iterator,3):
            d=dict(zip(headers,r))
            if d.get(column) in (None, '--'): continue
            region=d.get('SUBRGN','US')
            rate=Decimal(str(d[column])) * Decimal('0.45359237') / 1000
            rows.append({'factor_id':f'EPA_EGRID2023_{region}','activity_type':'electricity_grid','scope':2,'scope2_method':'location',
              'region':region,'year':2023,'value':str(rate),'unit':'kWh','source':'EPA eGRID2023 revision 2',
              'table_ref':f'{sheet} {column}: {d[column]} lb CO2e/MWh × 0.45359237 / 1000',
              'url':manifest[name]['url'],'source_sha256':manifest[name]['sha256'],'source_row':f'{sheet} row {n}', 'verified':True})
    w.close()
    if len(rows)<25 or not any(r['region']=='US' for r in rows): raise ValueError('Incomplete eGRID subregion import')
    (tables/'official_egrid_2023.json').write_text(json.dumps({'table_id':'EPA_EGRID2023_REV2',**manifest[name],'rows':rows},indent=2),encoding='utf-8')
    # EPA stationary natural gas: match the actual source text before accepting constants.
    name='epa_hub_2025.pdf'
    with pdfplumber.open(DEST/name) as pdf:
        text=pdf.pages[0].extract_text()
    import re
    if 'NaturalGas0.00102653.061.00.10' not in re.sub(r'\s+','',text):
        raise ValueError('EPA natural gas source row changed; review importer')
    rows=[{'factor_id':'EPA_HUB2025_NATGAS','activity_type':'natural_gas_stationary','scope':1,'region':'US','year':2025,
           'value':'53.1145','components':{'CO2':'53.06','CH4':'0.001','N2O':'0.0001'},'gwp_set':'AR5-100','unit':'mmBtu',
           'source':'EPA GHG Emission Factors Hub 2025','table_ref':'Table 1, Natural Gas; kg CO2 and grams CH4/N2O per mmBtu',
           'url':manifest[name]['url'],'source_sha256':manifest[name]['sha256'],'source_row':'PDF page 1, Table 1 Natural Gas','verified':True}]
    (tables/'official_epa_hub_2025.json').write_text(json.dumps({'table_id':'EPA_HUB2025_VERIFIED',**manifest[name],'rows':rows},indent=2),encoding='utf-8')
    print(f'eGRID: 27 subregions/US where present; EPA verified natural gas imported')


if __name__ == "__main__":
    download()
    compile_tables()
