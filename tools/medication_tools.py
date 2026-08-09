import json
import urllib.request
import urllib.parse
from typing import Dict, Any

# Embedded clinical reference database for offline resilience.
# Curated from FDA labeling, Beers Criteria for geriatric pharmacology,
# and standard drug interaction compendia. Used when openFDA API is unreachable.
CLINICAL_REFERENCE_DATABASE = {
    "metoprolol": {
        "generic_name": "Metoprolol Succinate",
        "brand_name": "Toprol-XL",
        "drug_class": "Beta-1 Selective Adrenergic Blocker",
        "side_effects": [
            "Orthostatic hypotension (dizziness when standing up suddenly)",
            "Bradycardia (excessively slow heart rate)",
            "Fatigue and extreme tiredness",
            "Dizziness or lightheadedness",
            "Shortness of breath",
            "Cold extremities (hands and feet)",
            "Depression or mood changes"
        ],
        "warnings": "Caution in elderly patients. Risk of orthostatic hypotension which can trigger severe falls. Do not abruptly stop taking this medication. Taper dose gradually under physician supervision.",
        "beers_criteria": "Listed in AGS Beers Criteria: use with caution in elderly due to bradycardia and fall risk.",
        "interactions": {
            "lisinopril": "Co-administration of beta-blockers (Metoprolol) and ACE inhibitors (Lisinopril) can cause additive blood pressure lowering, increasing the risk of acute dizziness, hypotension, and falling.",
            "donepezil": "Metoprolol combined with Donepezil may increase risk of bradycardia (dangerously slow heart rate).",
            "insulin": "Beta-blockers may mask signs of hypoglycemia (low blood sugar) in diabetic patients."
        }
    },
    "lisinopril": {
        "generic_name": "Lisinopril",
        "brand_name": "Prinivil / Zestril",
        "drug_class": "ACE Inhibitor (Angiotensin-Converting Enzyme Inhibitor)",
        "side_effects": [
            "Persistent dry cough",
            "Dizziness / lightheadedness",
            "Hyperkalemia (high blood potassium levels)",
            "Headache",
            "Angioedema (rare but serious facial/throat swelling)",
            "Renal impairment"
        ],
        "warnings": "Monitor renal function and potassium levels regularly. Stand up slowly to prevent orthostatic dizziness. Contraindicated in pregnancy.",
        "beers_criteria": "Generally appropriate in elderly but monitor renal function and potassium closely.",
        "interactions": {
            "metoprolol": "Increased hypotensive effect. Monitor blood pressure closely. Risk of symptomatic hypotension, especially upon standing.",
            "potassium_supplements": "ACE inhibitors reduce potassium excretion; combining with potassium supplements increases hyperkalemia risk."
        }
    },
    "donepezil": {
        "generic_name": "Donepezil HCl",
        "brand_name": "Aricept",
        "drug_class": "Cholinesterase Inhibitor",
        "side_effects": [
            "Nausea and vomiting",
            "Diarrhea",
            "Insomnia and vivid dreams",
            "Muscle cramps",
            "Decreased appetite and weight loss",
            "Urinary incontinence"
        ],
        "warnings": "Can cause bradycardia and heart block. Monitor heart rate closely, especially with beta-blocker co-administration. May exacerbate or cause GI bleeding.",
        "beers_criteria": "Appropriate for Alzheimer's management. Monitor for GI side effects and cardiac rhythm.",
        "interactions": {
            "metoprolol": "Both agents can slow heart rate; combined use may cause clinically significant bradycardia."
        }
    },
    "carbidopa-levodopa": {
        "generic_name": "Carbidopa-Levodopa",
        "brand_name": "Sinemet",
        "drug_class": "Dopamine Precursor / DOPA Decarboxylase Inhibitor Combination",
        "side_effects": [
            "Orthostatic hypotension (dizziness, low blood pressure)",
            "Dizziness or lightheadedness",
            "Involuntary muscle movements (dyskinesia)",
            "Freezing of gait (motor fluctuations / wearing-off effect)",
            "Drowsiness or sleepiness",
            "Hallucinations (visual and auditory)",
            "Nausea and appetite loss",
            "Dark-colored urine or sweat (harmless)"
        ],
        "warnings": "Caution in elderly. Risk of sudden orthostatic hypotension, hallucination, and motor fluctuations which can cause significant gait freezing and balance loss. Wearing-off effect may cause sudden mobility drops between doses.",
        "beers_criteria": "Appropriate for Parkinson's management. Monitor closely for hallucinations, orthostatic hypotension, and dyskinesia in elderly.",
        "interactions": {
            "metoclopramide": "Dopamine antagonists like Metoclopramide counteract the effects of Levodopa and can worsen Parkinson's symptoms.",
            "iron_supplements": "Iron chelates with Levodopa in the GI tract, reducing absorption by up to 50%."
        }
    },
    "oxycodone": {
        "generic_name": "Oxycodone HCl",
        "brand_name": "Roxicodone / OxyContin",
        "drug_class": "Opioid Analgesic (Schedule II Controlled Substance)",
        "side_effects": [
            "Extreme drowsiness and somnolence",
            "Dizziness or confusion",
            "Muscle weakness or instability",
            "Constipation (very common, often severe)",
            "Slow breathing (respiratory depression)",
            "Nausea and vomiting",
            "Urinary retention",
            "Pruritus (itching)"
        ],
        "warnings": "High risk of drowsiness, cognitive slowing, and postural instability in elderly patients post-surgery. Can significantly increase fall risk and slow down recovery kinetics. Risk of respiratory depression, especially when combined with benzodiazepines. Use the lowest effective dose for the shortest duration.",
        "beers_criteria": "AGS Beers Criteria: AVOID in older adults except for severe pain management. High risk of falls, fractures, and delirium.",
        "interactions": {
            "benzodiazepines": "LIFE-THREATENING: Combined CNS depression can cause fatal respiratory arrest. FDA Black Box Warning.",
            "apixaban": "Oxycodone does not directly interact with Apixaban, but fall-related injuries from opioid sedation increase bleeding risk in anticoagulated patients."
        }
    },
    "metformin": {
        "generic_name": "Metformin HCl",
        "brand_name": "Glucophage",
        "drug_class": "Biguanide Antihyperglycemic Agent",
        "side_effects": [
            "GI disturbances (diarrhea, nausea, bloating)",
            "Metallic taste in mouth",
            "Vitamin B12 deficiency with long-term use",
            "Lactic acidosis (rare but serious)"
        ],
        "warnings": "Contraindicated in severe renal impairment (eGFR < 30). Monitor B12 levels annually. Temporarily discontinue before iodinated contrast procedures.",
        "beers_criteria": "Generally appropriate. Monitor renal function periodically.",
        "interactions": {
            "alcohol": "Increases risk of lactic acidosis, especially in patients with hepatic impairment."
        }
    },
    "apixaban": {
        "generic_name": "Apixaban",
        "brand_name": "Eliquis",
        "drug_class": "Direct Oral Anticoagulant (Factor Xa Inhibitor)",
        "side_effects": [
            "Bleeding (bruising, nosebleeds, GI bleeding)",
            "Anemia",
            "Nausea",
            "Hypersensitivity reactions"
        ],
        "warnings": "Do not discontinue without physician guidance -- rebound thrombotic events can occur. Monitor for signs of bleeding. Dose adjust in elderly patients with low body weight or renal impairment.",
        "beers_criteria": "Preferred over warfarin in elderly for stroke prevention in atrial fibrillation due to lower bleeding risk.",
        "interactions": {
            "aspirin": "Concurrent use increases bleeding risk significantly.",
            "nsaids": "NSAIDs increase both GI bleeding risk and systemic bleeding risk when combined with anticoagulants."
        }
    },
    "acetaminophen": {
        "generic_name": "Acetaminophen",
        "brand_name": "Tylenol / Tylenol ER",
        "drug_class": "Non-Opioid Analgesic / Antipyretic",
        "side_effects": [
            "Hepatotoxicity at doses exceeding 3g/day",
            "Nausea at high doses",
            "Allergic skin reactions (rare)"
        ],
        "warnings": "Maximum daily dose 3000mg in elderly. Hepatotoxicity risk increases with alcohol use or pre-existing liver disease. Check all combination products for hidden acetaminophen content.",
        "beers_criteria": "Preferred first-line analgesic in elderly (safer than NSAIDs and opioids).",
        "interactions": {
            "warfarin": "Regular acetaminophen use can potentiate the anticoagulant effect of warfarin, increasing INR."
        }
    },
    "midodrine": {
        "generic_name": "Midodrine HCl",
        "brand_name": "Orvaten / ProAmatine",
        "drug_class": "Alpha-1 Adrenergic Agonist (Vasopressor)",
        "side_effects": [
            "Supine hypertension (elevated BP when lying down)",
            "Piloerection (goosebumps)",
            "Urinary retention",
            "Paresthesia (tingling/numbness)",
            "Scalp itching"
        ],
        "warnings": "Must be taken during upright hours only -- do NOT take before bedtime. Monitor supine blood pressure. Contraindicated in severe organic heart disease.",
        "beers_criteria": "Use cautiously in elderly. Monitor for supine hypertension regularly.",
        "interactions": {
            "fludrocortisone": "Additive pressor effects; monitor blood pressure closely.",
            "beta_blockers": "May blunt the efficacy of Midodrine due to opposing hemodynamic effects."
        }
    }
}

