-- Add unique constraint for emails to prevent duplicate account creation
-- This ensures email uniqueness at the database level

ALTER TABLE public.profiles 
ADD CONSTRAINT profiles_email_unique UNIQUE(email);

-- Create index for efficient email lookup
CREATE INDEX IF NOT EXISTS idx_profiles_email_unique ON public.profiles(email);

-- Add comment for clarity
COMMENT ON CONSTRAINT profiles_email_unique ON public.profiles IS 'Ensures each email address can only be used for one account';
