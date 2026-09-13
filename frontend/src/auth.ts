import { createClient, type Session } from '@supabase/supabase-js';

export type AuthSession = Pick<Session, 'access_token' | 'user'>;

export interface AuthGateway {
  getSession: () => Promise<{ session: AuthSession | null }>;
  signInWithPassword: (credentials: {
    email: string;
    password: string;
  }) => Promise<{ session: AuthSession | null; error: Error | null }>;
  signOut: () => Promise<{ error: Error | null }>;
}

export function createAuthGateway(): AuthGateway {
  const url = import.meta.env.VITE_SUPABASE_URL;
  const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !publishableKey) {
    const configurationError = new Error('Authentication is not configured.');
    return {
      getSession: () => Promise.reject(configurationError),
      signInWithPassword: () => Promise.reject(configurationError),
      signOut: () => Promise.reject(configurationError),
    };
  }

  const client = createClient(url, publishableKey);
  return {
    async getSession() {
      const { data, error } = await client.auth.getSession();
      if (error) throw error;
      return { session: data.session };
    },
    async signInWithPassword(credentials) {
      const { data, error } = await client.auth.signInWithPassword(credentials);
      return { session: data.session, error };
    },
    async signOut() {
      return client.auth.signOut({ scope: 'local' });
    },
  };
}
