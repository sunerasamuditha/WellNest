import os
import json
from google.cloud import firestore

# Ensure the credentials and project are set
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "wellnest-a2a-key.json"
os.environ["GOOGLE_CLOUD_PROJECT"] = "wellnest-a2a"

def import_residents():
    try:
        db = firestore.Client(database="wellnest-firestore")
        
        with open('data/residents.json', 'r') as f:
            residents = json.load(f)
            
        print("Importing residents to wellnest-a2a project (wellnest-firestore)...")
        
        for resident_id, data in residents.items():
            doc_ref = db.collection('residents').document(resident_id)
            doc_ref.set(data)
            print(f"Imported: {resident_id} ({data.get('name')})")
            
        print("\nAll residents imported successfully!")
    except Exception as e:
        print(f"Error importing residents: {e}")

if __name__ == "__main__":
    import_residents()
