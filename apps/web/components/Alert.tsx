export function Alert({ message }: { message: string }) {
  return (
    <div className="tp-alert" role="alert">
      {message}
    </div>
  );
}
