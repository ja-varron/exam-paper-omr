-- Add PRC licensure exam type to profiles table
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS prc_exam_type text;

-- Helpful index for matching instructors and students by exam type
CREATE INDEX IF NOT EXISTS idx_profiles_prc_exam_type ON public.profiles(prc_exam_type);

COMMENT ON COLUMN public.profiles.prc_exam_type IS 'Selected PRC licensure exam type for account grouping and assignment logic';
