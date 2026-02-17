import os
import time
import requests
import json
from loguru import logger
from app.config import config
from app.utils import utils

# To use Veo via Vertex AI REST API (since we might not have google-cloud-aiplatform installed)
# Or if user provided service account key, we can use google-auth.
# For simplicity and to avoid dependency hell, we can try to use google-auth if available,
# or just assume the environment is authenticated if no key is provided.

class VeoGenerator:
    def __init__(self):
        self.enabled = config.app.get("veo", {}).get("enable", False)
        self.project_id = config.app.get("veo", {}).get("project_id", "")
        self.location = config.app.get("veo", {}).get("location", "us-central1")
        self.model_name = config.app.get("veo", {}).get("model_name", "veo-001")
        self.key_json = config.app.get("veo", {}).get("private_key_json", "")
        self.credentials = None
        self._setup_auth()

    def _setup_auth(self):
        if not self.enabled:
            return
            
        try:
            from google.oauth2 import service_account
            import google.auth
            from google.auth.transport.requests import Request
            
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            
            if self.key_json and os.path.exists(self.key_json):
                self.credentials = service_account.Credentials.from_service_account_file(
                    self.key_json, scopes=scopes
                )
                logger.info(f"Veo: Loaded credentials from {self.key_json}")
            else:
                self.credentials, self.project_id = google.auth.default(scopes=scopes)
                logger.info("Veo: Using default application credentials")
                
        except ImportError:
            logger.error("Veo: google-auth library not found. Please install: pip install google-auth google-auth-httplib2 google-auth-oauthlib")
        except Exception as e:
            logger.error(f"Veo Auth Init Failed: {e}")

    def get_access_token(self):
        if not self.credentials:
            return None
        
        try:
            from google.auth.transport.requests import Request
            self.credentials.refresh(Request())
            return self.credentials.token
        except Exception as e:
            logger.error(f"Veo: Failed to refresh token: {e}")
            return None

    def generate_video(self, prompt: str, duration_seconds: int = 8):
        if not self.enabled:
            logger.warning("Veo is disabled in config")
            return None

        if not self.project_id:
            logger.error("Veo: Project ID is missing")
            return None
            
        token = self.get_access_token()
        if not token:
            logger.error("Veo: Failed to get access token")
            return None

        # Veo (Vertex AI) Endpoint
        # Note: Actual endpoint path depends on the model version (e.g. publisher google vs deepmind)
        # Using the standard Vertex AI prediction endpoint structure
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model_name}:predict"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        # Veo Payload Structure (Approximate - need to verify exact schema for Veo)
        # Assuming standard request format for video generation models
        data = {
            "instances": [
                {
                    "prompt": prompt,
                    # "duration": f"{duration_seconds}s" # Some models take duration
                }
            ],
            "parameters": {
                "sampleCount": 1,
                # "storageUri": f"gs://{self.bucket_name}/..." # If we had a bucket
            }
        }
        
        logger.info(f"Veo: Submitting generation request for prompt: {prompt[:50]}...")
        
        try:
            # Set a long timeout (e.g., 5 minutes) as video generation can be slow
            response = requests.post(url, headers=headers, json=data, timeout=300)
            
            if response.status_code != 200:
                logger.error(f"Veo Request Failed ({response.status_code}): {response.text}")
                return None
                
            result = response.json()
            
            # Parse result (Dependent on model output schema)
            # Veo might return a long-running operation ID usually, 
            # OR direct bytes if it's fast (unlikely for video).
            # If it returns base64 video directly:
            if "predictions" in result:
                import base64
                for prediction in result["predictions"]:
                    # Look for bytes/video content
                    if "bytesBase64Encoded" in prediction:
                         video_data = base64.b64decode(prediction["bytesBase64Encoded"])
                         return self._save_video(video_data)
                    elif "video" in prediction:
                         # Handle other schema
                         pass
            
            logger.info(f"Veo Response: {result}")
            return None
            
        except Exception as e:
            logger.error(f"Veo Generation Error: {e}")
            return None
            
    def _save_video(self, video_data):
        from uuid import uuid4
        filename = f"veo_{uuid4().hex}.mp4"
        cache_dir = utils.storage_dir("cache_videos")
        filepath = os.path.join(cache_dir, filename)
        
        with open(filepath, "wb") as f:
            f.write(video_data)
        
        logger.success(f"Veo: Video saved to {filepath}")
        return filepath

generator = VeoGenerator()
