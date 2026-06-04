-- Create instructor_students table to link students to instructors
-- This establishes the relationship: which students belong to which instructor

CREATE TABLE IF NOT EXISTS public.instructor_students (
  id BIGSERIAL PRIMARY KEY,
  instructor_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(instructor_id, student_id)
);

-- Create index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_instructor_students_instructor_id ON public.instructor_students(instructor_id);
CREATE INDEX IF NOT EXISTS idx_instructor_students_student_id ON public.instructor_students(student_id);