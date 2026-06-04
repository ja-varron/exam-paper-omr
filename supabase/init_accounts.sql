-- Create profiles table for exam-paper-omr
-- This table stores user profile information

-- Enum for roles
DO $$ BEGIN
    CREATE TYPE public.user_role AS ENUM ('Instructor','Student','Admin');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Profiles table (one row per auth.user)
CREATE TABLE IF NOT EXISTS public.profiles (
  user_id uuid PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
  email text UNIQUE NOT NULL,
  first_name text NOT NULL,
  middle_name text,
  last_name text NOT NULL,
  role public.user_role NOT NULL DEFAULT 'Student',
  prc_exam_type text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  is_active boolean NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS profiles_role_idx ON public.profiles (role);

-- Trigger helper to keep `updated_at` fresh
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at_trigger ON public.profiles;
CREATE TRIGGER set_updated_at_trigger
BEFORE UPDATE ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- Sync auth.users -> public.profiles on signup
CREATE OR REPLACE FUNCTION public.handle_auth_user_created()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (user_id, email, first_name, middle_name, last_name, role, created_at)
  VALUES (NEW.id, NEW.email, '', NULL, '', 'Student', now())
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_auth_user_created();