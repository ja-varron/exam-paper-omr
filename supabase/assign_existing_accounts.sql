-- One-time script to assign existing students to instructors based on PRC exam type
-- Run this after deploying the auto_assign_students_instructors.sql trigger
-- This ensures existing accounts are properly assigned

-- Assign existing students to existing instructors
INSERT INTO public.instructor_students (instructor_id, student_id, created_at)
SELECT i.user_id, s.user_id, now()
FROM public.profiles i
CROSS JOIN public.profiles s
WHERE i.role = 'Instructor'
  AND s.role = 'Student'
  AND i.prc_exam_type = s.prc_exam_type
  AND i.is_active = true
  AND s.is_active = true
ON CONFLICT (instructor_id, student_id) DO NOTHING;

-- Log the assignments made
SELECT
  'Assignments created' as status,
  COUNT(*) as total_assignments
FROM public.instructor_students
WHERE created_at >= now() - interval '1 minute';