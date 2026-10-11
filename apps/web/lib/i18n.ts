export type Locale = "en" | "ar";

export const STRINGS: Record<Locale, Record<string, string>> = {
  en: {
    "app.tagline": "AI-assisted reconciliation for accounting firms",
    "dashboard.title": "Dashboard",
    "dashboard.newReview": "New Review",
    "dashboard.empty": "No reviews yet. Start your first reconciliation review.",
    "dashboard.signinRequired": "Sign in required",
    "dashboard.signinRequiredHint": "Sign in to see your workspace and clients.",
    "dashboard.signin": "Sign in",
    "dashboard.clients": "Clients",
    "dashboard.newClientName": "New client name",
    "dashboard.addClient": "Add Client",
    "dashboard.signout": "Sign out",
    "health.backendUp": "Backend connected",
    "health.backendDown": "Backend unreachable",
    "health.checking": "Checking backend…",
    "auth.signin": "Sign in",
    "auth.createAccount": "Create account",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.firmName": "Firm name",
    "auth.needAccount": "Need an account? Register",
    "auth.haveAccount": "Have an account? Sign in",
    "auth.back": "Back",
    "auth.createdCheckEmail": "Account created. Check your email to verify, then sign in."
  },
  ar: {
    "app.tagline": "تسوية مدعومة بالذكاء الاصطناعي لشركات المحاسبة",
    "dashboard.title": "لوحة التحكم",
    "dashboard.newReview": "مراجعة جديدة",
    "dashboard.empty": "لا توجد مراجعات بعد. ابدأ أول مراجعة تسوية.",
    "dashboard.signinRequired": "تسجيل الدخول مطلوب",
    "dashboard.signinRequiredHint": "سجّل الدخول لعرض مساحة العمل والعملاء.",
    "dashboard.signin": "تسجيل الدخول",
    "dashboard.clients": "العملاء",
    "dashboard.newClientName": "اسم العميل الجديد",
    "dashboard.addClient": "إضافة عميل",
    "dashboard.signout": "تسجيل الخروج",
    "health.backendUp": "الخادم متصل",
    "health.backendDown": "تعذّر الوصول إلى الخادم",
    "health.checking": "جارٍ التحقق من الخادم…",
    "auth.signin": "تسجيل الدخول",
    "auth.createAccount": "إنشاء حساب",
    "auth.email": "البريد الإلكتروني",
    "auth.password": "كلمة المرور",
    "auth.firmName": "اسم الشركة",
    "auth.needAccount": "تحتاج حساباً؟ سجّل",
    "auth.haveAccount": "لديك حساب؟ سجّل الدخول",
    "auth.back": "رجوع",
    "auth.createdCheckEmail": "تم إنشاء الحساب. تحقق من بريدك الإلكتروني ثم سجّل الدخول."
  }
};

export function t(locale: Locale, key: string): string {
  return STRINGS[locale][key] ?? STRINGS.en[key] ?? key;
}

export function dirOf(locale: Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}
