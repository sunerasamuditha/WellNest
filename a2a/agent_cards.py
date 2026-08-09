# Standard A2A Agent Card Metadata configurations

def get_root_agent_card(base_url: str = "") -> dict:
    """
    Root agent representing the primary SilverGrove system gateway (Care Coordinator).
    """
    return {
        "name": "SilverGrove Care Gateway",
        "description": "Primary clinical communication and coordinator agent gateway for elderly AAL environments",
        "version": "1.0.0",
        "url": f"{base_url}/a2a/care-coordinator",
        "capabilities": {
            "streaming": True,
            "pushNotifications": True
        },
        "skills": [
            {
                "id": "care-coordination",
                "name": "Clinical Alert Coordination",
                "description": "Coordinates inter-agent state escalations and routes clinical observations to family and physician endpoints"
            }
        ],
        "authentication": {
            "schemes": ["none"]
        }
    }

def get_all_agent_cards(base_url: str = "") -> dict:
    """
    Returns A2A Agent Cards for all 4 specialized agents.
    """
    return {
        "sensory_guardian": {
            "name": "SilverGrove Sensory Guardian",
            "description": "Privacy-first ambient radar and vital signs telemetry monitoring agent",
            "version": "1.0.0",
            "url": f"{base_url}/a2a/sensory-guardian",
            "capabilities": {
                "streaming": True,
                "pushNotifications": False
            },
            "skills": [
                {
                    "id": "vital-analysis",
                    "name": "Ambient Vital Sign Analysis",
                    "description": "Analyzes gait velocity drifts and radar-reported blood pressure/heart rates for anomalies"
                }
            ],
            "authentication": {
                "schemes": ["none"]
            }
        },
        "medical_compliance": {
            "name": "SilverGrove Medical Compliance",
            "description": "Clinical reasoning correlation engine cross-referencing anomalies with medication side-effects and drug interactions",
            "version": "1.0.0",
            "url": f"{base_url}/a2a/medical-compliance",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False
            },
            "skills": [
                {
                    "id": "clinical-correlation",
                    "name": "Geriatric Drug-Adversity Correlation",
                    "description": "Cross-references resident symptoms against US openFDA database records and dangerous drug-drug interaction local tables"
                }
            ],
            "authentication": {
                "schemes": ["none"]
            }
        },
        "cognitive_companion": {
            "name": "SilverGrove Cognitive Companion",
            "description": "Empathetic conversational companion interface for active checking and senior resident advisory",
            "version": "1.0.0",
            "url": f"{base_url}/a2a/cognitive-companion",
            "capabilities": {
                "streaming": True,
                "pushNotifications": True
            },
            "skills": [
                {
                    "id": "empathetic-checkin",
                    "name": "Resident Empathetic Safety Coaching",
                    "description": "Formulates warm, low-stress, senior-adapted safety and clinical check-in alerts"
                }
            ],
            "authentication": {
                "schemes": ["none"]
            }
        },
        "care_coordinator": get_root_agent_card(base_url),
        "family_gateway": {
            "name": "SilverGrove Family Agent Gateway",
            "description": "Self-hosted A2A endpoint for dispatching human-readable clinical alerts to the resident's verified family proxy application",
            "version": "1.0.0",
            "url": f"{base_url}/a2a/family-gateway/inbox",
            "capabilities": {
                "streaming": False,
                "pushNotifications": True
            },
            "skills": [
                {
                    "id": "receive-alert",
                    "name": "Receive Clinical Alert",
                    "description": "Ingests SHA-256 integrity-verified, human-readable clinical alerts regarding the resident"
                }
            ],
            "authentication": {
                "schemes": ["sha256_integrity"]
            }
        },
        "physician_gateway": {
            "name": "SilverGrove Physician EHR Gateway",
            "description": "Self-hosted A2A endpoint for dispatching HL7 FHIR R4 Observations to the primary care physician's EHR review queue",
            "version": "1.0.0",
            "url": f"{base_url}/a2a/physician-gateway/fhir-ingest",
            "capabilities": {
                "streaming": False,
                "pushNotifications": True
            },
            "skills": [
                {
                    "id": "ingest-fhir",
                    "name": "Ingest FHIR Observation",
                    "description": "Ingests SHA-256 integrity-verified HL7 FHIR R4 Observations (LOINC/UCUM) and queues them for physician review"
                }
            ],
            "authentication": {
                "schemes": ["sha256_integrity"]
            }
        }
    }
