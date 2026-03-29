-- Automatic assignment of students to instructors based on PRC exam type
-- When a new student account is created, assign to all instructors with same PRC exam type
-- When a new instructor account is created, assign all students with same PRC exam type

-- Function to assign students to instructors
CREATE OR REPLACE FUNCTION public.assign_students_to_instructors()
RETURNS TRIGGER AS $$
BEGIN
  -- If new student profile
  IF NEW.role = 'Student' AND NEW.prc_exam_type IS NOT NULL THEN
    -- Assign to all instructors with same PRC exam type
    INSERT INTO public.instructor_students (instructor_id, student_id, created_at)
    SELECT i.user_id, NEW.user_id, now()
    FROM public.profiles i
    WHERE i.role = 'Instructor'
      AND i.prc_exam_type = NEW.prc_exam_type
      AND i.is_active = true
    ON CONFLICT (instructor_id, student_id) DO NOTHING;
  END IF;

  -- If new instructor profile
  IF NEW.role = 'Instructor' AND NEW.prc_exam_type IS NOT NULL THEN
    -- Assign all students with same PRC exam type
    INSERT INTO public.instructor_students (instructor_id, student_id, created_at)
    SELECT NEW.user_id, s.user_id, now()
    FROM public.profiles s
    WHERE s.role = 'Student'
      AND s.prc_exam_type = NEW.prc_exam_type
      AND s.is_active = true
    ON CONFLICT (instructor_id, student_id) DO NOTHING;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger on profiles insert
DROP TRIGGER IF EXISTS assign_students_on_profile_insert ON public.profiles;
CREATE TRIGGER assign_students_on_profile_insert
AFTER INSERT ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.assign_students_to_instructors();

-- Also trigger on update if role or prc_exam_type changes
DROP TRIGGER IF EXISTS assign_students_on_profile_update ON public.profiles;
CREATE TRIGGER assign_students_on_profile_update
AFTER UPDATE OF role, prc_exam_type ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.assign_students_to_instructors();