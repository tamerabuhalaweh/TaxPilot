import { Icon } from "./Icon";

export function Alert({ message }: { message: string }) {
  return (
    <div className="tp-alert" role="alert">
      <Icon name="alert" />
      <span>{message}</span>
    </div>
  );
}