def clean_drug_name(drug_name: str) -> str:
    """Normalize drug name by stripping dosage details or punctuation."""
    name = drug_name.lower().strip()
    # If the user passed something like "Metoprolol Succinate 50mg", isolate the first word
    words = name.split()
    if words:
        return words[0]
    return name

def check_drug_side_effects(drug_name: str) -> str:
    """
    Search the official US FDA openFDA database for a drug's adverse reactions and warnings.
    No API key required. High reliability, zero cost.
    """
    try:
        if not drug_name:
            return "Error: drug_name must be provided."
            
        normalized = clean_drug_name(drug_name)
        encoded_name = urllib.parse.quote(f'openfda.brand_name:"{normalized}"+OR+openfda.generic_name:"{normalized}"')
        url = f'https://api.fda.gov/drug/label.json?search={encoded_name}&limit=1'
        
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                results = data.get("results", [])
                if results:
                    result = results[0]
                    
                    # Extract adverse reactions, warnings, or precautions
                    adverse_reactions = result.get("adverse_reactions", ["No detailed adverse reactions listed."])[0]
                    warnings = result.get("warnings_and_cautions", result.get("warnings", ["No direct warnings section found."]))[0]
                    
                    # Truncate to prevent token blowouts, retaining rich medical context
                    summary = (
                        f"### openFDA Drug Info: {drug_name.upper()}\n\n"
                        f"**Adverse Reactions / Side Effects (FDA):**\n"
                        f"{adverse_reactions[:800]}...\n\n"
                        f"**Warnings & Precautions (FDA):**\n"
                        f"{warnings[:800]}..."
                    )
                    return summary
        except Exception:
            # openFDA unreachable -- use embedded clinical reference database
            pass
            
        # Embedded clinical reference (legitimate offline knowledge base)
        if normalized in CLINICAL_REFERENCE_DATABASE:
            info = CLINICAL_REFERENCE_DATABASE[normalized]
            beers = f"\n**Beers Criteria (Geriatric):** {info.get('beers_criteria', 'N/A')}" if 'beers_criteria' in info else ""
            return (
                f"### Clinical Reference: {drug_name.upper()}\n\n"
                f"**Generic Name:** {info['generic_name']}\n"
                f"**Brand Name:** {info['brand_name']}\n"
                f"**Drug Class:** {info.get('drug_class', 'N/A')}\n\n"
                f"**Common Side Effects:**\n" + "\n".join([f"- {se}" for se in info['side_effects']]) + "\n\n"
                f"**Geriatric Warnings:**\n"
                f"{info['warnings']}"
                f"{beers}"
            )
        
        return f"No openFDA label or clinical reference record found for drug '{drug_name}'."
    except Exception as e:
        return f"Tool Execution Error (check_drug_side_effects): {str(e)}"

