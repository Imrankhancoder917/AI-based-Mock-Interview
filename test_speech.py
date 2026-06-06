import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app
from models.database import User
import json

with app.app_context():
    user = User.query.first()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        
    print("Testing /api/speech/respond")
    response = client.post('/api/speech/respond', json={"text": "Hello world", "language": "en", "slow": False})
    
    print("Status:", response.status_code)
    try:
        data = response.json
        print("Response ok:", data.get("ok"))
        print("Data length:", len(data.get("data_url", "")))
    except Exception as e:
        print("Failed to decode JSON:", response.data)
