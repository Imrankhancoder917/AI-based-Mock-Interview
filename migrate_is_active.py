import sqlite3
import os

db_path = '/tmp/interviewforge.db'

def migrate():
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE candidate_profiles ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 0;")
        print("Added is_active to candidate_profiles")
    except sqlite3.OperationalError as e:
        print(f"Error on candidate_profiles: {e}")

    try:
        cursor.execute("ALTER TABLE job_descriptions ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 0;")
        print("Added is_active to job_descriptions")
    except sqlite3.OperationalError as e:
        print(f"Error on job_descriptions: {e}")

    # For each user, set the latest candidate profile to active=1
    cursor.execute("""
        UPDATE candidate_profiles 
        SET is_active = 1 
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY created_at DESC) as rn 
                FROM candidate_profiles
            ) WHERE rn = 1
        )
    """)

    # For each user, set the latest JD to active=1
    cursor.execute("""
        UPDATE job_descriptions 
        SET is_active = 1 
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY created_at DESC) as rn 
                FROM job_descriptions
            ) WHERE rn = 1
        )
    """)

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
