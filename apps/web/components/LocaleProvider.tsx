"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { dirOf, type Locale } from "../lib/i18n";

const STORAGE_KEY = "tp-locale";

function readStored(): Locale {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "ar" ? "ar" : "en";
  } catch {
    return "en"; // storage unavailable (private mode): session-only default
  }
}

function applyToDocument(locale: Locale): void {
  document.documentElement.lang = locale;
  document.documentElement.dir = dirOf(locale);
}

const LocaleContext = createContext<{ locale: Locale; setLocale: (next: Locale) => void }>({
  locale: "en",
  setLocale: () => undefined
});

/** Shared locale state: persists across navigation and refresh via localStorage,
 * applied to <html> lang/dir. Initial render is English to avoid SSR hydration
 * mismatch; the stored value applies on mount. */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    const stored = readStored();
    setLocaleState((current) => {
      if (current !== stored) {
        applyToDocument(stored);
        return stored;
      }
      applyToDocument(current);
      return current;
    });
  }, []);

  const setLocale = useCallback((next: Locale) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* persistence unavailable; in-memory still works for the session */
    }
    applyToDocument(next);
    setLocaleState(next);
  }, []);

  return <LocaleContext.Provider value={{ locale, setLocale }}>{children}</LocaleContext.Provider>;
}

export function useLocale(): { locale: Locale; setLocale: (next: Locale) => void } {
  return useContext(LocaleContext);
}
