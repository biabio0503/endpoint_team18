-- Preserve existing cookie owners and all plan references. They cannot be claimed
-- by a new account without a separate, verified migration procedure.
ALTER TABLE public.session_owners
  ADD COLUMN auth_user_id uuid REFERENCES auth.users(id),
  ADD CONSTRAINT session_owners_auth_user_id_key UNIQUE (auth_user_id);

-- The public Data API remains closed for all private tables. The backend uses
-- its own database connection and checks the verified owner on every operation.
-- Existing RLS and revocations remain in force; anonymous Auth users are also
-- members of the authenticated database role and must not receive table grants.
