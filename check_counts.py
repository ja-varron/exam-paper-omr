import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv('backend/.env')

# Database connection - remove SQLAlchemy prefix
db_url = os.getenv('DATABASE_URL').replace('postgresql+psycopg://', 'postgresql://')
conn = psycopg2.connect(db_url)
cursor = conn.cursor()

# Get all instructors and their PRC exam types
print('=== INSTRUCTORS ===')
cursor.execute("""
    SELECT user_id, CONCAT(first_name, ' ', last_name) as full_name, prc_exam_type
    FROM public.profiles
    WHERE role = 'Instructor' AND is_active = true
""")
instructors = cursor.fetchall()
for instructor in instructors:
    print(f'{instructor[0]}: {instructor[1]} - PRC: {instructor[2]}')

print('\n=== STUDENT COUNTS BY PRC TYPE ===')
# Count students by PRC exam type
cursor.execute("""
    SELECT prc_exam_type, COUNT(*)
    FROM public.profiles
    WHERE role = 'Student' AND is_active = true
    GROUP BY prc_exam_type
    ORDER BY prc_exam_type
""")
student_counts = cursor.fetchall()
for prc_type, count in student_counts:
    print(f'{prc_type}: {count} students')

cursor.close()
conn.close()