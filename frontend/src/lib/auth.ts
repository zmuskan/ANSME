import { useSyncExternalStore } from 'react';
import type { User, Session } from '@supabase/supabase-js';
import { getSupabase, isSupabaseConfigured } from './supabase';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface Profile {
  id: string;
  email: string | null;
  fullName: string | null;
  avatarUrl: string | null;
  isAnonymous: boolean;
}

interface AuthState {
  status: AuthStatus;
  user: User | null;
  profile: Profile | null;
  session: Session | null;
  error: Error | null;
}

function mapUserToProfile(user: User): Profile {
  return {
    id: user.id,
    email: user.email ?? null,
    fullName:
      user.user_metadata?.["full_name"] ??
      user.user_metadata?.["name"] ??
      null,
    avatarUrl: user.user_metadata?.["avatar_url"] ?? null,
    isAnonymous: Boolean(user.is_anonymous),
  };
}

let currentState: AuthState = {
  status: 'loading',
  user: null,
  profile: null,
  session: null,
  error: null,
};

const listeners = new Set<() => void>();
let authSubscription: { unsubscribe: () => void } | null = null;

function setState(newState: Partial<AuthState>): void {
  currentState = { ...currentState, ...newState };
  listeners.forEach((listener) => listener());
}

let isInitialized = false;

function initAuthStore(): void {
  if (isInitialized || typeof window === 'undefined') return;
  isInitialized = true;

  if (!isSupabaseConfigured) {
    setState({
      status: 'unauthenticated',
      user: null,
      profile: null,
      session: null,
      error: new Error('Supabase is not configured.'),
    });
    return;
  }

  const supabase = getSupabase();

  supabase.auth
    .getSession()
    .then(({ data: { session }, error }) => {
      if (error) {
        setState({
          status: 'unauthenticated',
          user: null,
          profile: null,
          session: null,
          error,
        });
        return;
      }

      if (session?.user) {
        setState({
          status: 'authenticated',
          user: session.user,
          profile: mapUserToProfile(session.user),
          session,
          error: null,
        });
      } else {
        setState({
          status: 'unauthenticated',
          user: null,
          profile: null,
          session: null,
          error: null,
        });
      }
    })
    .catch((err: unknown) => {
      setState({
        status: 'unauthenticated',
        user: null,
        profile: null,
        session: null,
        error: err instanceof Error ? err : new Error(String(err)),
      });
    });

  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((_event, session) => {
    if (session?.user) {
      setState({
        status: 'authenticated',
        user: session.user,
        profile: mapUserToProfile(session.user),
        session,
        error: null,
      });
    } else {
      setState({
        status: 'unauthenticated',
        user: null,
        profile: null,
        session: null,
        error: null,
      });
    }
  });

  authSubscription = subscription;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  initAuthStore();

  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): AuthState {
  return currentState;
}

function getServerSnapshot(): AuthState {
  return {
    status: 'loading',
    user: null,
    profile: null,
    session: null,
    error: null,
  };
}

export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export async function signInWithGoogle(redirectTo?: string): Promise<void> {
  const supabase = getSupabase();
  const options = redirectTo
    ? { redirectTo }
    : { redirectTo: window.location.href };

  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options,
  });

  if (error) {
    throw error;
  }
}

export async function signInAsGuest(): Promise<Session> {
  const supabase = getSupabase();

  const {
    data: { session },
    error: sessionError,
  } = await supabase.auth.getSession();

  if (sessionError) {
    throw new Error(`Unable to check the current sign-in session: ${sessionError.message}`);
  }

  if (session?.user && session.access_token) {
    return session;
  }

  const {
    data: { session: guestSession },
    error,
  } = await supabase.auth.signInAnonymously();

  if (error) {
    throw new Error(`Guest sign-in failed: ${error.message}`);
  }

  if (!guestSession?.user || !guestSession.access_token) {
    throw new Error(
      'Guest sign-in did not create a valid session. Check that anonymous sign-ins are enabled in Supabase.'
    );
  }

  const {
    data: { session: activeSession },
    error: activeSessionError,
  } = await supabase.auth.getSession();

  if (activeSessionError) {
    throw new Error(
      `Guest sign-in succeeded, but its session could not be loaded: ${activeSessionError.message}`
    );
  }

  if (!activeSession?.user || !activeSession.access_token) {
    throw new Error(
      'Guest sign-in succeeded, but no active session was saved. Please try signing in again.'
    );
  }

  return activeSession;
}

export async function signOut(): Promise<void> {
  const supabase = getSupabase();
  const { error } = await supabase.auth.signOut();

  if (error) {
    throw error;
  }
}

export async function getAccessToken(): Promise<string> {
  if (typeof window === 'undefined') {
    throw new Error('A Supabase access token is only available in the browser.');
  }

  const supabase = getSupabase();
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession();

  if (error) {
    throw new Error(`Unable to retrieve the current sign-in session: ${error.message}`);
  }

  if (!session?.user || !session.access_token) {
    throw new Error(
      'Your sign-in session is missing. Please sign in again before using ANSME.'
    );
  }

  return session.access_token;
}

export function isAuthenticated(): boolean {
  return currentState.status === 'authenticated';
}