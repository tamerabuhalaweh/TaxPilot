/**
 * Synthetic demo fixtures for visual preview mode ONLY.
 *
 * Every record is invented placeholder content for UI review. Nothing here is a
 * reconciliation outcome, a tax conclusion, or customer data. The UI must render
 * these behind an explicit demo banner (see components/DemoBanner) and must
 * never present them as processed results.
 */
export interface DemoClient {
  id: string;
  name: string;
  nameAr: string;
  sector: string;
  sectorAr: string;
  status: "active" | "archived";
  activeReviews: number;
  lastActivity: string;
}

export interface DemoReview {
  id: string;
  clientName: string;
  clientNameAr: string;
  period: string;
  type: string;
  typeAr: string;
  status: "draft" | "in_progress" | "ready_for_approval" | "approved";
  updatedAt: string;
}

export const DEMO_FIRM = { name: "Al-Nahda Accounting", nameAr: "النهضة للمحاسبة" };

export const DEMO_CLIENTS: DemoClient[] = [
  {
    id: "demo-client-1",
    name: "Example Trading LLC",
    nameAr: "شركة المثال التجارية",
    sector: "Retail",
    sectorAr: "تجزئة",
    status: "active",
    activeReviews: 1,
    lastActivity: "2026-10-02"
  },
  {
    id: "demo-client-2",
    name: "Jordan Food Industries",
    nameAr: "الشركة الأردنية للصناعات الغذائية",
    sector: "Manufacturing",
    sectorAr: "صناعة",
    status: "active",
    activeReviews: 0,
    lastActivity: "2026-09-18"
  },
  {
    id: "demo-client-3",
    name: "Amman Consulting Group",
    nameAr: "مجموعة عمان الاستشارية",
    sector: "Services",
    sectorAr: "خدمات",
    status: "archived",
    activeReviews: 0,
    lastActivity: "2026-06-30"
  }
];

export const DEMO_REVIEWS: DemoReview[] = [
  {
    id: "demo-review-1",
    clientName: "Example Trading LLC",
    clientNameAr: "شركة المثال التجارية",
    period: "2026-01-01 – 2026-09-30",
    type: "JoFotara reconciliation",
    typeAr: "تسوية الفوترة",
    status: "in_progress",
    updatedAt: "2026-10-02"
  },
  {
    id: "demo-review-2",
    clientName: "Example Trading LLC",
    clientNameAr: "شركة المثال التجارية",
    period: "2025-01-01 – 2025-12-31",
    type: "JoFotara reconciliation",
    typeAr: "تسوية الفوترة",
    status: "approved",
    updatedAt: "2026-03-14"
  }
];
