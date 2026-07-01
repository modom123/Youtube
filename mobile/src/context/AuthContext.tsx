import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getProfile, login as apiLogin, register as apiRegister, logout as apiLogout, getSession } from '../services/api';

interface User {
  id: number;
  name: string;
  email: string;
  subscription_tier: string;
  videos_used: number;
  credits_used: number;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  isAuthenticated: false,
  login: async () => {},
  register: async () => {},
  logout: async () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const session = await getSession();
      if (!session) {
        setUser(null);
        return;
      }
      const profile = await getProfile();
      setUser(profile);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setIsLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    await apiLogin(email, password);
    await refresh();
  };

  const register = async (name: string, email: string, password: string) => {
    await apiRegister(name, email, password);
    await refresh();
  };

  const logout = async () => {
    await apiLogout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{
      user,
      isLoading,
      isAuthenticated: !!user,
      login,
      register,
      logout,
      refresh,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
