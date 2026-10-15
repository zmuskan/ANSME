import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env["VITE_SUPABASE_URL"] as string | undefined;
const supabaseAnonKey = import.meta.env["VITE_SUPABASE_ANON_KEY"] as string | undefined;

export const isSupabaseConfigured: boolean = Boolean(
  supabaseUrl &&
    supabaseAnonKey &&
    supabaseUrl !== 'https://your-project.supabase.co' &&
    supabaseAnonKey !== 'your-anon-key'
);

let supabaseInstance: ReturnType<typeof createClient> | null = null;

export function getSupabase(): SupabaseClient {
  if (typeof window === 'undefined') {
    throw new Error(
      'Supabase client cannot be initialized on the server side in a browser-only auth setup.'
    );
  }

  if (!isSupabaseConfigured || !supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      'Supabase environment variables are missing or incomplete. ' +
        'Please define VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your environment configuration.'
    );
  }

  if (!supabaseInstance) {
    supabaseInstance = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
        storageKey: 'ansme.auth',
    },
    realtime: {
        params: {
        eventsPerSecond: 0,
        },
    },
    });
  }

  return supabaseInstance;
}