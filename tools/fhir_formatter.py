import datetime
from typing import Dict, List

def format_heart_rate_fhir(resident_id: str, heart_rate: int) -> dict:
    """
    Formats heart rate vital telemetry into a standard HL7 FHIR Observation resource
    using LOINC code 8867-4 and UCUM unit beats/minute.
    """
    return {
        "resourceType": "Observation",
        "id": f"obs-hr-{resident_id}-{int(datetime.datetime.utcnow().timestamp())}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "8867-4",
                    "display": "Heart rate"
                }
            ]
        },
        "subject": {
            "reference": f"Patient/{resident_id}"
        },
        "effectiveDateTime": datetime.datetime.utcnow().isoformat() + "Z",
        "valueQuantity": {
            "value": heart_rate,
            "unit": "beats/minute",
            "system": "http://unitsofmeasure.org",
            "code": "/min"
        }
    }

def format_blood_pressure_fhir(resident_id: str, systolic: int, diastolic: int) -> dict:
    """
    Formats systolic/diastolic blood pressure telemetry into a standard HL7 FHIR Observation
    panel resource using LOINC code 85354-9 (Blood pressure panel) with components.
    """
    now_str = datetime.datetime.utcnow().isoformat() + "Z"
    return {
        "resourceType": "Observation",
        "id": f"obs-bp-{resident_id}-{int(datetime.datetime.utcnow().timestamp())}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood pressure panel with all components"
                }
            ]
        },
        "subject": {
            "reference": f"Patient/{resident_id}"
        },
        "effectiveDateTime": now_str,
        "component": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure"
                        }
                    ]
                },
                "valueQuantity": {
                    "value": systolic,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mm[Hg]"
                }
            },
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8462-4",
                            "display": "Diastolic blood pressure"
                        }
                    ]
                },
                "valueQuantity": {
                    "value": diastolic,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mm[Hg]"
                }
            }
        ]
    }

def format_gait_speed_fhir(resident_id: str, gait_speed: float) -> dict:
    """
    Formats gait velocity/speed telemetry into a standard HL7 FHIR Observation resource
    using custom local systems for gait speed tracking (m/s).
    """
    return {
        "resourceType": "Observation",
        "id": f"obs-gait-{resident_id}-{int(datetime.datetime.utcnow().timestamp())}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "activity",
                        "display": "Physical Activity"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "101676-5",
                    "display": "Average gait speed"
                }
            ]
        },
        "subject": {
            "reference": f"Patient/{resident_id}"
        },
        "effectiveDateTime": datetime.datetime.utcnow().isoformat() + "Z",
        "valueQuantity": {
            "value": gait_speed,
            "unit": "m/s",
            "system": "http://unitsofmeasure.org",
            "code": "m/s"
        }
    }
