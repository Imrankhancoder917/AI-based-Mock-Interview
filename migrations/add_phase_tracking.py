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
        print("Running database migrations...")
        
        # Alter table interview_sessions to add current_phase column
        try:
            db.session.execute(text("ALTER TABLE interview_sessions ADD COLUMN current_phase VARCHAR(80)"))
            db.session.commit()
            print("Successfully added current_phase column.")
        except Exception as e:
            db.session.rollback()
            print(f"Failed to add current_phase (might already exist): {e}")
            
        # Alter table interview_sessions to add phase_index column
        try:
            db.session.execute(text("ALTER TABLE interview_sessions ADD COLUMN phase_index INTEGER DEFAULT 0"))
            db.session.commit()
            print("Successfully added phase_index column.")
        except Exception as e:
            db.session.rollback()
            print(f"Failed to add phase_index (might already exist): {e}")
            
        print("Database migrations complete.")

if __name__ == "__main__":
    run_migration()
