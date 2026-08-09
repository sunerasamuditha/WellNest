import os
import json
import logging
from typing import Dict, Any, List

# Setup standard logger
logger = logging.getLogger("SilverGroveGCP")

# Flag state
FIRESTORE_ACTIVE = False
PUBSUB_ACTIVE = False

firestore_client = None
pubsub_publisher = None
pubsub_topic_path = None

# Detect project configuration
PROJECT_ID = os.environ.get("PROJECT_ID", "silvergrove-a2a")

# Attempt to initialize Firestore Client
try:
    from google.cloud import firestore
    # Auto-resolves credentials via Application Default Credentials (ADC) or environmental files
    firestore_client = firestore.Client(project=PROJECT_ID)
    FIRESTORE_ACTIVE = True
    logger.info(f"[GCP Config] Cloud Firestore client initialized successfully for project: {PROJECT_ID}")
except Exception as e:
    logger.warning(f"[GCP Config] Could not initialize Cloud Firestore client: {e}. Defaulting to local JSON storage.")

# Attempt to initialize Pub/Sub Client
try:
    from google.cloud import pubsub_v1
    pubsub_publisher = pubsub_v1.PublisherClient()
    pubsub_topic_path = pubsub_publisher.topic_path(PROJECT_ID, "a2a-alerts")
    PUBSUB_ACTIVE = True
    logger.info(f"[GCP Config] Cloud Pub/Sub client initialized successfully for topic: a2a-alerts")
except Exception as e:
    logger.warning(f"[GCP Config] Could not initialize Cloud Pub/Sub client: {e}. Defaulting to local in-memory event bus.")


# --- Firestore Operations ---

def get_resident_profile_db(resident_id: str) -> Dict[str, Any]:
    """
    Load resident profile details. If Firestore is active, reads from Firestore;
    otherwise, reads from the local residents.json file.
    """
    if FIRESTORE_ACTIVE:
        try:
            doc_ref = firestore_client.collection("residents").document(resident_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            logger.info(f"[Firestore] Profile {resident_id} not found in database. Reading from local storage.")
        except Exception as e:
            logger.error(f"[Firestore Error] Failed to read resident profile: {e}")
            
    # Local file storage
    residents_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "residents.json")
    try:
        with open(residents_file, "r") as f:
            residents = json.load(f)
            return residents.get(resident_id, {"error": f"Resident {resident_id} not found."})
    except Exception as e:
        return {"error": f"Failed to load resident profile: {str(e)}"}

def save_resident_profile_db(resident_id: str, data: Dict[str, Any]):
    """
    Persist or update a resident profile in Firestore or the local residents.json file.
    """
    if FIRESTORE_ACTIVE:
        try:
            firestore_client.collection("residents").document(resident_id).set(data)
            logger.info(f"[Firestore] Profile {resident_id} saved to Cloud Firestore.")
            return
        except Exception as e:
            logger.error(f"[Firestore Error] Failed to save profile: {e}")
            
    # Local file storage
    residents_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "residents.json")
    try:
        residents = {}
        if os.path.exists(residents_file):
            with open(residents_file, "r") as f:
                residents = json.load(f)
        residents[resident_id] = data
        with open(residents_file, "w") as f:
            json.dump(residents, f, indent=2)
    except Exception as e:
        logger.error(f"[Local Storage Error] Failed to write profile: {e}")

def get_alerts_db() -> List[Dict[str, Any]]:
    """
    Load alerts timeline. If Firestore is active, reads from Firestore ordered by timestamp;
    otherwise, reads from the local alerts_timeline.json file.
    """
    if FIRESTORE_ACTIVE:
        try:
            alerts_ref = firestore_client.collection("alerts").order_by("timestamp", direction=firestore.Query.DESCENDING)
            alerts = []
            for doc in alerts_ref.stream():
                alerts.append(doc.to_dict())
            return alerts
        except Exception as e:
            logger.error(f"[Firestore Error] Failed to load alerts: {e}")
            
    # Local file storage
    alerts_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alerts_timeline.json")
    try:
        if os.path.exists(alerts_file):
            with open(alerts_file, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"[Local Storage Error] Failed to read alerts: {e}")
    return []

def save_alert_db(alert: Dict[str, Any]):
    """
    Save a new alert to Firestore or prepend it to the local alerts_timeline.json file.
    """
    if FIRESTORE_ACTIVE:
        try:
            firestore_client.collection("alerts").document(alert["id"]).set(alert)
            logger.info(f"[Firestore] Alert {alert['id']} saved to Cloud Firestore.")
            return
        except Exception as e:
            logger.error(f"[Firestore Error] Failed to save alert: {e}")
            
    # Local file storage
    alerts_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alerts_timeline.json")
    try:
        alerts = []
        if os.path.exists(alerts_file):
            with open(alerts_file, "r") as f:
                alerts = json.load(f)
        alerts.insert(0, alert)
        with open(alerts_file, "w") as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        logger.error(f"[Local Storage Error] Failed to write alert: {e}")

def clear_alerts_db():
    """
    Clear all alerts from Firestore or overwrite the local alerts_timeline.json file with an empty list.
    """
    if FIRESTORE_ACTIVE:
        try:
            # Batch delete
            batch = firestore_client.batch()
            docs = firestore_client.collection("alerts").stream()
            count = 0
            for doc in docs:
                batch.delete(doc.reference)
                count += 1
            if count > 0:
                batch.commit()
            logger.info(f"[Firestore] Cleared {count} alerts from Cloud Firestore.")
            return
        except Exception as e:
            logger.error(f"[Firestore Error] Failed to clear alerts: {e}")
            
    # Local file storage
    alerts_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alerts_timeline.json")
    try:
        with open(alerts_file, "w") as f:
            json.dump([], f)
    except Exception as e:
        logger.error(f"[Local Storage Error] Failed to clear alerts: {e}")


# --- Pub/Sub Messaging Operations ---

def publish_alert_event(alert: Dict[str, Any]):
    """
    Publishes the alert over Google Cloud Pub/Sub topic to enable asynchronous A2A integrations.
    Falls back gracefully if Pub/Sub is inactive.
    """
    if PUBSUB_ACTIVE:
        try:
            alert_bytes = json.dumps(alert).encode("utf-8")
            future = pubsub_publisher.publish(pubsub_topic_path, data=alert_bytes)
            message_id = future.result()
            logger.info(f"[PubSub] Alert {alert['id']} published to topic with Message ID: {message_id}")
            return message_id
        except Exception as e:
            logger.error(f"[PubSub Error] Failed to publish message: {e}")
    else:
        logger.info(f"[Local Event Bus] Alert {alert['id']} dispatched to local message channel.")
        return f"local_{alert['id']}"
