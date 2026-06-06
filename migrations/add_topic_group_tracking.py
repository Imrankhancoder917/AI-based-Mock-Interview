import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import create_app
from extensions import db
from sqlalchemy import text

def run_migration():
    app = create_app()
    with app.app_context():
        print("Running database migrations for topic_key...")
        
        # Alter table questions to add topic_key column
        try:
            db.session.execute(text("ALTER TABLE questions ADD COLUMN topic_key VARCHAR(120)"))
            db.session.commit()
            print("Successfully added topic_key column to questions table.")
        except Exception as e:
            db.session.rollback()
            print(f"Failed to add topic_key (might already exist): {e}")
            
        print("Database migrations complete.")

if __name__ == "__main__":
    run_migration()
