import type { Metadata } from "next";
import { LocaleProvider } from "../components/LocaleProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "TaxPilot",
  description: "AI-assisted reconciliation for accounting firms"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body>
        <LocaleProvider>
          <div className="tp-shell">{children}</div>
        </LocaleProvider>
      </body>
    </html>
  );
}
