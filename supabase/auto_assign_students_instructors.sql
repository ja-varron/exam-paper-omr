-- Automatic assignment of students to instructors based on PRC exam type
-- When a new student account is created, assign to all instructors with same PRC exam type
-- When a new instructor account is created, assign all students with same PRC exam type
-- When PRC exam type changes, automatically adjust assignments

-- Function to assign students to instructors
CREATE OR REPLACE FUNCTION public.assign_students_to_instructors()
RETURNS TRIGGER AS $$
BEGIN
  -- Handle INSERT operations
  IF TG_OP = 'INSERT' THEN
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

  -- Handle UPDATE operations
  ELSIF TG_OP = 'UPDATE' THEN
    -- Only process if role or prc_exam_type changed
    IF (OLD.role != NEW.role) OR (OLD.prc_exam_type IS DISTINCT FROM NEW.prc_exam_type) THEN

      -- If student role changed or prc_exam_type changed
      IF NEW.role = 'Student' THEN
        -- Remove from instructors who don't match new exam type
        IF OLD.prc_exam_type IS NOT NULL AND (OLD.prc_exam_type != NEW.prc_exam_type OR OLD.role != NEW.role) THEN
          DELETE FROM public.instructor_students
          WHERE student_id = NEW.user_id
            AND instructor_id NOT IN (
              SELECT i.user_id
              FROM public.profiles i
              WHERE i.role = 'Instructor'
                AND i.prc_exam_type = NEW.prc_exam_type
                AND i.is_active = true
            );
        END IF;

        -- Add to instructors who match new exam type
        IF NEW.prc_exam_type IS NOT NULL THEN
          INSERT INTO public.instructor_students (instructor_id, student_id, created_at)
          SELECT i.user_id, NEW.user_id, now()
          FROM public.profiles i
          WHERE i.role = 'Instructor'
            AND i.prc_exam_type = NEW.prc_exam_type
            AND i.is_active = true
          ON CONFLICT (instructor_id, student_id) DO NOTHING;
        END IF;

      -- If instructor role changed or prc_exam_type changed
      ELSIF NEW.role = 'Instructor' THEN
        -- Remove students who don't match new exam type
        IF OLD.prc_exam_type IS NOT NULL AND (OLD.prc_exam_type != NEW.prc_exam_type OR OLD.role != NEW.role) THEN
          DELETE FROM public.instructor_students
          WHERE instructor_id = NEW.user_id
            AND student_id NOT IN (
              SELECT s.user_id
              FROM public.profiles s
              WHERE s.role = 'Student'
                AND s.prc_exam_type = NEW.prc_exam_type
                AND s.is_active = true
            );
        END IF;

        -- Add students who match new exam type
        IF NEW.prc_exam_type IS NOT NULL THEN
          INSERT INTO public.instructor_students (instructor_id, student_id, created_at)
          SELECT NEW.user_id, s.user_id, now()
          FROM public.profiles s
          WHERE s.role = 'Student'
            AND s.prc_exam_type = NEW.prc_exam_type
            AND s.is_active = true
          ON CONFLICT (instructor_id, student_id) DO NOTHING;
        END IF;

      -- If role changed from Student/Instructor to something else, remove all assignments
      ELSIF OLD.role IN ('Student', 'Instructor') AND NEW.role NOT IN ('Student', 'Instructor') THEN
        DELETE FROM public.instructor_students
        WHERE student_id = NEW.user_id OR instructor_id = NEW.user_id;
      END IF;
    END IF;
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