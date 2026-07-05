-- Run this in your Supabase SQL Editor after the existing tables are created.
-- Adds backend-specific tables + proper RLS policies

-- ============================================================
-- ADMIN USERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_users (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id UUID UNIQUE NOT NULL REFERENCES auth.users(id),
  email TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('super_admin', 'admin', 'support')),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;

-- Allow service_role key (backend) to access admin_users
DROP POLICY IF EXISTS "Admin users service role only" ON admin_users;
CREATE POLICY "Admin users service role only"
  ON admin_users
  USING (true);

-- ============================================================
-- AGENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_name TEXT NOT NULL,
  personality_description TEXT,
  system_prompt TEXT NOT NULL,
  tone_tags TEXT,
  is_premium BOOLEAN DEFAULT FALSE,
  price_per_month INTEGER DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;

-- Service role access (backend uses service key)
DROP POLICY IF EXISTS "Agents service access" ON agents;
CREATE POLICY "Agents service access" ON agents
  FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- MESSAGES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id) ON DELETE CASCADE,
  business_id BIGINT REFERENCES business_profiles(id) ON DELETE CASCADE,
  direction TEXT NOT NULL CHECK (direction IN ('sent', 'received')),
  channel TEXT DEFAULT 'whatsapp',
  content TEXT NOT NULL,
  sequence_day INTEGER,
  status TEXT DEFAULT 'sent' CHECK (status IN ('sent', 'delivered', 'read', 'replied', 'failed', 'received')),
  meta_message_id TEXT,
  timestamp TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Messages service access" ON messages;
CREATE POLICY "Messages service access" ON messages
  FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- CONVERSATION HISTORY TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_history (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'model')),
  content TEXT,
  timestamp TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Conversation history service access" ON conversation_history;
CREATE POLICY "Conversation history service access" ON conversation_history
  FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- ADD COLUMNS TO EXISTING TABLES
-- ============================================================
ALTER TABLE business_profiles
  ADD COLUMN IF NOT EXISTS active_agent_id BIGINT REFERENCES agents(id);

-- Add WhatsApp columns for per-business WhatsApp numbers
ALTER TABLE business_profiles
  ADD COLUMN IF NOT EXISTS whatsapp_phone TEXT,
  ADD COLUMN IF NOT EXISTS meta_phone_number_id TEXT,
  ADD COLUMN IF NOT EXISTS whatsapp_verified BOOLEAN DEFAULT FALSE;

ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS response_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS personality_profile TEXT DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS best_contact_time TEXT,
  ADD COLUMN IF NOT EXISTS current_sequence_day INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS product_purchased TEXT,
  ADD COLUMN IF NOT EXISTS last_contacted TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS business_id BIGINT REFERENCES business_profiles(id);

-- Add next_booking column for customer appointments
ALTER TABLE customers ADD COLUMN IF NOT EXISTS next_booking timestamptz;

-- ============================================================
-- MESSAGE QUEUE (AI Pipeline)
-- ============================================================
CREATE TABLE IF NOT EXISTS message_queue (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id) ON DELETE CASCADE,
  business_id BIGINT REFERENCES business_profiles(id) ON DELETE CASCADE,
  message_type TEXT NOT NULL CHECK (message_type IN ('sequence','appointment_reminder','appointment_followup')),
  stage TEXT NOT NULL DEFAULT 'pending_schedule'
    CHECK (stage IN ('pending_schedule','pending_ai_gen','ready_to_send','sending','sent','failed','dead')),
  sequence_day INTEGER,
  payload JSONB DEFAULT '{}',
  ai_generated_text TEXT,
  meta_message_id TEXT,
  error_log TEXT,
  retry_count INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  scheduled_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE message_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Message queue service access" ON message_queue;
CREATE POLICY "Message queue service access" ON message_queue
  FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_message_queue_stage ON message_queue(stage);
CREATE INDEX IF NOT EXISTS idx_message_queue_scheduled ON message_queue(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_message_queue_business ON message_queue(business_id);
