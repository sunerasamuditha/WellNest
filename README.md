<p align="center">
  <img src="static/logo.png" alt="WellNest Logo" width="280"/>
</p>

<h1 align="center">WellNest</h1>
<p align="center"><strong>Privacy-First Multi-Agent Assisted Living Dashboard</strong></p>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#asynchronous-architecture">Architecture</a> •
  <a href="#sustainable-development-goals-sdgs">SDGs</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#getting-started">Getting Started</a>
</p>

---

**WellNest** is a privacy-first, enterprise-grade Ambient Assisted Living (AAL) multi-agent platform designed to bridge independent senior living, proactive health monitoring, and secure clinical collaboration. 

Powered by the **Google Agent Development Kit (ADK)** and the **Agent-to-Agent (A2A) protocol**, WellNest replaces invasive video surveillance with camera-free micro-radar ambient monitoring and orchestrates an advanced consensus pipeline to safely manage elderly patient wellness and polypharmacy risks.

---

## Key Features

*   **Privacy-by-Design Ambient Telemetry**: Camera-free ambient radar and RF sensors track gait speed, sleep quality, and daily vitals without invasive cameras, preserving senior dignity.
*   **Async Multi-Agent Consensus Pipeline**: Orchestrates specialized agents communicating asynchronously via a high-performance in-memory Event Bus for concurrent, multi-layered clinical evaluation.
*   **Automated Polypharmacy Correlation**: Integrates with live **openFDA** drug databases to instantly cross-reference gait and biometric anomalies against active prescriptions (e.g., beta-blockers like Metoprolol Succinate).
*   **Secure A2A Protocol Routing**: Packages consensus clinical summaries into cryptographically structured A2A Agent Cards, securely dispatching telemetry directly to Family and Physician gateways.
*   **HL7 FHIR Interoperability**: Generates standards-compliant FHIR R4 Observations tagged with strict LOINC codes and UCUM units to enable direct integration into enterprise Electronic Health Records (EHRs).
*   **Seamless Dynamic Clinical Reports**: Compiles instant, localized PDF clinical charts using hardened string-cleansing algorithms to protect against layout/encoding crashes.

---

## Sustainable Development Goals (SDGs)

WellNest strongly aligns with the United Nations Sustainable Development Goals, specifically focusing on global health, innovation, and equality:

1. **SDG 3: Good Health and Well-being**
   * Promotes proactive, preventative healthcare for the aging population.
   * Reduces hospital readmissions through early detection of polypharmacy interactions and gait abnormalities.
2. **SDG 9: Industry, Innovation, and Infrastructure**
   * Introduces novel multi-agent consensus mechanisms (A2A) and leverages micro-radar over traditional cameras to build resilient, privacy-preserving infrastructure for aged care.
3. **SDG 10: Reduced Inequalities**
   * Bridges the care gap by providing enterprise-grade, continuous clinical monitoring to underserved elderly populations, reducing reliance on expensive, full-time nursing facilities.

---

## Asynchronous Architecture

WellNest deploys an event-driven Multi-Agent System (MAS). Instead of rigid, sequential scripting, agents concurrently publish and subscribe to clinical event streams using an `asyncio`-powered Event Bus.

### Specialized Agents

1.  **Sensory Guardian**: Ingests sensor streams (micro-radar gait velocity, respiratory rates, heart rate) and flags deviations of $\ge 15\%$ against patient baselines.
2.  **Medical Compliance**: Receives anomaly events, polls openFDA APIs, and determines if new medications (e.g., Metoprolol, Lisinopril) are causing orthostatic hypotension.
3.  **Cognitive Companion**: Receives clinical checkouts and structures friendly, daily safety advice tailored for senior residents to keep them safe and active.
4.  **Care Coordinator**: Compiles the entire consensus, formats biometric data as HL7 FHIR observations, creates standardized A2A dispatch cards, and publishes them to connected channels.

---

## Tech Stack

*   **Core Orchestration**: Google Agent Development Kit (ADK), Google GenAI SDK (Gemini 3.1 Pro)
*   **Protocol Standard**: Agent-to-Agent (A2A) specifications for Agent Cards
*   **Asynchronous Engine**: Python `asyncio` Task Groups, FastAPI Event loop
*   **Data & APIs**: openFDA API, HL7 FHIR R4 Standards
*   **Database**: Google Cloud Firestore (Native Mode)
*   **PDF Generation**: Hardened `FPDF2` Clinical Engine
*   **Frontend**: High-fidelity, reactive glassmorphism dashboard (HTML5, Vanilla CSS, JS)
*   **CI/CD & Cloud Deployment**: GitHub Actions, Google Artifact Registry, Google Cloud Run

---

## Getting Started

### 1. Configure Environments
Create a `.env` file in the root directory:
```bash
GEMINI_API_KEY=your_google_ai_studio_api_key_here
GOOGLE_CLOUD_PROJECT=wellnest-a2a
GOOGLE_APPLICATION_CREDENTIALS=wellnest-a2a-key.json
```

### 2. Setup Dependencies
```bash
# Clone the repository
git clone https://github.com/sunerasamuditha/WellNest.git
cd WellNest

# Install core packages
pip install google-adk google-genai fastapi uvicorn python-dotenv fpdf2 requests google-cloud-firestore
```

### 3. Run the System
```bash
python main.py
```
Open your browser and navigate to `http://localhost:8180` to experience the live simulation and Command Center dashboard!
