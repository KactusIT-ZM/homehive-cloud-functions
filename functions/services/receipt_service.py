from fpdf import FPDF
import datetime

def generate_receipt_pdf(data):
    """
    Generates a receipt PDF from the given data.
    """
    pdf = FPDF()
    pdf.add_page()
    
    # Set font
    pdf.set_font("helvetica", size=12)
    
    # Title
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, "Receipt", ln=True, align="C")
    pdf.ln(10)
    
    # Tenant and Property Info
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, f"Tenant: {data['tenant_name']}", ln=True)
    pdf.cell(0, 10, f"Property: {data['property_name']}", ln=True)
    pdf.ln(5)
    
    # Dates
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, f"Date Paid: {data['date_paid']}", ln=True)
    pdf.cell(0, 10, f"Next Payment Date: {data['next_payment_date']}", ln=True)
    pdf.ln(10)
    
    # Items Table
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(100, 10, "Description", border=1)
    pdf.cell(40, 10, "Amount", border=1, ln=True, align="R")
    
    pdf.set_font("helvetica", size=12)
    total = 0
    for item in data['additional_info']:
        pdf.cell(100, 10, item['title'], border=1)
        pdf.cell(40, 10, f"{item['amount']:.2f}", border=1, ln=True, align="R")
        total += item['amount']
    
    # Total
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(100, 10, "Total Paid", border=1)
    pdf.cell(40, 10, f"{data['amount_paid']:.2f}", border=1, ln=True, align="R")
    pdf.ln(10)
    
    # Thank you message
    pdf.set_font("helvetica", "I", 12)
    pdf.cell(0, 10, "Thank you for your payment!", ln=True, align="C")
    
    return pdf.output(dest='S').encode('latin-1')

