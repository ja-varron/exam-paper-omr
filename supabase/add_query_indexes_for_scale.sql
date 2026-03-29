-- Query-performance indexes for high-traffic exam assignment and result lookups.
-- Safe to run multiple times.

create index if not exists idx_exam_results_student_exam_created
  on public.exam_results (student_id, exam_id, created_at desc);

create index if not exists idx_exam_results_exam_student
  on public.exam_results (exam_id, student_id);

create index if not exists idx_instructor_students_student_instructor
  on public.instructor_students (student_id, instructor_id);

create index if not exists idx_exams_instructor_exam_date
  on public.exams (instructor_id, exam_date desc);