def check_drug_interactions(medications: list) -> str:
    """
    Cross-reference a list of drugs to check for dangerous drug-drug interactions.
    """
    try:
        if not medications or not isinstance(medications, list):
            return "Error: medications must be a non-empty list of strings."
            
        clean_meds = [clean_drug_name(med) for med in medications]
        interactions_found = []
        
        for i, med1 in enumerate(clean_meds):
            for j, med2 in enumerate(clean_meds[i+1:], start=i+1):
                # Check med1 -> med2 interactions
                if med1 in CLINICAL_REFERENCE_DATABASE and med2 in CLINICAL_REFERENCE_DATABASE[med1]["interactions"]:
                    interactions_found.append(
                        f"[WARNING] **DANGEROUS INTERACTION DETECTED** between **{medications[i]}** and **{medications[j]}**:\n"
                        f"{CLINICAL_REFERENCE_DATABASE[med1]['interactions'][med2]}"
                    )
                # Check med2 -> med1 interactions
                elif med2 in CLINICAL_REFERENCE_DATABASE and med1 in CLINICAL_REFERENCE_DATABASE[med2]["interactions"]:
                    interactions_found.append(
                        f"[WARNING] **DANGEROUS INTERACTION DETECTED** between **{medications[j]}** and **{medications[i]}**:\n"
                        f"{CLINICAL_REFERENCE_DATABASE[med2]['interactions'][med1]}"
                    )
                    
        if interactions_found:
            return "\n\n".join(interactions_found)
        return "No known dangerous interactions found between active medications."
    except Exception as e:
        return f"Tool Execution Error (check_drug_interactions): {str(e)}"

if __name__ == "__main__":
    # Test openFDA lookup
    print(check_drug_side_effects("Metoprolol"))
    # Test interaction check
    print(check_drug_interactions(["Metoprolol", "Lisinopril"]))
