/**
 * Preview modes (build-time contract for Vercel environments).
 *
 * - `connected` (default): the real product. Auth, clients and all working
 *   features talk to the backend through the same-origin BFF proxy
 *   (`API_INTERNAL_URL`, server-side). Nothing is simulated.
 * - `demo`: protected visual walkthrough with explicitly marked synthetic
 *   content. No backend is contacted for product data; no financial processing
 *   is simulated — unimplemented capabilities render as honest
 *   preview-only / coming-soon states, never invented outcomes.
 *
 * Set `NEXT_PUBLIC_PREVIEW_MODE=demo` on Vercel Preview environments and leave
 * Production (and connected staging previews) on the default.
 */
export type PreviewMode = "demo" | "connected";

export const PREVIEW_MODE: PreviewMode =
  process.env.NEXT_PUBLIC_PREVIEW_MODE === "demo" ? "demo" : "connected";

export function isDemoMode(): boolean {
  return PREVIEW_MODE === "demo";
}
