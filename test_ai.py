import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db
from models.database import User
from flask_login import login_user
import json

with app.app_context():
    # Login as first user
    user = User.query.first()
    if not user:
        print("No user found")
        exit(1)
        
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        
    print("Logged in as:", user.email)
    
    # Hit generate-question API
    response = client.post('/api/interview/generate-question', 
                           json={"difficulty": 5, "session_history": []})
    
    print("Status:", response.status_code)
    try:
        print("Response:", json.dumps(response.json, indent=2))
    except Exception as e:
        print("Failed to decode JSON:", response.data)
