import Link from "next/link";

/** Honestly labeled placeholder: review creation arrives in Sprint 1.
 * This screen creates nothing and claims nothing — it states what exists. */
export default function NewReviewPlaceholder() {
  return (
    <main>
      <p>
        <Link href="/">← Back to Dashboard</Link>
      </p>
      <h1>New Review — coming in Sprint 1</h1>
      <div className="tp-card">
        <p>
          Review creation (client selection, upload, mapping, reconciliation) is not implemented yet. The
          working foundation in place today: backend health checks, background-job queue, database
          migrations, and this bilingual interface shell.
        </p>
        <p className="tp-muted">Next slice: authentication, tenant workspaces, and client management.</p>
      </div>
    </main>
  );
}
