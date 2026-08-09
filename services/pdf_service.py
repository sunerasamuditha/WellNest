import os
from fpdf import FPDF
from tools.alert_tools import get_alerts_timeline

def sanitize_line(text: str) -> str:
    if not text:
        return ""
    # Strip markdown symbols
    clean = text.replace('**', '').replace('*', '-')
    # Replace smart quotes and special characters
    clean = clean.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
    # Truncate extremely long words that cause "Not enough horizontal space" errors (max 60 chars)
    words = clean.split(' ')
    safe_words = [w[:60] for w in words]
    clean = ' '.join(safe_words)
    # Encode to latin-1 to avoid glyph errors
    return clean.encode('latin-1', 'replace').decode('latin-1')

def generate_local_pdf(resident_id: str) -> str:
    """
    Directly builds a PDF from the JSON alert history without using an LLM.
    """
    try:
        timeline = get_alerts_timeline()
        if not isinstance(timeline, list):
            return "Error fetching timeline."
            
        filtered = [a for a in timeline if a.get("resident_id") == resident_id]
        if not filtered:
            return f"No historical alerts found for resident {resident_id}."
            
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(200, 10, txt="SilverGrove Health Dashboard", ln=True, align='C')
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt=f"Clinical Activity Report: {resident_id}", ln=True, align='C')
        pdf.ln(10)
        
        pdf.set_font("Arial", '', 11)
        
        # Write alert history
        for a in filtered:
            time_str = a.get('timestamp', '')
            severity = a.get('severity', 'INFO').upper()
            msg = a.get('message', '')
            
            # Format row
            line = f"[{time_str}] {severity} - {msg}"
            pdf.multi_cell(0, 8, txt=sanitize_line(line))
            pdf.ln(2)
            
            # Add correlation if exists
            correlation = a.get('correlation')
            if correlation:
                corr_line = f"  -> Correlation: {correlation}"
                pdf.multi_cell(0, 8, txt=sanitize_line(corr_line))
                pdf.ln(2)
            
        # Ensure reports directory exists
        reports_dir = os.path.join(os.getcwd(), "static", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        filename = f"{resident_id}_local_report.pdf"
        filepath = os.path.join(reports_dir, filename)
        
        pdf.output(filepath)
        
        return f"PDF successfully generated. URL: /reports/{filename}"
    except Exception as e:
        return f"Failed to generate PDF: {str(e)}"
