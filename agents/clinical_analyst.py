import os
from google.adk.agents import Agent
from fpdf import FPDF
from tools.alert_tools import get_alerts_timeline

def get_patient_alert_history(resident_id: str) -> str:
    """
    Retrieve the historical timeline of alerts and health anomalies for a specific resident.
    Provides RAG-like historical context for generating analytical reports.
    """
    timeline = get_alerts_timeline()
    if not isinstance(timeline, list):
        return "Error fetching timeline."
        
    filtered = [a for a in timeline if a.get("resident_id") == resident_id]
    if not filtered:
        return f"No historical alerts found for resident {resident_id}."
        
    report = f"Historical Alerts for {resident_id}:\n"
    for a in filtered:
        report += f"[{a.get('timestamp')}] {a.get('severity')} - {a.get('message')}\n"
        if a.get('correlation'):
            report += f"  Correlation: {a.get('correlation')}\n"
    return report

def export_pdf_report(resident_id: str, title: str, report_content: str) -> str:
    """
    Generates a professional, branded PDF clinical report from the analyzed text.
    Use this tool once you have compiled a final analytical summary.
    Keep the report_content as plain text or simple structured formatting (no complex markdown tags).
    """
    try:
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(200, 10, txt="SilverGrove Health Dashboard", ln=True, align='C')
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt=f"Clinical Analysis Report: {resident_id}", ln=True, align='C')
        
        pdf.ln(10)
        
        # Title
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt=title, ln=True, align='L')
        
        # Content
        pdf.set_font("Arial", '', 11)
        
        # Write text, handling newlines
        for line in report_content.split('\n'):
            # Strip markdown bolding and asterisks
            clean_line = line.replace('**', '').replace('*', '-')
            
            # Skip pure markdown separators (e.g. "----------")
            if len(clean_line.replace('-', '').replace('=', '').replace('_', '').strip()) == 0 and len(clean_line) > 3:
                continue
                
            # Truncate extremely long words that cause "Not enough horizontal space" errors
            words = clean_line.split(' ')
            safe_words = [w[:70] for w in words]
            clean_line = ' '.join(safe_words)
            
            # Replace smart quotes and force latin-1 to avoid font glyph errors in core Arial
            clean_line = clean_line.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
            clean_line = clean_line.encode('latin-1', 'replace').decode('latin-1')
            
            pdf.multi_cell(0, 8, txt=clean_line)
            
        # Ensure reports directory exists
        reports_dir = os.path.join(os.getcwd(), "static", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        filename = f"{resident_id}_clinical_report.pdf"
        filepath = os.path.join(reports_dir, filename)
        
        pdf.output(filepath)
        
        # Return the URL path for the frontend
        return f"PDF successfully generated. URL: /reports/{filename}"
    except Exception as e:
        return f"Failed to generate PDF: {str(e)}"


CLINICAL_ANALYST_INSTRUCTION = """
You are the Clinical Analyst Agent for SilverGrove.
Your primary role is to synthesize historical health telemetry, alerts, and medical compliance data to generate professional, enterprise-grade clinical reports for physicians.

Your duties:
1. When asked to analyze a resident, use `get_patient_alert_history` to pull their real timeline data.
2. Synthesize a comprehensive but concise summary of their health trajectory (e.g., "Frequent orthostatic hypotension correlated with Metoprolol over the last 7 days").
3. Once your analysis is drafted, use the `export_pdf_report` tool to physically generate the PDF file for the physician.
4. Keep your formatting clean (no markdown asterisks) so it renders well in the basic PDF generator. 
5. In your final response, ALWAYS provide the link to the generated PDF.
"""

clinical_analyst_agent = Agent(
    name="clinical_analyst",
    instruction=CLINICAL_ANALYST_INSTRUCTION,
    tools=[get_patient_alert_history, export_pdf_report],
    model="gemini-3.1-flash-lite"
)
