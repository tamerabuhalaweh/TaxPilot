export type Locale = "en" | "ar";

export const STRINGS: Record<Locale, Record<string, string>> = {
  en: {
    "app.tagline": "AI-assisted reconciliation for accounting firms",
    "dashboard.title": "Dashboard",
    "dashboard.newReview": "New Review",
    "dashboard.empty": "No reviews yet. Start your first reconciliation review.",
    "health.backendUp": "Backend connected",
    "health.backendDown": "Backend unreachable",
    "health.checking": "Checking backend…"
  },
  ar: {
    "app.tagline": "تسوية مدعومة بالذكاء الاصطناعي لشركات المحاسبة",
    "dashboard.title": "لوحة التحكم",
    "dashboard.newReview": "مراجعة جديدة",
    "dashboard.empty": "لا توجد مراجعات بعد. ابدأ أول مراجعة تسوية.",
    "health.backendUp": "الخادم متصل",
    "health.backendDown": "تعذّر الوصول إلى الخادم",
    "health.checking": "جارٍ التحقق من الخادم…"
  }
};

export function t(locale: Locale, key: string): string {
  return STRINGS[locale][key] ?? STRINGS.en[key] ?? key;
}

export function dirOf(locale: Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}
