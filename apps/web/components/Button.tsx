import type { ButtonHTMLAttributes, ReactNode } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
}

export function Button({ children, ...rest }: Props) {
  return (
    <button className="tp-primary" {...rest}>
      {children}
    </button>
  );
}
