"use client";

import { useId, useRef, useState } from "react";

/**
 * Accessible tab widget (WAI-APG tab pattern, manual activation).
 *
 * - Roving tabindex: the active tab is tabbable, others are reached by arrow keys.
 * - Arrow keys move selection; direction follows the document (in RTL locales
 *   ArrowLeft advances, ArrowRight goes back). Home/End jump to first/last.
 * - Tabs and panel are linked via id/aria-controls/aria-labelledby; focus
 *   follows selection so keyboard and screen-reader users stay oriented.
 */
export function Tabs({ tabs }: { tabs: { id: string; label: string; content: React.ReactNode }[] }) {
  const [active, setActive] = useState(tabs[0]?.id);
  const baseId = useId().replace(/:/g, "");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function select(index: number, focus: boolean): void {
    const tab = tabs[(index + tabs.length) % tabs.length];
    if (!tab) return;
    setActive(tab.id);
    if (focus) buttons.current[index]?.focus();
  }

  function activeIndex(): number {
    const found = tabs.findIndex((tab) => tab.id === active);
    return found < 0 ? 0 : found;
  }

  function onKeyDown(event: React.KeyboardEvent): void {
    const rtl = typeof document !== "undefined" && document.documentElement.dir === "rtl";
    const forward = rtl ? "ArrowLeft" : "ArrowRight";
    const backward = rtl ? "ArrowRight" : "ArrowLeft";
    const current = activeIndex();
    if (event.key === forward) {
      event.preventDefault();
      select(current + 1, true);
    } else if (event.key === backward) {
      event.preventDefault();
      select(current - 1, true);
    } else if (event.key === "Home") {
      event.preventDefault();
      select(0, true);
    } else if (event.key === "End") {
      event.preventDefault();
      select(tabs.length - 1, true);
    }
  }

  const current = tabs[activeIndex()];
  return (
    <div>
      <div className="tp-tabs" role="tablist" aria-label="sections" onKeyDown={onKeyDown}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(el) => {
              buttons.current[index] = el;
            }}
            role="tab"
            id={`${baseId}-tab-${tab.id}`}
            aria-selected={active === tab.id}
            aria-controls={`${baseId}-panel`}
            tabIndex={active === tab.id ? 0 : -1}
            className={active === tab.id ? "tp-tab-active" : undefined}
            onClick={() => select(index, false)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {current ? (
        <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-tab-${current.id}`} tabIndex={0}>
          {current.content}
        </div>
      ) : null}
    </div>
  );
}
