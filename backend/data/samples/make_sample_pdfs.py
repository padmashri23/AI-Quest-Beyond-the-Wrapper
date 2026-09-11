"""Generate the two sample utility-bill PDFs. Dev-only; needs `pip install reportlab`.
Run once: python backend/data/samples/make_sample_pdfs.py"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent


def bill(path: Path, lines: list[str]):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for i, line in enumerate(lines):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 14 if i == 0 else 10.5)
        c.drawString(56, y, line)
        y -= 18 if i else 26
    c.save()


bill(
    HERE / "utility_bill_electricity_fremont_mar2025.pdf",
    [
        "Pacific Gas and Electric Company",
        "Commercial Electric Statement",
        "Account number: 8823100042-7   Service: 4100 Warm Springs Blvd, Fremont CA 94538",
        "Contact: billing@pge-business.example  Tel (415) 555-0142",
        "Billing period: 01 Mar 2025 to 31 Mar 2025",
        "Grid region: WECC California (CAMX)",
        "",
        "Meter 774-Q  Peak consumption 61,240 kWh",
        "Meter 774-Q  Off-peak consumption 129,210 kWh",
        "Total consumption 190,450 kWh",
        "",
        "Energy charge $0.1548 per kWh",
        "Demand charge 412 kW x $18.20",
        "Total amount due $32,376.50",
        "Please pay by 21 Apr 2025.",
    ],
)

bill(
    HERE / "utility_bill_gas_sheffield_q1_2025.pdf",
    [
        "British Gas Business",
        "Gas Statement - Sheffield Works",
        "Customer number: BGB-4471-9920   Supply address: 12 Attercliffe Road, Sheffield S4 7WT, United Kingdom",
        "Email: accounts@northbridge-precision.example",
        "Period: 01 Jan 2025 to 31 Mar 2025",
        "",
        "Meter G09-1182  Opening read 442,118  Closing read 468,203",
        "Volume 26,085 m3 corrected",
        "Energy used 286,400 kWh (gross calorific value 39.4 MJ/m3)",
        "",
        "Unit rate 6.65 p per kWh",
        "Standing charge 91 days x GBP 1.12",
        "Total due GBP 19,048.00 inc. VAT",
    ],
)
print("written")
