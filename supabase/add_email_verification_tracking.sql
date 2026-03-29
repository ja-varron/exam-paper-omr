-- Add email verification tracking to profiles table
-- This tracks whether the account creation email was successfully sent

ALTER TABLE public.profiles 
ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE;

-- Create index for efficient lookups of unverified accounts
CREATE INDEX IF NOT EXISTS idx_profiles_email_verified_at ON public.profiles(email_verified_at);

-- Add comment for clarity
COMMENT ON COLUMN public.profiles.email_verified_at IS 'Timestamp when the account creation email was successfully sent to the user';
