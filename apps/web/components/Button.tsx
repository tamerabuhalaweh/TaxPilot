import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: Variant;
}

export function Button({ children, variant = "primary", className, ...rest }: Props) {
  return (
    <button className={["tp-button", `tp-button-${variant}`, className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </button>
  );
}
